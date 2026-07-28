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

# Agrega esta pestaña a tu configuración inicial
tab_dash, tab_semanal, tab_hc, tab_historico, tab_auditoria = st.tabs([
    "📊 Dashboard Interactivo", 
    "🔄 Actualización Semanal (Forms)", 
    "👥 Sincronización de Headcount", # <--- NUEVA PESTAÑA
    "📥 Carga Masiva (Histórico)", 
    "🕵️ Auditoría de Brechas"
])

with tab_semanal:
    st.markdown("#### 🔄 Procesamiento Masivo de Archivos Semanales (Todos los Cursos)")
    st.write("Carga los reportes de Microsoft Forms. El sistema filtrará y estructurará automáticamente todos los cursos impartidos en un solo paso.")

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
                    # 1. Sanitización masiva de la columna de cursos (eliminar \xa0)
                    df_raw[col_examen] = df_raw[col_examen].astype(str).str.replace(r'\xa0', ' ', regex=True).str.strip()
                    
                    # 2. Limpieza de IDs y filtrado de registros válidos
                    df_raw['num_emp_str'] = df_raw[col_num].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    # Máscara para registros que TIENEN curso Y TIENEN ID válido
                    mask_valida = (
                        ~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & 
                        ~df_raw['num_emp_str'].isin(['nan', '', 'None', 'N/A', '0']) & 
                        df_raw[col_num].notna()
                    )
                    
                    df_clean = df_raw[mask_valida].copy()
                    
                    # Identificar los que tienen curso pero fallaron por falta de ID
                    mask_sin_id = ~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & ~mask_valida
                    df_sin_id = df_raw[mask_sin_id].copy()

                    st.success(f"📊 **Resumen Global del Archivo:**\n- Total de filas crudas: **{len(df_raw)}**\n- Registros válidos listos para guardar: **{len(df_clean)}**")
                    
                    # Mostrar conteo por curso para control visual
                    if not df_clean.empty:
                        conteo_cursos = df_clean[col_examen].value_counts().reset_index()
                        conteo_cursos.columns = ['Curso Detectado', 'Cantidad de Exámenes']
                        st.markdown("##### 📌 Cursos Identificados en el Archivo")
                        st.dataframe(conteo_cursos, hide_index=True, use_container_width=True)

                    if not df_sin_id.empty:
                        st.warning(f"⚠️ Se ignorarán {len(df_sin_id)} exámenes válidos porque no tienen Número de Empleado asignado.")

                    # Botón unificado
                    if not df_clean.empty and st.button("🚀 Procesar y Guardar Todos los Cursos", type="primary"):
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
                            
                            palabras_filtro = ['nombre', 'puesto', 'empleado', 'fecha', 'exámen', 'examen', 'qué te pareció', 'desempeño del', 'capacitador', 'comentarios', 'sugerencias']

                            for _, row in df_clean.iterrows():
                                emp_id = str(row['num_emp_str'])
                                curso_actual = str(row[col_examen]).strip()
                                
                                # Manejo de fechas
                                fecha_raw = row.get(col_fecha, datetime.now())
                                try:
                                    fecha_dt = pd.to_datetime(fecha_raw)
                                    fecha_val_str = fecha_dt.strftime('%Y-%m-%d')
                                except:
                                    fecha_dt = datetime.now()
                                    fecha_val_str = fecha_dt.strftime('%Y-%m-%d')

                                # 2. FILTRO ANTI-DUPLICADOS DINÁMICO
                                llave_unica = f"{emp_id}|{fecha_val_str}|{curso_actual}"
                                if llave_unica in set_existentes:
                                    registros_omitidos += 1
                                    continue
                                
                                raw_nombre = row.get(col_nom)
                                nombre_emp = "Sin Nombre" if pd.isna(raw_nombre) else str(raw_nombre).strip()[:100]

                                # --- REEMPLAZA DESDE AQUÍ ---
                                # Extracción de puntajes base 10
                                detalle = {}
                                for cp in cols_preguntas:
                                    if any(x in cp.lower() for x in palabras_filtro):
                                        continue 
                                    
                                    col_respuesta_texto = cp.replace("Puntos: ", "", 1).strip()
                                    
                                    # Solo evaluamos la pregunta si hay una respuesta de texto válida
                                    if col_respuesta_texto in df_raw.columns:
                                        respuesta = row.get(col_respuesta_texto)
                                        # Si la respuesta es NaN o cadena vacía, ignoramos la pregunta entera
                                        if pd.isna(respuesta) or str(respuesta).strip() == '':
                                            continue 
                                    else:
                                        # Si por algún motivo la columna de texto no existe pero sí la de puntos
                                        # asumimos que no se debe contar (pasa con bugs de Forms)
                                        continue

                                    val_raw = row.get(cp, 0)
                                    try:
                                        detalle[cp] = 0.0 if pd.isna(float(val_raw)) else float(val_raw)
                                    except:
                                        detalle[cp] = 0.0

                                total_reactivos = len(detalle)
                                if total_reactivos > 0:
                                    # Cuenta cuántas respuestas tuvieron un valor mayor a 0
                                    aciertos = sum([1.0 for v in detalle.values() if float(v) > 0])
                                    calif_total = round((aciertos / total_reactivos) * 10.0, 2)
                                else:
                                    calif_total = 0.0
                                # --- HASTA AQUÍ ---

                                lote_insercion.append({
                                    "num_empleado": emp_id,
                                    "nombre_empleado": nombre_emp,
                                    "curso_evaluado": curso_actual,
                                    "fecha_entrenamiento": fecha_dt.isoformat(),
                                    "calificacion_total": calif_total,
                                    "detalle_respuestas": detalle,
                                    "archivo_origen": archivo_sem.name
                                })

                            # 3. Inserción Masiva
                            if lote_insercion:
                                for i in range(0, len(lote_insercion), 300):
                                    supabase.table("entrenamientos_planta").insert(lote_insercion[i:i+300]).execute()
                                
                                st.success(f"🎉 Sincronización exitosa. {len(lote_insercion)} registros guardados en la base de datos.")
                                if registros_omitidos > 0:
                                    st.info(f"💡 Se omitieron {registros_omitidos} registros duplicados (mismo número de empleado, mismo curso, misma fecha).")
                            else:
                                st.warning(f"No hay registros nuevos para guardar. Se omitieron {registros_omitidos} ya existentes.")
            except Exception as e:
                st.error(f"Error procesando el archivo: {e}")

