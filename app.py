import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y CONEXIÓN
# ==========================================
st.set_page_config(page_title="Gestión de Entrenamiento General", layout="wide")

# Conexión a Supabase (Asegúrate de configurar tus secrets en Streamlit Cloud)
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_connection()
except Exception as e:
    st.error(f"Error de conexión a Supabase: {e}")
    st.stop()

# ==========================================
# INTERFAZ PRINCIPAL
# ==========================================
st.title("🎓 Sistema Global de Entrenamiento y Certificación")
st.info("Administración centralizada de capacitaciones. Modula por curso, evalúa vigencias y detecta brechas de cumplimiento.")

tab_dash, tab_semanal, tab_historico, tab_auditoria = st.tabs([
    "📊 Dashboard Interactivo", 
    "🔄 Actualización Semanal (Forms)", 
    "📥 Carga Masiva (Histórico)", 
    "🕵️ Auditoría de Brechas"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: ACTUALIZACIÓN SEMANAL (Motor de Inserción Principal)
# -----------------------------------------------------------------------------
with tab_semanal:
    st.markdown("#### 🔄 Procesamiento de Archivos Semanales de Inducción")
    st.write("Carga los reportes de Microsoft Forms. El sistema filtrará y estructurará automáticamente todos los cursos impartidos.")

    archivo_sem = st.file_uploader("Subir archivo Excel/CSV (Ej. Inducción Día 1 o Día 2)", type=["csv", "xlsx"], key="up_sem")

    if archivo_sem:
        with st.expander(f"⚙️ Procesando: {archivo_sem.name}", expanded=True):
            try:
                if archivo_sem.name.endswith('.csv'):
                    df_raw = pd.read_csv(archivo_sem)
                else:
                    df_raw = pd.read_excel(archivo_sem)

                cols = [str(c).strip() for c in df_raw.columns]
                df_raw.columns = cols
                
                # Búsqueda dinámica de columnas
                col_examen = next((c for c in cols if 'exámen va a presentar' in c.lower() or 'examen va a presentar' in c.lower()), None)
                col_num = next((c for c in cols if 'número de empleado' in c.lower() or 'numero de empleado' in c.lower()), None)
                col_nom = 'Nombre Completo'
                col_calif = next((c for c in cols if 'total de puntos' in c.lower()), None)
                col_fecha = next((c for c in cols if 'hora de finalización' in c.lower() or 'fecha que se realiza' in c.lower()), None)

                if col_nom not in cols:
                    st.error(f"❌ Falta columna exacta '{col_nom}'.")
                elif not col_examen or not col_num or not col_calif:
                    st.error("❌ Faltan columnas de control (Examen, ID o Total de puntos).")
                else:
                    # Sanitización del nombre del curso (eliminar espacios irrompibles de MS Forms)
                    df_raw[col_examen] = df_raw[col_examen].astype(str).str.replace(r'\xa0', ' ', regex=True).str.strip()
                    cursos_disponibles = df_raw[~df_raw[col_examen].isin(['nan', '', 'None', 'NaN'])][col_examen].unique().tolist()
                    
                    st.markdown("##### 📌 Configuración de Carga")
                    curso_seleccionado = st.selectbox("Selecciona el curso a procesar:", cursos_disponibles)

                    df_curso = df_raw[df_raw[col_examen] == curso_seleccionado].copy()
                    
                    # Limpieza de IDs
                    df_curso['num_emp_str'] = df_curso[col_num].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    mask_sin_id = df_curso['num_emp_str'].isin(['nan', '', 'None', 'N/A', '0']) | df_curso[col_num].isna()
                    
                    df_sin_id = df_curso[mask_sin_id]
                    df_clean = df_curso[~mask_sin_id]

                    st.success(f"📊 Registros listos para '{curso_seleccionado}': **{len(df_clean)}**")

                    if not df_sin_id.empty:
                        st.warning(f"⚠️ Se ignorarán {len(df_sin_id)} exámenes sin Número de Empleado.")

                    if not df_clean.empty and st.button(f"🚀 Guardar {len(df_clean)} registros de {curso_seleccionado}", type="primary"):
                        with st.spinner("Procesando transacciones..."):
                            
                            # 1. Obtener historial para la llave compuesta anti-duplicados
                            try:
                                resp_existentes = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, curso_evaluado").execute()
                                set_existentes = set()
                                for x in resp_existentes.data:
                                    e_db = str(x.get('num_empleado')).strip()
                                    f_db = str(x.get('fecha_entrenamiento'))[:10]
                                    c_db = str(x.get('curso_evaluado')).strip()
                                    set_existentes.add(f"{e_db}|{f_db}|{c_db}")
                            except:
                                set_existentes = set()

                            lote_insercion = []
                            registros_omitidos = 0
                            cols_preguntas = [c for c in cols if str(c).strip().startswith('Puntos:')]
                            
                            # Filtro estricto de conceptos que no son evaluables técnicamente
                            palabras_filtro = ['nombre', 'puesto', 'empleado', 'fecha', 'exámen', 'examen', 'qué te pareció', 'desempeño del', 'capacitador', 'comentarios', 'sugerencias']

                            for _, row in df_clean.iterrows():
                                emp_id = str(row['num_emp_str'])
                                
                                # Manejo de fechas
                                fecha_raw = row.get(col_fecha, datetime.now())
                                try:
                                    fecha_dt = pd.to_datetime(fecha_raw)
                                    fecha_val_str = fecha_dt.strftime('%Y-%m-%d')
                                except:
                                    fecha_dt = datetime.now()
                                    fecha_val_str = fecha_dt.strftime('%Y-%m-%d')

                                # 2. FILTRO ANTI-DUPLICADOS (Llave de 3 niveles)
                                llave_unica = f"{emp_id}|{fecha_val_str}|{curso_seleccionado}"
                                if llave_unica in set_existentes:
                                    registros_omitidos += 1
                                    continue
                                
                                raw_nombre = row.get(col_nom)
                                nombre_emp = "Sin Nombre" if pd.isna(raw_nombre) else str(raw_nombre).strip()[:100]

                                # Extracción de puntajes base 10
                                detalle = {}
                                for cp in cols_preguntas:
                                    if any(x in cp.lower() for x in palabras_filtro):
                                        continue 
                                    
                                    # Verificar si el usuario realmente contestó la pregunta (filtro de ramificación MS Forms)
                                    col_respuesta_texto = cp.replace("Puntos: ", "", 1).strip()
                                    if col_respuesta_texto in df_raw.columns:
                                        respuesta = row.get(col_respuesta_texto)
                                        if pd.isna(respuesta) or str(respuesta).strip() == '':
                                            continue 

                                    val_raw = row.get(cp, 0)
                                    try:
                                        detalle[cp] = 0.0 if pd.isna(float(val_raw)) else float(val_raw)
                                    except:
                                        detalle[cp] = 0.0

                                total_reactivos = len(detalle)
                                if total_reactivos > 0:
                                    aciertos = sum([1.0 for v in detalle.values() if float(v) > 0])
                                    calif_total = round((aciertos / total_reactivos) * 10.0, 2)
                                else:
                                    calif_total = 0.0

                                lote_insercion.append({
                                    "num_empleado": emp_id,
                                    "nombre_empleado": nombre_emp,
                                    "curso_evaluado": curso_seleccionado,
                                    "fecha_entrenamiento": fecha_dt.isoformat(),
                                    "calificacion_total": calif_total,
                                    "detalle_respuestas": detalle,
                                    "archivo_origen": archivo_sem.name
                                })

                            # 3. Inserción Masiva
                            if lote_insercion:
                                for i in range(0, len(lote_insercion), 300):
                                    supabase.table("entrenamientos_planta").insert(lote_insercion[i:i+300]).execute()
                                
                                st.success(f"🎉 Sincronización exitosa. {len(lote_insercion)} registros guardados.")
                                if registros_omitidos > 0:
                                    st.info(f"💡 Se omitieron {registros_omitidos} registros duplicados.")
                            else:
                                st.warning(f"No hay registros nuevos. Se omitieron {registros_omitidos} ya existentes.")
            except Exception as e:
                st.error(f"Error procesando el archivo: {e}")

# -----------------------------------------------------------------------------
# PESTAÑA 2: DASHBOARD INTERACTIVO
# -----------------------------------------------------------------------------
with tab_dash:
    st.markdown("#### 📊 Análisis de Calificaciones por Curso")
    
    try:
        # Cargar todos los registros para métricas globales
        resp_train = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, calificacion_total, curso_evaluado").execute()
        df_todo = pd.DataFrame(resp_train.data)
    except:
        df_todo = pd.DataFrame()

    if not df_todo.empty:
        cursos_db = df_todo['curso_evaluado'].unique().tolist()
        filtro_curso = st.selectbox("Filtrar métricas por curso:", ["Todos"] + cursos_db)
        
        if filtro_curso != "Todos":
            df_dash = df_todo[df_todo['curso_evaluado'] == filtro_curso]
        else:
            df_dash = df_todo
            
        df_dash['fecha_entrenamiento'] = pd.to_datetime(df_dash['fecha_entrenamiento'])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Exámenes Totales", len(df_dash))
        c2.metric("Promedio Global", f"{df_dash['calificacion_total'].mean():.2f} / 10")
        aprobados = len(df_dash[df_dash['calificacion_total'] >= 8.0])
        c3.metric("Tasa de Aprobación", f"{(aprobados/len(df_dash))*100:.1f}%")
        
    else:
        st.info("La base de datos está vacía. Inicia cargando archivos en la pestaña de Actualización.")

# -----------------------------------------------------------------------------
# PESTAÑA 3 & 4 (Estructura base para expansión)
# -----------------------------------------------------------------------------
with tab_historico:
    st.info("Sigue la misma lógica de la Pestaña de Actualización Semanal, pero adaptada para ingestar múltiples archivos a la vez iterando sobre `st.file_uploader(accept_multiple_files=True)`.")

with tab_auditoria:
    st.info("El escaneo cronológico ahora requerirá agrupar por `num_empleado` y por `curso_evaluado` para buscar brechas de tiempo (gaps) independientemente en cada materia.")