# -----------------------------------------------------------------------------
# PESTAÑA 2: DASHBOARD INTERACTIVO
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# PESTAÑA: DASHBOARD INTERACTIVO (Filtro estricto a personal ACTIVO)
# -----------------------------------------------------------------------------
with tab_dash:
    st.markdown("#### 📊 Dashboard de Certificación y Cumplimiento")
    st.write("Las métricas presentadas aquí están cruzadas con el Headcount actual. **Excluyen automáticamente** las evaluaciones del personal dado de baja.")
    
    with st.spinner("Sincronizando padrón y evaluaciones..."):
        try:
            # 1. Traer SOLO personal con estatus 'Active' de la tabla maestra
            resp_emp = supabase.table("empleados_planta").select("num_empleado, nombre_completo, departamento, area").eq("estatus", "Active").execute()
            df_activos = pd.DataFrame(resp_emp.data)
            
            # 2. Traer TODO el historial de entrenamientos
            resp_train = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, calificacion_total, curso_evaluado").execute()
            df_train = pd.DataFrame(resp_train.data)
            
        except Exception as e:
            df_activos = pd.DataFrame()
            df_train = pd.DataFrame()
            st.error(f"Error al conectar con la base de datos: {e}")

    if not df_activos.empty and not df_train.empty:
        # 3. EL CROSS CHECK (INNER JOIN): Descarta a cualquiera que no esté en df_activos
        df_dash = pd.merge(df_train, df_activos, on="num_empleado", how="inner")
        
        if not df_dash.empty:
            df_dash['fecha_entrenamiento'] = pd.to_datetime(df_dash['fecha_entrenamiento'])
            
            # --- FILTROS DE INTERFAZ ---
            c_filtro1, c_filtro2 = st.columns(2)
            cursos_db = sorted(df_dash['curso_evaluado'].unique().tolist())
            filtro_curso = c_filtro1.selectbox("Filtro por Curso:", ["Todos"] + cursos_db)
            
            deptos_db = sorted(df_dash['departamento'].dropna().unique().tolist())
            filtro_depto = c_filtro2.selectbox("Filtro por Departamento:", ["Todos"] + deptos_db)
            
            # Aplicar filtros
            df_filtrado = df_dash.copy()
            if filtro_curso != "Todos":
                df_filtrado = df_filtrado[df_filtrado['curso_evaluado'] == filtro_curso]
            if filtro_depto != "Todos":
                df_filtrado = df_filtrado[df_filtrado['departamento'] == filtro_depto]
            
            if not df_filtrado.empty:
                # --- KPI CARDS ---
                c1, c2, c3 = st.columns(3)
                c1.metric("Exámenes Vigentes (HC Activo)", len(df_filtrado))
                
                promedio = df_filtrado['calificacion_total'].mean()
                c2.metric("Promedio Global", f"{promedio:.2f} / 10.0")
                
                aprobados = len(df_filtrado[df_filtrado['calificacion_total'] >= 8.0])
                tasa_aprobacion = (aprobados / len(df_filtrado)) * 100 if len(df_filtrado) > 0 else 0
                c3.metric("Tasa de Aprobación (≥ 8.0)", f"{tasa_aprobacion:.1f}%")
                
                st.divider()
                
                # --- GRÁFICAS CON TU ESQUEMA DE COLORES ---
                col_graf1, col_graf2 = st.columns(2)
                
                # Gráfica 1: Distribución de Aprobación
                df_filtrado['Estatus'] = df_filtrado['calificacion_total'].apply(lambda x: 'Aprobado (≥ 8)' if x >= 8 else 'Reprobado (< 8)')
                resumen_estatus = df_filtrado['Estatus'].value_counts().reset_index()
                resumen_estatus.columns = ['Estatus', 'Cantidad']
                
                # Colores corporativos: Gris cálido para aprobados, Rojo corporativo para reprobados
                mapa_colores = {'Aprobado (≥ 8)': '#A29894', 'Reprobado (< 8)': '#D4002B'}
                
                fig_pie = px.pie(
                    resumen_estatus, 
                    values='Cantidad', 
                    names='Estatus', 
                    title="Distribución de Aprobación en Planta", 
                    color='Estatus', 
                    color_discrete_map=mapa_colores
                )
                col_graf1.plotly_chart(fig_pie, use_container_width=True)
                
                # Gráfica 2: Desempeño por Departamento
                if filtro_depto == "Todos":
                    resumen_deptos = df_filtrado.groupby('departamento').agg(
                        Examenes=('num_empleado', 'count'),
                        Promedio=('calificacion_total', 'mean')
                    ).reset_index().sort_values('Examenes', ascending=False).head(10)
                    
                    fig_bar = px.bar(
                        resumen_deptos, 
                        x='Promedio', 
                        y='departamento', 
                        orientation='h', 
                        title="Promedio por Departamento (Top 10 Volumen)", 
                        color_discrete_sequence=['#8D1537'], # Rojo Oscuro corporativo
                        text_auto='.1f'
                    )
                    fig_bar.update_layout(
                        yaxis={'categoryorder':'total ascending'},
                        plot_bgcolor='#F2F2F2',
                        paper_bgcolor='#FFFFFF',
                        font=dict(color='#000000')
                    )
                    col_graf2.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.warning("No hay datos para los filtros seleccionados.")
        else:
            st.info("Ningún examen coincide con el padrón actual de empleados activos. Verifica que el headcount esté cargado.")
    else:
        st.info("Faltan datos. Asegúrate de haber cargado el Headcount en su pestaña correspondiente y los históricos de entrenamiento.")
# -----------------------------------------------------------------------------
# PESTAÑA: GESTIÓN DE HEADCOUNT (ALTAS Y BAJAS AUTOMÁTICAS)
# -----------------------------------------------------------------------------
with tab_hc:
    st.markdown("#### 👥 Sincronización del Headcount Maestro")
    st.write("Sube el reporte de RH (ej. HC_Snapshot). El sistema actualizará datos, registrará altas y dará de baja por descarte a quienes ya no figuren.")

    archivo_hc = st.file_uploader("Subir reporte semanal de Headcount", type=["xlsx", "xls"], key="up_hc")

    if archivo_hc:
        with st.spinner("Leyendo la pestaña 'HC_Snapshot' del archivo..."):
            try:
                # El sistema debe apuntar directamente a la hoja donde están los datos
                df_hc = pd.read_excel(archivo_hc, sheet_name='HC_Snapshot')
                
                col_id = 'Pers.No.'
                
                # Estandarización de IDs
                df_hc[col_id] = df_hc[col_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                df_hc = df_hc[(df_hc[col_id] != 'nan') & (df_hc[col_id] != '') & (df_hc[col_id].notna())]
                
                st.success(f"✅ Se leyeron {len(df_hc)} empleados vigentes en el archivo.")

                if st.button("🔄 Procesar Altas, Bajas y Actualizaciones", type="primary"):
                    with st.spinner("Cruzando datos con la base actual..."):
                        
                        # 1. Traer a todos los empleados de Supabase
                        try:
                            resp_db = supabase.table("empleados_planta").select("num_empleado, estatus").execute()
                            empleados_db = {str(x['num_empleado']): x['estatus'] for x in resp_db.data}
                        except Exception as e:
                            empleados_db = {}
                        
                        # 2. Identificar BAJAS por ausencia
                        ids_excel = set(df_hc[col_id].tolist())
                        ids_db = set(empleados_db.keys())
                        
                        bajas_detectadas = ids_db - ids_excel
                        # Solo procesamos la baja si no estaba ya como inactivo
                        bajas_a_procesar = [emp for emp in bajas_detectadas if empleados_db[emp] != 'Inactive']
                        
                        # 3. Preparar el bloque de UPSERT (Altas y actualizaciones de puesto/área)
                        lote_upsert = []
                        for _, row in df_hc.iterrows():
                            emp_id = row[col_id]
                            
                            # Limpiar fecha de ingreso
                            fecha_raw = row.get('Join Date')
                            try:
                                fecha_ingreso = pd.to_datetime(fecha_raw).strftime('%Y-%m-%d')
                            except:
                                fecha_ingreso = None
                                
                            # Absorber todas las columnas del Excel en formato crudo para el JSON
                            # Pandas devuelve objetos Timestamp que no son serializables por JSON, los pasamos a string
                            datos_json_crudo = row.fillna("").to_dict()
                            datos_json = {}
                            for key, value in datos_json_crudo.items():
                                # Si el valor es de tipo Timestamp de pandas o un date de Python, lo pasamos a texto
                                if isinstance(value, pd.Timestamp) or type(value).__name__ in ['Timestamp', 'date', 'datetime']:
                                    datos_json[key] = str(value)
                                else:
                                    datos_json[key] = value
                            
                            estatus_reportado = str(row.get('Employment Status', 'Active')).strip()
                            
                            lote_upsert.append({
                                "num_empleado": emp_id,
                                "nombre_completo": str(row.get('Personnel Name', 'N/D')).strip(),
                                "estatus": estatus_reportado,
                                "fecha_ingreso": fecha_ingreso,
                                "puesto": str(row.get('Job Title', 'N/D')).strip(),
                                "departamento": str(row.get('Depto Eng', row.get('Cost Center', 'N/D'))).strip(),
                                "area": str(row.get('Area', 'N/D')).strip(),
                                "supervisor": str(row.get('Direct_Supervisor', row.get('Manager', 'N/D'))).strip(),
                                "clase_categoria": str(row.get('ClassCateg', 'N/D')).strip(),
                                "datos_completos": datos_json,
                                "ultima_actualizacion": datetime.now().isoformat()
                            })
                        
                        # 4. Impactar Base de Datos
                        
                        # A) Ejecutar Bajas
                        if bajas_a_procesar:
                            # Iteramos porque Supabase Python client no soporta un "update in list" nativo rápido
                            for emp in bajas_a_procesar:
                                supabase.table("empleados_planta").update({"estatus": "Inactive", "ultima_actualizacion": datetime.now().isoformat()}).eq("num_empleado", emp).execute()
                                
                        # B) Ejecutar Upserts (Altas/Cambios)
                        if lote_upsert:
                            for i in range(0, len(lote_upsert), 300):
                                supabase.table("empleados_planta").upsert(lote_upsert[i:i+300]).execute()
                                
                        st.success(f"✅ **¡Padrón maestro actualizado exitosamente!**\n\n- **Personal procesado (Altas/Cambios):** {len(lote_upsert)}\n- **Bajas Automáticas procesadas:** {len(bajas_a_procesar)}")
                        
            except Exception as e:
                st.error(f"Error procesando el archivo: {e}")
# -----------------------------------------------------------------------------
# PESTAÑA: CARGA MASIVA DE HISTÓRICO
# -----------------------------------------------------------------------------
with tab_historico:
    st.markdown("#### 📥 Carga Masiva de Historial (Múltiples Archivos)")
    st.write("Sube todos tus archivos antiguos de Forms a la vez. El sistema procesará cada Excel/CSV iterativamente, separará los cursos y descartará lo que ya esté en la base de datos.")

    archivos_hist = st.file_uploader("Seleccionar archivos históricos", type=["csv", "xlsx"], accept_multiple_files=True, key="up_hist")

    if archivos_hist:
        if st.button("🚀 Procesar Todo el Histórico", type="primary"):
            
            with st.spinner("Descargando llaves de la base de datos para evitar duplicados..."):
                # 1. Traer historial existente UNA SOLA VEZ para todos los archivos
                try:
                    resp_existentes = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, curso_evaluado").execute()
                    set_existentes = set()
                    for x in resp_existentes.data:
                        e_db = str(x.get('num_empleado')).strip()
                        f_db = str(x.get('fecha_entrenamiento'))[:10]
                        c_db = str(x.get('curso_evaluado')).strip()
                        set_existentes.add(f"{e_db}|{f_db}|{c_db}")
                except Exception as e:
                    set_existentes = set()
                    st.warning(f"Error al conectar con la base de datos: {e}")

            lote_insercion_global = []
            registros_omitidos_global = 0
            archivos_procesados = 0
            archivos_con_error = []

            # Filtro estricto de conceptos que no son evaluables
            palabras_filtro = ['nombre', 'puesto', 'empleado', 'fecha', 'exámen', 'examen', 'qué te pareció', 'que te parecio', 'desempeño del', 'capacitador', 'comentarios', 'sugerencias', 'instructor']

            barra_progreso = st.progress(0)
            
            for idx, archivo in enumerate(archivos_hist):
                try:
                    if archivo.name.endswith('.csv'):
                        df_raw = pd.read_csv(archivo)
                    else:
                        df_raw = pd.read_excel(archivo)

                    cols = [str(c).strip() for c in df_raw.columns]
                    df_raw.columns = cols
                    
                    # Búsqueda dinámica de columnas (relajando el nombre para históricos)
                    col_examen = next((c for c in cols if 'exámen va a presentar' in c.lower() or 'examen va a presentar' in c.lower()), None)
                    col_num = next((c for c in cols if 'número de empleado' in c.lower() or 'numero de empleado' in c.lower()), None)
                    col_nom = next((c for c in cols if 'nombre' in c.lower()), 'Nombre Completo')
                    col_fecha = next((c for c in cols if 'hora de finalización' in c.lower() or 'fecha que se realiza' in c.lower()), None)
                    
                    # Si no tiene columnas clave, lo reportamos y pasamos al siguiente archivo
                    if not col_examen or not col_num:
                        archivos_con_error.append(f"{archivo.name} (Faltan columnas clave como Examen o Número de Empleado)")
                        continue

                    # Sanitización masiva
                    df_raw[col_examen] = df_raw[col_examen].astype(str).str.replace(r'\xa0', ' ', regex=True).str.strip()
                    df_raw['num_emp_str'] = df_raw[col_num].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    # Filtrado de registros válidos
                    mask_valida = (
                        ~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & 
                        ~df_raw['num_emp_str'].isin(['nan', '', 'None', 'N/A', '0']) & 
                        df_raw[col_num].notna()
                    )
                    df_clean = df_raw[mask_valida]

                    cols_preguntas = [c for c in cols if str(c).strip().startswith('Puntos:')]

                    for _, row in df_clean.iterrows():
                        emp_id = str(row['num_emp_str'])
                        curso_actual = str(row[col_examen]).strip()
                        
                        # Fechas
                        fecha_raw = row.get(col_fecha, datetime.now())
                        try:
                            fecha_dt = pd.to_datetime(fecha_raw)
                            fecha_val_str = fecha_dt.strftime('%Y-%m-%d')
                        except:
                            fecha_dt = datetime.now()
                            fecha_val_str = fecha_dt.strftime('%Y-%m-%d')

                        # Anti-duplicados (Compara contra BD y contra lo que se va acumulando en esta misma sesión)
                        llave_unica = f"{emp_id}|{fecha_val_str}|{curso_actual}"
                        if llave_unica in set_existentes:
                            registros_omitidos_global += 1
                            continue
                        
                        raw_nombre = row.get(col_nom)
                        nombre_emp = "Sin Nombre" if pd.isna(raw_nombre) else str(raw_nombre).strip()[:100]

                        # Extraer puntajes
                        detalle = {}
                        for cp in cols_preguntas:
                            if any(x in cp.lower() for x in palabras_filtro):
                                continue 
                            
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

                        lote_insercion_global.append({
                            "num_empleado": emp_id,
                            "nombre_empleado": nombre_emp,
                            "curso_evaluado": curso_actual,
                            "fecha_entrenamiento": fecha_dt.isoformat(),
                            "calificacion_total": calif_total,
                            "detalle_respuestas": detalle,
                            "archivo_origen": archivo.name
                        })
                        
                        # Alimentar el set temporal para que un archivo duplicado en la misma carga no se inserte 2 veces
                        set_existentes.add(llave_unica)
                        
                    archivos_procesados += 1
                except Exception as e:
                    archivos_con_error.append(f"{archivo.name} (Error: {e})")
                
                # Actualizar barra de progreso visual en Streamlit
                barra_progreso.progress((idx + 1) / len(archivos_hist))

            # 3. Inserción masiva final (fuera del ciclo de los archivos)
            if lote_insercion_global:
                with st.spinner("Insertando lote masivo en Supabase... esto puede tomar unos segundos."):
                    for i in range(0, len(lote_insercion_global), 300):
                        supabase.table("entrenamientos_planta").insert(lote_insercion_global[i:i+300]).execute()
                
                st.success(f"🎉 **¡Carga Histórica Completada!**\n\n- **Archivos procesados:** {archivos_procesados}\n- **Registros guardados en BD:** {len(lote_insercion_global)}\n- **Duplicados omitidos:** {registros_omitidos_global}")
            else:
                st.info(f"Se procesaron {len(archivos_hist)} archivo(s), pero no hubo registros nuevos. Se omitieron {registros_omitidos_global} duplicados.")

            if archivos_con_error:
                st.error("⚠️ Se encontraron problemas con los siguientes archivos y fueron ignorados:")
                for err in archivos_con_error:
                    st.write(f"- {err}")

with tab_auditoria:
    st.info("El escaneo cronológico ahora requerirá agrupar por `num_empleado` y por `curso_evaluado` para buscar brechas de tiempo (gaps) independientemente en cada materia.")
