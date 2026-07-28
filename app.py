import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time
import streamlit.components.v1 as components

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

# --- CONSOLIDACIÓN DE PESTAÑAS ---
tab_dash, tab_gestion_datos, tab_consulta, tab_certificados, tab_auditoria = st.tabs([
    "📊 Dashboard Interactivo", 
    "⚙️ Gestión de Datos", 
    "🔍 Consulta y Actualización",
    "🎓 Emisión de Certificados", # <--- NUEVA PESTAÑA
    "🕵️ Auditoría de Brechas"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: DASHBOARD INTERACTIVO Y PROYECCIÓN
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
            resp_train = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, calificacion_total, curso_evaluado, detalle_respuestas").execute()
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
            
            # Sub-pestañas para organizar la vista gerencial y el overview operativo
            dash_metricas, dash_calendario = st.tabs(["📈 Métricas Globales", "📅 Calendario de Reentrenamientos"])

            # =================================================================
            # VISTA 1: MÉTRICAS GLOBALES Y GRÁFICAS
            # =================================================================
            with dash_metricas:
                c_filtro1, c_filtro2 = st.columns(2)
                cursos_db = sorted(df_dash['curso_evaluado'].unique().tolist())
                filtro_curso = c_filtro1.selectbox("Filtro por Curso:", ["Todos"] + cursos_db, key="dash_curso")
                
                deptos_db = sorted(df_dash['departamento'].dropna().unique().tolist())
                filtro_depto = c_filtro2.selectbox("Filtro por Departamento:", ["Todos"] + deptos_db, key="dash_depto")
                
                df_filtrado = df_dash.copy()
                if filtro_curso != "Todos":
                    df_filtrado = df_filtrado[df_filtrado['curso_evaluado'] == filtro_curso]
                if filtro_depto != "Todos":
                    df_filtrado = df_filtrado[df_filtrado['departamento'] == filtro_depto]
                
                if not df_filtrado.empty:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Exámenes Vigentes (HC Activo)", len(df_filtrado))
                    
                    promedio = df_filtrado['calificacion_total'].mean()
                    c2.metric("Promedio Global", f"{promedio:.2f} / 10.0")
                    
                    aprobados = len(df_filtrado[df_filtrado['calificacion_total'] >= 8.0])
                    tasa_aprobacion = (aprobados / len(df_filtrado)) * 100 if len(df_filtrado) > 0 else 0
                    c3.metric("Tasa de Aprobación (≥ 8.0)", f"{tasa_aprobacion:.1f}%")
                    
                    st.divider()
                    
                    col_graf1, col_graf2 = st.columns(2)
                    
                    df_filtrado['Estatus'] = df_filtrado['calificacion_total'].apply(lambda x: 'Aprobado (≥ 8)' if x >= 8 else 'Reprobado (< 8)')
                    resumen_estatus = df_filtrado['Estatus'].value_counts().reset_index()
                    resumen_estatus.columns = ['Estatus', 'Cantidad']
                    
                    mapa_colores = {'Aprobado (≥ 8)': '#A29894', 'Reprobado (< 8)': '#D4002B'}
                    
                    fig_pie = px.pie(
                        resumen_estatus, values='Cantidad', names='Estatus', 
                        title="Distribución de Aprobación en Planta", color='Estatus', color_discrete_map=mapa_colores
                    )
                    col_graf1.plotly_chart(fig_pie, use_container_width=True)
                    
                    if filtro_depto == "Todos":
                        resumen_deptos = df_filtrado.groupby('departamento').agg(
                            Examenes=('num_empleado', 'count'), Promedio=('calificacion_total', 'mean')
                        ).reset_index().sort_values('Examenes', ascending=False).head(10)
                        
                        fig_bar = px.bar(
                            resumen_deptos, x='Promedio', y='departamento', orientation='h', 
                            title="Promedio por Departamento (Top 10 Volumen)", color_discrete_sequence=['#8D1537'], text_auto='.1f'
                        )
                        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, plot_bgcolor='#F2F2F2', paper_bgcolor='#FFFFFF', font=dict(color='#000000'))
                        col_graf2.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.warning("No hay datos para los filtros seleccionados.")

            # =================================================================
            # VISTA 2: CALENDARIO DE REENTRENAMIENTOS (OVERVIEW)
            # =================================================================
            with dash_calendario:
                st.markdown("#### 📅 Overview de Necesidades Próximas")
                st.write("Identifica al personal que requiere reentrenamiento. Excluye a quienes tienen certificaciones permanentes.")
                
                # 1. Obtener el último examen de cada empleado por curso (para saber su vigencia actual)
                df_latest_cal = df_dash.sort_values('fecha_entrenamiento', ascending=False).drop_duplicates(subset=['num_empleado', 'curso_evaluado'], keep='first').copy()
                
                # 2. Extraer periodicidad matemática
                def extraer_meses(detalle):
                    if isinstance(detalle, dict) and 'periodicidad_meses' in detalle:
                        return int(detalle['periodicidad_meses'])
                    return 12 # Anual por defecto

                df_latest_cal['meses_vigencia'] = df_latest_cal['detalle_respuestas'].apply(extraer_meses)
                
                # Filtramos a los que tienen periodicidad "0" (Permanentes), no necesitan estar en el calendario
                df_calendario = df_latest_cal[df_latest_cal['meses_vigencia'] > 0].copy()
                
                if not df_calendario.empty:
                    # Calcular fechas dinámicas
                    df_calendario['Fecha de Vencimiento'] = df_calendario.apply(lambda row: (row['fecha_entrenamiento'] + relativedelta(months=row['meses_vigencia'])).date(), axis=1)
                    df_calendario['Mes de Vencimiento'] = pd.to_datetime(df_calendario['Fecha de Vencimiento']).dt.to_period('M')
                    
                    # Selector dinámico de alcance temporal
                    c_tiempo1, c_tiempo2 = st.columns(2)
                    opciones_tiempo = {
                        "Este Mes y Siguiente": 2, 
                        "Próximos 3 Meses": 3, 
                        "Próximos 6 Meses": 6, 
                        "Ver Vencidos e Histórico Completo": 999
                    }
                    rango_seleccionado = c_tiempo1.selectbox("Rango de Proyección:", list(opciones_tiempo.keys()))
                    filtro_curso_cal = c_tiempo2.selectbox("Filtrar Requerimiento por Curso:", ["Todos"] + sorted(df_calendario['curso_evaluado'].unique().tolist()))
                    
                    # Aplicar filtros
                    if filtro_curso_cal != "Todos":
                        df_calendario = df_calendario[df_calendario['curso_evaluado'] == filtro_curso_cal]
                        
                    hoy = datetime.now().date()
                    if opciones_tiempo[rango_seleccionado] != 999:
                        limite = hoy + relativedelta(months=opciones_tiempo[rango_seleccionado])
                        # Mostrar vencidos (fecha < hoy) y los próximos en el rango seleccionado
                        df_calendario = df_calendario[df_calendario['Fecha de Vencimiento'] <= limite]
                        
                    # Preparamos la tabla visual
                    df_show_cal = df_calendario[['num_empleado', 'nombre_completo', 'departamento', 'curso_evaluado', 'Fecha de Vencimiento']].copy()
                    df_show_cal.columns = ['ID Empleado', 'Nombre', 'Departamento', 'Curso Requerido', 'Fecha Límite']
                    df_show_cal = df_show_cal.sort_values('Fecha Límite')
                    
                    # Semáforo de urgencia
                    def estilar_urgencia(val):
                        if isinstance(val, date):
                            if val < hoy:
                                return 'background-color: #ffcccc; color: #cc0000; font-weight: bold;' # Vencido
                            elif val <= (hoy + timedelta(days=15)):
                                return 'background-color: #f7aa67; color: black; font-weight: bold;' # Crítico (Naranja)
                            elif val <= (hoy + timedelta(days=45)):
                                return 'background-color: #fff2cc; color: #b38600;' # Próximo (Amarillo)
                            else:
                                return 'background-color: #e2f0d9; color: #385723;' # Óptimo (Verde)
                        return ''

                    st.dataframe(df_show_cal.style.map(estilar_urgencia, subset=['Fecha Límite']), use_container_width=True, hide_index=True)
                    
                    st.caption("🔴 Rojo: Vencido | 🟠 Naranja: Vence en ≤ 15 días | 🟡 Amarillo: Vence en ≤ 45 días | 🟢 Verde: Vigente")
                else:
                    st.info("Todo el personal activo cuenta con certificaciones permanentes. No hay reentrenamientos programados.")

        else:
            st.info("Ningún examen coincide con el padrón actual de empleados activos. Verifica que el headcount esté cargado.")
    else:
        st.info("Faltan datos. Asegúrate de haber cargado el Headcount y los históricos de entrenamiento.")

# -----------------------------------------------------------------------------
# PESTAÑA 2: GESTIÓN DE DATOS (Centralización de cargas)
# -----------------------------------------------------------------------------
with tab_gestion_datos:
    st.markdown("### ⚙️ Centro de Carga y Sincronización")
    
    opcion_carga = st.radio(
        "Selecciona el módulo de datos que deseas operar:",
        ["🔄 Actualización Semanal (Exámenes)", "👥 Headcount (Altas/Bajas)", "📥 Carga Histórica (Masiva)"],
        horizontal=True
    )
    
    st.divider()

    # --- MÓDULO 1: ACTUALIZACIÓN SEMANAL ---
    if opcion_carga == "🔄 Actualización Semanal (Exámenes)":
        st.markdown("#### 🔄 Procesamiento Masivo de Archivos Semanales")
        st.write("Carga los reportes de Microsoft Forms. El sistema filtrará y estructurará automáticamente todos los cursos impartidos en un solo paso.")

        archivo_sem = st.file_uploader("Subir archivo Excel/CSV (Ej. Inducción Día 1 o Día 2)", type=["csv", "xlsx"], key="up_sem")

        if archivo_sem:
            with st.expander(f"⚙️ Procesando: {archivo_sem.name}", expanded=True):
                try:
                    df_raw = pd.read_csv(archivo_sem) if archivo_sem.name.endswith('.csv') else pd.read_excel(archivo_sem)
                    cols = [str(c).strip() for c in df_raw.columns]
                    df_raw.columns = cols
                    
                    col_examen = next((c for c in cols if 'exámen va a presentar' in c.lower() or 'examen va a presentar' in c.lower()), None)
                    col_num = next((c for c in cols if 'número de empleado' in c.lower() or 'numero de empleado' in c.lower()), None)
                    col_nom = 'Nombre Completo'
                    col_calif = next((c for c in cols if 'total de puntos' in c.lower()), None)
                    col_fecha = next((c for c in cols if 'hora de finalización' in c.lower() or 'fecha que se realiza' in c.lower()), None)

                    if col_nom not in cols or not col_examen or not col_num or not col_calif:
                        st.error("❌ Faltan columnas de control (Nombre Completo, Examen, ID o Total de puntos).")
                    else:
                        df_raw[col_examen] = df_raw[col_examen].astype(str).str.replace(r'\xa0', ' ', regex=True).str.strip()
                        df_raw['num_emp_str'] = df_raw[col_num].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        
                        mask_valida = (~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & ~df_raw['num_emp_str'].isin(['nan', '', 'None', 'N/A', '0']) & df_raw[col_num].notna())
                        df_clean = df_raw[mask_valida].copy()
                        df_sin_id = df_raw[~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & ~mask_valida].copy()

                        st.success(f"📊 **Resumen:** Filas crudas: **{len(df_raw)}** | Válidas para guardar: **{len(df_clean)}**")
                        
                        if not df_sin_id.empty:
                            st.warning(f"⚠️ Se ignorarán {len(df_sin_id)} exámenes válidos sin Número de Empleado asignado.")

                        if not df_clean.empty and st.button("🚀 Procesar y Guardar Todos los Cursos", type="primary"):
                            with st.spinner("Procesando transacciones..."):
                                try:
                                    resp_existentes = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, curso_evaluado").execute()
                                    set_existentes = {f"{str(x.get('num_empleado')).strip()}|{str(x.get('fecha_entrenamiento'))[:10]}|{str(x.get('curso_evaluado')).strip()}" for x in resp_existentes.data}
                                except:
                                    set_existentes = set()

                                lote_insercion = []
                                registros_omitidos = 0
                                cols_preguntas = [c for c in cols if str(c).strip().startswith('Puntos:')]
                                
                                palabras_filtro = ['nombre', 'puesto', 'empleado', 'fecha', 'exámen', 'examen', 'instructor', 'demostró dominio', 'explicó los temas', 'resolvió adecuadamente', 'manejó bien el tiempo', 'contenido del curso fue útil', 'podría mejorar', 'lee a continuación y califica']

                                for _, row in df_clean.iterrows():
                                    emp_id = str(row['num_emp_str'])
                                    curso_actual = str(row[col_examen]).strip()
                                    
                                    fecha_raw = row.get(col_fecha, datetime.now())
                                    try:
                                        fecha_dt = pd.to_datetime(fecha_raw)
                                        fecha_val_str = fecha_dt.strftime('%Y-%m-%d')
                                    except:
                                        fecha_dt = datetime.now()
                                        fecha_val_str = fecha_dt.strftime('%Y-%m-%d')

                                    llave_unica = f"{emp_id}|{fecha_val_str}|{curso_actual}"
                                    if llave_unica in set_existentes:
                                        registros_omitidos += 1
                                        continue
                                    
                                    raw_nombre = row.get(col_nom)
                                    nombre_emp = "Sin Nombre" if pd.isna(raw_nombre) else str(raw_nombre).strip()[:100]

                                    detalle = {}
                                    for cp in cols_preguntas:
                                        col_respuesta_texto = cp.replace("Puntos: ", "", 1).strip()
                                        if any(x in col_respuesta_texto.lower() for x in palabras_filtro): continue 
                                        
                                        if col_respuesta_texto in df_raw.columns:
                                            respuesta = row.get(col_respuesta_texto)
                                            if pd.notna(respuesta) and str(respuesta).strip() != '':
                                                val_raw = row.get(cp, 0)
                                                try: puntos = 0.0 if pd.isna(float(val_raw)) else float(val_raw)
                                                except: puntos = 0.0
                                                detalle[cp] = puntos

                                    total_reactivos = len(detalle)
                                    if total_reactivos > 0:
                                        aciertos = sum([1.0 for v in detalle.values() if float(v) > 0])
                                        calif_total = round((aciertos / total_reactivos) * 10.0, 2)
                                    else:
                                        calif_total = 0.0

                                    lote_insercion.append({
                                        "num_empleado": emp_id, "nombre_empleado": nombre_emp, "curso_evaluado": curso_actual,
                                        "fecha_entrenamiento": fecha_dt.isoformat(), "calificacion_total": calif_total,
                                        "detalle_respuestas": detalle, "archivo_origen": archivo_sem.name
                                    })

                                if lote_insercion:
                                    for i in range(0, len(lote_insercion), 300):
                                        supabase.table("entrenamientos_planta").insert(lote_insercion[i:i+300]).execute()
                                    st.success(f"🎉 Guardados {len(lote_insercion)} registros. Omitidos: {registros_omitidos}")
                                else:
                                    st.warning(f"No hay registros nuevos. Se omitieron {registros_omitidos} ya existentes.")
                except Exception as e:
                    st.error(f"Error procesando: {e}")

    # --- MÓDULO 2: HEADCOUNT ---
    elif opcion_carga == "👥 Headcount (Altas/Bajas)":
        st.markdown("#### 👥 Sincronización del Headcount Maestro")
        st.write("Sube el reporte de RH. El sistema actualizará datos y dará de baja por descarte a quienes ya no figuren.")

        archivo_hc = st.file_uploader("Subir reporte semanal de Headcount", type=["xlsx", "xls"], key="up_hc")

        if archivo_hc:
            with st.spinner("Procesando padrón..."):
                try:
                    df_hc = pd.read_excel(archivo_hc, sheet_name='HC_Snapshot')
                    col_id = 'Pers.No.'
                    df_hc[col_id] = df_hc[col_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    df_hc = df_hc[(df_hc[col_id] != 'nan') & (df_hc[col_id] != '') & (df_hc[col_id].notna())]
                    
                    st.success(f"✅ Se leyeron {len(df_hc)} empleados vigentes.")

                    if st.button("🔄 Procesar Altas y Bajas Automáticas", type="primary"):
                        with st.spinner("Impactando base de datos..."):
                            try:
                                resp_db = supabase.table("empleados_planta").select("num_empleado, estatus").execute()
                                empleados_db = {str(x['num_empleado']): x['estatus'] for x in resp_db.data}
                            except:
                                empleados_db = {}
                            
                            ids_excel = set(df_hc[col_id].tolist())
                            ids_db = set(empleados_db.keys())
                            
                            bajas_detectadas = ids_db - ids_excel
                            bajas_a_procesar = [emp for emp in bajas_detectadas if empleados_db[emp] != 'Inactive']
                            
                            lote_upsert = []
                            for _, row in df_hc.iterrows():
                                emp_id = row[col_id]
                                fecha_raw = row.get('Join Date')
                                try: fecha_ingreso = pd.to_datetime(fecha_raw).strftime('%Y-%m-%d')
                                except: fecha_ingreso = None
                                    
                                datos_json = {}
                                for key, value in row.fillna("").to_dict().items():
                                    if isinstance(value, pd.Timestamp) or type(value).__name__ in ['Timestamp', 'date', 'datetime']:
                                        datos_json[key] = str(value)
                                    else:
                                        datos_json[key] = value
                                
                                lote_upsert.append({
                                    "num_empleado": emp_id, "nombre_completo": str(row.get('Personnel Name', 'N/D')).strip(),
                                    "estatus": str(row.get('Employment Status', 'Active')).strip(), "fecha_ingreso": fecha_ingreso,
                                    "puesto": str(row.get('Job Title', 'N/D')).strip(), "departamento": str(row.get('Depto Eng', row.get('Cost Center', 'N/D'))).strip(),
                                    "area": str(row.get('Area', 'N/D')).strip(), "supervisor": str(row.get('Direct_Supervisor', row.get('Manager', 'N/D'))).strip(),
                                    "clase_categoria": str(row.get('ClassCateg', 'N/D')).strip(), "datos_completos": datos_json,
                                    "ultima_actualizacion": datetime.now().isoformat()
                                })
                            
                            if bajas_a_procesar:
                                for emp in bajas_a_procesar:
                                    supabase.table("empleados_planta").update({"estatus": "Inactive", "ultima_actualizacion": datetime.now().isoformat()}).eq("num_empleado", emp).execute()
                                    
                            if lote_upsert:
                                for i in range(0, len(lote_upsert), 300):
                                    supabase.table("empleados_planta").upsert(lote_upsert[i:i+300]).execute()
                                    
                            st.success(f"✅ ¡Actualizado! Altas/Cambios: {len(lote_upsert)} | Bajas: {len(bajas_a_procesar)}")
                except Exception as e:
                    st.error(f"Error procesando Headcount: {e}")

    # --- MÓDULO 3: HISTÓRICO ---
    elif opcion_carga == "📥 Carga Histórica (Masiva)":
        st.markdown("#### 📥 Ingesta Histórica de Múltiples Archivos")
        st.write("Sube todos tus Excel/CSV antiguos a la vez.")

        archivos_hist = st.file_uploader("Seleccionar históricos", type=["csv", "xlsx"], accept_multiple_files=True, key="up_hist")

        if archivos_hist:
            if st.button("🚀 Procesar Todo el Histórico", type="primary"):
                with st.spinner("Descargando llaves para control de duplicados..."):
                    try:
                        resp_existentes = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, curso_evaluado").execute()
                        set_existentes = {f"{str(x.get('num_empleado')).strip()}|{str(x.get('fecha_entrenamiento'))[:10]}|{str(x.get('curso_evaluado')).strip()}" for x in resp_existentes.data}
                    except:
                        set_existentes = set()

                lote_global, omitidos_global, procesados, err_archivos = [], 0, 0, []
                palabras_filtro = ['nombre', 'puesto', 'empleado', 'fecha', 'exámen', 'examen', 'instructor', 'demostró dominio', 'explicó los temas', 'resolvió adecuadamente', 'manejó bien el tiempo', 'contenido del curso fue útil', 'podría mejorar', 'lee a continuación y califica']
                barra_progreso = st.progress(0)
                
                for idx, archivo in enumerate(archivos_hist):
                    try:
                        df_raw = pd.read_csv(archivo) if archivo.name.endswith('.csv') else pd.read_excel(archivo)
                        cols = [str(c).strip() for c in df_raw.columns]
                        df_raw.columns = cols
                        
                        col_examen = next((c for c in cols if 'exámen va a presentar' in c.lower() or 'examen va a presentar' in c.lower()), None)
                        col_num = next((c for c in cols if 'número de empleado' in c.lower() or 'numero de empleado' in c.lower()), None)
                        col_nom = next((c for c in cols if 'nombre' in c.lower()), 'Nombre Completo')
                        col_fecha = next((c for c in cols if 'hora de finalización' in c.lower() or 'fecha que se realiza' in c.lower()), None)
                        
                        if not col_examen or not col_num:
                            err_archivos.append(f"{archivo.name} (Faltan columnas)")
                            continue

                        df_raw[col_examen] = df_raw[col_examen].astype(str).str.replace(r'\xa0', ' ', regex=True).str.strip()
                        df_raw['num_emp_str'] = df_raw[col_num].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        mask_valida = (~df_raw[col_examen].isin(['nan', '', 'None', 'NaN']) & ~df_raw['num_emp_str'].isin(['nan', '', 'None', 'N/A', '0']) & df_raw[col_num].notna())
                        df_clean = df_raw[mask_valida]
                        cols_preguntas = [c for c in cols if str(c).strip().startswith('Puntos:')]

                        for _, row in df_clean.iterrows():
                            emp_id, curso_actual = str(row['num_emp_str']), str(row[col_examen]).strip()
                            
                            try: fecha_dt = pd.to_datetime(row.get(col_fecha, datetime.now()))
                            except: fecha_dt = datetime.now()
                            fecha_val_str = fecha_dt.strftime('%Y-%m-%d')

                            llave_unica = f"{emp_id}|{fecha_val_str}|{curso_actual}"
                            if llave_unica in set_existentes:
                                omitidos_global += 1
                                continue
                            
                            raw_nombre = row.get(col_nom)
                            nombre_emp = "Sin Nombre" if pd.isna(raw_nombre) else str(raw_nombre).strip()[:100]

                            detalle = {}
                            for cp in cols_preguntas:
                                col_respuesta_texto = cp.replace("Puntos: ", "", 1).strip()
                                if any(x in col_respuesta_texto.lower() for x in palabras_filtro): continue 
                                if col_respuesta_texto in df_raw.columns:
                                    respuesta = row.get(col_respuesta_texto)
                                    if pd.notna(respuesta) and str(respuesta).strip() != '':
                                        val_raw = row.get(cp, 0)
                                        try: puntos = 0.0 if pd.isna(float(val_raw)) else float(val_raw)
                                        except: puntos = 0.0
                                        detalle[cp] = puntos

                            total_reactivos = len(detalle)
                            calif_total = round((sum([1.0 for v in detalle.values() if float(v) > 0]) / total_reactivos) * 10.0, 2) if total_reactivos > 0 else 0.0

                            lote_global.append({
                                "num_empleado": emp_id, "nombre_empleado": nombre_emp, "curso_evaluado": curso_actual,
                                "fecha_entrenamiento": fecha_dt.isoformat(), "calificacion_total": calif_total,
                                "detalle_respuestas": detalle, "archivo_origen": archivo.name
                            })
                            set_existentes.add(llave_unica)
                            
                        procesados += 1
                    except Exception as e:
                        err_archivos.append(f"{archivo.name} (Error: {e})")
                    
                    barra_progreso.progress((idx + 1) / len(archivos_hist))

                if lote_global:
                    with st.spinner("Insertando lote masivo..."):
                        for i in range(0, len(lote_global), 300):
                            supabase.table("entrenamientos_planta").insert(lote_global[i:i+300]).execute()
                    st.success(f"🎉 Completado. Archivos: {procesados} | Guardados: {len(lote_global)} | Omitidos: {omitidos_global}")
                else:
                    st.info(f"Procesados {len(archivos_hist)}. No hay registros nuevos (Omitidos: {omitidos_global}).")
                if err_archivos:
                    st.error("⚠️ Archivos ignorados por errores:")
                    for err in err_archivos: st.write(f"- {err}")

# -----------------------------------------------------------------------------
# PESTAÑA 3: CONSULTA DE PERSONAL Y ACTUALIZACIÓN MANUAL
# -----------------------------------------------------------------------------
with tab_consulta:
    st.markdown("### 🔍 Expediente Individual y Actualización")
    st.write("Busca el historial de capacitación de cualquier empleado (Activo o Baja) y registra evaluaciones de forma manual.")

    # 1. Cargar padrón para el buscador
    try:
        resp_emp = supabase.table("empleados_planta").select("num_empleado, nombre_completo, estatus, puesto, departamento").execute()
        df_emp = pd.DataFrame(resp_emp.data)
    except Exception as e:
        df_emp = pd.DataFrame()
        st.error(f"Error cargando el padrón: {e}")

    if not df_emp.empty:
        # Formatear lista para el buscador interactivo
        df_emp['display'] = df_emp['num_empleado'] + " - " + df_emp['nombre_completo'] + " [" + df_emp['estatus'] + "]"
        lista_empleados = [""] + df_emp['display'].tolist()
        
        col_busqueda, _ = st.columns([2, 1])
        seleccion = col_busqueda.selectbox("Buscador de Empleados (Escribe ID o Nombre):", lista_empleados)

        if seleccion != "":
            emp_id = seleccion.split(" - ")[0]
            datos_empleado = df_emp[df_emp['num_empleado'] == emp_id].iloc[0]
            
            st.divider()
            
            # --- TARJETA DE IDENTIFICACIÓN (5 Columnas para incluir Fecha de Ingreso) ---
            c_id1, c_id2, c_id3, c_id4, c_id5 = st.columns(5)
            c_id1.metric("Número de Empleado", emp_id)
            c_id2.metric("Nombre", datos_empleado['nombre_completo'])
            
            # Formatear fecha de ingreso para visualización limpia
            f_ingreso = datos_empleado.get('fecha_ingreso', 'N/D')
            if pd.notna(f_ingreso) and str(f_ingreso).strip() != '':
                try:
                    f_ingreso_fmt = pd.to_datetime(f_ingreso).strftime('%d-%b-%Y')
                except:
                    f_ingreso_fmt = str(f_ingreso)[:10]
            else:
                f_ingreso_fmt = "No registrada"
                
            c_id3.metric("Fecha de Ingreso", f_ingreso_fmt)
            c_id4.metric("Departamento", datos_empleado.get('departamento', 'N/D'))
            
            # Etiqueta visual de estatus
            color_estatus = "🟢" if datos_empleado['estatus'] == 'Active' else "🔴"
            c_id5.metric("Estatus", f"{color_estatus} {datos_empleado['estatus']}")

            st.write("")

            # 2. Cargar historial del empleado seleccionado
            try:
                resp_historial = supabase.table("entrenamientos_planta").select("*").eq("num_empleado", emp_id).order("fecha_entrenamiento", desc=True).execute()
                df_hist = pd.DataFrame(resp_historial.data)
            except:
                df_hist = pd.DataFrame()

            # --- PANEL DIVIDIDO: HISTORIAL VS REGISTRO MANUAL ---
            col_historial, col_registro = st.columns([2, 1], gap="large")

            with col_historial:
                st.markdown("#### 📜 Matriz de Entrenamientos")
                
                if not df_hist.empty:
                    df_hist['fecha_entrenamiento'] = pd.to_datetime(df_hist['fecha_entrenamiento'])
                    
                    # Identificar la última evaluación por cada curso para el cálculo de vigencia
                    df_latest = df_hist.sort_values('fecha_entrenamiento', ascending=False).drop_duplicates(subset=['curso_evaluado'], keep='first').copy()
                    
                    # Funciones de extracción desde el JSONB
                    def calcular_proximo(row):
                        detalle = row.get('detalle_respuestas', {})
                        meses = 12 # Anual por defecto
                        if isinstance(detalle, dict) and 'periodicidad_meses' in detalle:
                            meses = int(detalle['periodicidad_meses'])
                        
                        # Si es periodicidad 0 (Única vez), devolvemos un string en lugar de fecha
                        if meses == 0:
                            return "N/A (Permanente)"
                        return (row['fecha_entrenamiento'] + relativedelta(months=meses)).date()
                    
                    def obtener_periodicidad(row):
                        detalle = row.get('detalle_respuestas', {})
                        if isinstance(detalle, dict) and 'periodicidad_meses' in detalle:
                            meses = int(detalle['periodicidad_meses'])
                            # AJUSTE SOLICITADO: Imprimir "Permanente" si meses es 0
                            return "Permanente" if meses == 0 else f"{meses} meses"
                        return "12 meses"
                        
                    def obtener_certificado(row):
                        detalle = row.get('detalle_respuestas', {})
                        if isinstance(detalle, dict) and 'num_certificado' in detalle:
                            return str(detalle['num_certificado'])
                        return "N/A"

                    df_latest['Próximo Vencimiento'] = df_latest.apply(calcular_proximo, axis=1)
                    df_latest['Periodicidad'] = df_latest.apply(obtener_periodicidad, axis=1)
                    df_latest['Certificado'] = df_latest.apply(obtener_certificado, axis=1)
                    df_latest['Fecha de Curso'] = df_latest['fecha_entrenamiento'].dt.date
                    
                    # Formato para visualización
                    df_mostrar = df_latest[['curso_evaluado', 'Fecha de Curso', 'Periodicidad', 'Próximo Vencimiento', 'calificacion_total', 'Certificado', 'archivo_origen']].copy()
                    df_mostrar.columns = ['Curso', 'Última Fecha', 'Periodicidad', 'Próximo Vencimiento', 'Calificación', 'Certificado', 'Origen']
                    
                    # Semáforo de vigencias (Vencido = Rojo, Vigente = Verde)
                    hoy = datetime.now().date()
                    def estilo_vigencia(val):
                        if isinstance(val, date):
                            if val < hoy:
                                return 'background-color: #ffcccc; color: #cc0000; font-weight: bold;'
                            elif val <= (hoy + timedelta(days=30)):
                                return 'background-color: #fff2cc; color: #b38600; font-weight: bold;'
                            else:
                                return 'background-color: #e2f0d9; color: #385723;'
                        elif val == "N/A (Permanente)":
                            # Verde para los permanentes
                            return 'background-color: #e2f0d9; color: #385723;'
                        return ''

                    st.dataframe(df_mostrar.style.map(estilo_vigencia, subset=['Próximo Vencimiento']), use_container_width=True, hide_index=True)
                else:
                    st.info("Este colaborador no tiene entrenamientos registrados en el sistema.")

            with col_registro:
                st.markdown("#### ➕ Registrar Certificación Manual")
                with st.form("form_nuevo_curso", clear_on_submit=True): # Limpia el formulario al guardar
                    try:
                        resp_cursos = supabase.table("entrenamientos_planta").select("curso_evaluado").execute()
                        cursos_unicos = sorted(list(set([x['curso_evaluado'] for x in resp_cursos.data])))
                    except:
                        cursos_unicos = []
                        
                    n_curso = st.selectbox("Selecciona o escribe el curso:", cursos_unicos + ["-- OTRO (Escribir abajo) --"])
                    n_curso_manual = st.text_input("Nombre del Curso (Si elegiste 'OTRO'):")
                    
                    n_fecha = st.date_input("Fecha de Certificación:", datetime.now().date())
                    n_calificacion = st.number_input("Calificación Obtenida (0-10):", min_value=0.0, max_value=10.0, value=10.0, step=0.1)
                    
                    n_certificado = st.text_input("Número de Certificado (Opcional):")
                    
                    n_periodicidad = st.selectbox("Periodicidad de Reentrenamiento:", [
                        (12, "Anual (12 meses)"), 
                        (6, "Semestral (6 meses)"), 
                        (24, "Bianual (24 meses)"),
                        (0, "Única vez (Sin caducidad)")
                    ], format_func=lambda x: x[1])

                    submit_manual = st.form_submit_button("💾 Guardar Registro", type="primary", use_container_width=True)

                # EVALUAMOS EL BOTÓN FUERA DEL st.form()
                if submit_manual:
                    curso_final = n_curso_manual.strip() if n_curso == "-- OTRO (Escribir abajo) --" else n_curso.strip()
                    
                    if not curso_final:
                        st.error("Debes especificar el nombre del curso.")
                    else:
                        json_manual = {
                            "tipo_ingreso": "Registro Manual HR",
                            "periodicidad_meses": n_periodicidad[0]
                        }
                        
                        if n_certificado.strip():
                            json_manual["num_certificado"] = n_certificado.strip()
                        
                        payload = {
                            "num_empleado": emp_id,
                            "nombre_empleado": datos_empleado['nombre_completo'],
                            "curso_evaluado": curso_final,
                            "fecha_entrenamiento": n_fecha.isoformat() + "T12:00:00",
                            "calificacion_total": float(n_calificacion),
                            "detalle_respuestas": json_manual,
                            "archivo_origen": "REGISTRO MANUAL"
                        }
                        
                        with st.spinner("Guardando en la base de datos..."):
                            try:
                                # Insertamos
                                supabase.table("entrenamientos_planta").insert(payload).execute()
                                
                                # Borramos cualquier caché previo que pudiera estar leyendo datos viejos
                                st.cache_data.clear() 
                                
                                st.success("✅ Registro guardado correctamente. Actualizando pantalla...")
                                time.sleep(1.5) # Le damos tiempo real a Supabase para indexar
                                st.rerun() # Refrescamos toda la app
                            except Exception as e:
                                st.error(f"Error al guardar: {e}")

# -----------------------------------------------------------------------------
# PESTAÑA 4: EMISIÓN DE CERTIFICADOS EN PDF
# -----------------------------------------------------------------------------
with tab_certificados:
    st.markdown("### 🎓 Emisión de Certificados Oficiales")
    st.write("Busca a un empleado para visualizar sus cursos aprobados y generar el diploma en PDF.")

    # 1. Buscador de empleados
    try:
        resp_emp_cert = supabase.table("empleados_planta").select("num_empleado, nombre_completo, estatus").execute()
        df_emp_cert = pd.DataFrame(resp_emp_cert.data)
    except:
        df_emp_cert = pd.DataFrame()

    if not df_emp_cert.empty:
        df_emp_cert['display'] = df_emp_cert['num_empleado'] + " - " + df_emp_cert['nombre_completo']
        lista_empleados_cert = [""] + df_emp_cert['display'].tolist()
        
        c_busqueda_cert, _ = st.columns([2, 1])
        seleccion_cert = c_busqueda_cert.selectbox("Selecciona un empleado para emitir certificado:", lista_empleados_cert, key="sel_cert")

        if seleccion_cert != "":
            emp_id_cert = seleccion_cert.split(" - ")[0]
            nombre_empleado_cert = seleccion_cert.split(" - ")[1]
            
            # 2. Obtener SOLO cursos aprobados (>= 8.0) del empleado
            try:
                resp_aprobados = supabase.table("entrenamientos_planta") \
                    .select("curso_evaluado, fecha_entrenamiento, calificacion_total") \
                    .eq("num_empleado", emp_id_cert) \
                    .gte("calificacion_total", 8.0) \
                    .order("fecha_entrenamiento", desc=True) \
                    .execute()
                df_aprobados = pd.DataFrame(resp_aprobados.data)
            except:
                df_aprobados = pd.DataFrame()
                
            st.divider()

            if not df_aprobados.empty:
                df_aprobados['fecha_dt'] = pd.to_datetime(df_aprobados['fecha_entrenamiento'])
                
                # Crear opciones descriptivas para el selector
                opciones_cursos = []
                for _, row in df_aprobados.iterrows():
                    f_str = row['fecha_dt'].strftime('%d-%b-%Y')
                    opciones_cursos.append(f"{row['curso_evaluado']} (Aprobado: {row['calificacion_total']} - Fecha: {f_str})")
                
                c_curso_cert, _ = st.columns([2, 1])
                curso_elegido = c_curso_cert.selectbox("Selecciona el curso a certificar:", opciones_cursos)
                
                # Extraer datos exactos del curso seleccionado
                idx_curso = opciones_cursos.index(curso_elegido)
                datos_curso = df_aprobados.iloc[idx_curso]
                
                fecha_curso = datos_curso['fecha_dt']
                meses_espanol = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
                
                dia_cert = str(fecha_curso.day).zfill(2)
                mes_cert = meses_espanol[fecha_curso.month - 1]
                anio_cert = str(fecha_curso.year)
                nombre_curso_cert = datos_curso['curso_evaluado']
                
                if st.button("🖼️ Generar Vista Previa del Certificado", type="primary"):
                    
                    # Cargar el HTML original, pero inyectando los datos de la base de datos de Python
                    html_certificado = f"""
                    <!DOCTYPE html>
                    <html lang="es">
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <script src="https://cdn.tailwindcss.com"></script>
                        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
                        <link href="https://fonts.googleapis.com/css2?family=Alex+Brush&family=Cinzel:wght@500;700&family=Dancing+Script:wght@600&family=Great+Vibes&family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=Parisienne&family=Playfair+Display:ital,wght@0,600;0,700;1,400&display=swap" rel="stylesheet">
                        <style>
                            :root {{ --bcs-red: #9e0b0f; --bcs-dark-red: #610407; --bcs-gold: #d4af37; }}
                            body {{ font-family: 'Montserrat', sans-serif; background-color: #0f172a; color: #f8fafc; overflow-x: hidden; margin: 0; padding: 0; }}
                            .certificate-paper {{ width: 1000px; height: 707px; background-color: #ffffff; color: #1e293b; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.4); overflow: hidden; box-sizing: border-box; }}
                            [contenteditable="true"] {{ outline: none; transition: background-color 0.2s; border-radius: 4px; padding: 2px 6px; }}
                            [contenteditable="true"]:hover {{ background-color: rgba(220, 38, 38, 0.05); box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.2); }}
                            .font-certificate-title {{ font-family: 'Cinzel', serif; letter-spacing: 0.15em; }}
                            .font-name-script {{ font-family: 'Great Vibes', cursive; }}
                            ::-webkit-scrollbar {{ width: 6px; }} ::-webkit-scrollbar-track {{ background: #1e293b; }} ::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 3px; }}
                            @media print {{
                                @page {{ size: A4 landscape; margin: 0; }}
                                body {{ background: white !important; padding: 0 !important; margin: 0 !important; }}
                                .no-print {{ display: none !important; }}
                                .certificate-paper {{ width: 100vw !important; height: 100vh !important; box-shadow: none !important; transform: scale(1) !important; }}
                            }}
                        </style>
                    </head>
                    <body class="flex flex-col lg:flex-row h-screen">
                        <!-- Sidebar -->
                        <aside class="no-print w-96 bg-slate-900 border-r border-slate-800 flex flex-col h-full z-20">
                            <div class="p-4 border-b border-slate-800 bg-slate-950 flex justify-between items-center">
                                <h1 class="font-bold text-white"><i class="fa-solid fa-award text-red-600 mr-2"></i>Editor BCS</h1>
                            </div>
                            <div class="p-4 space-y-4 overflow-y-auto flex-1 text-sm">
                                <div>
                                    <label class="block text-slate-300 mb-1 text-xs">Nombre</label>
                                    <input type="text" id="inputName" value="{nombre_empleado_cert}" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white">
                                </div>
                                <div class="grid grid-cols-2 gap-2">
                                    <div><label class="block text-slate-300 mb-1 text-xs">Día</label><input type="text" id="inputDay" value="{dia_cert}" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white text-center"></div>
                                    <div><label class="block text-slate-300 mb-1 text-xs">Mes</label><input type="text" id="inputMonth" value="{mes_cert}" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white text-center"></div>
                                </div>
                                <div><label class="block text-slate-300 mb-1 text-xs">Año</label><input type="text" id="inputYear" value="{anio_cert}" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white text-center"></div>
                                <div><label class="block text-slate-300 mb-1 text-xs">Curso</label><input type="text" id="inputCourse" value="{nombre_curso_cert}" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white"></div>
                                <div><label class="block text-slate-300 mb-1 text-xs">Entrenador</label><input type="text" id="inputTrainer" value="NOMBRE DEL CAPACITADOR" oninput="syncFromInput()" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-white"></div>
                            </div>
                            <div class="p-4 bg-slate-950">
                                <button onclick="window.print()" class="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded-lg"><i class="fa-solid fa-print mr-2"></i>Imprimir / PDF</button>
                            </div>
                        </aside>

                        <!-- Canvas -->
                        <main class="flex-1 bg-slate-950 flex flex-col items-center justify-center p-8 overflow-hidden relative">
                            <div class="no-print absolute top-4 right-4 space-x-2 z-50 text-white">
                                <button onclick="zoom(0.9)" class="bg-slate-800 px-3 py-1 rounded">-</button>
                                <button onclick="zoom(1.1)" class="bg-slate-800 px-3 py-1 rounded">+</button>
                            </div>
                            
                            <div id="certificatePaper" class="certificate-paper rounded-lg relative flex flex-col justify-between p-12 transition-transform origin-center">
                                <svg class="absolute inset-0 w-full h-full pointer-events-none z-0" viewBox="0 0 1000 707" fill="none">
                                    <path d="M 620 0 C 720 120 850 180 1000 180 L 1000 0 Z" fill="#610407"/>
                                    <path d="M 680 0 C 780 100 880 140 1000 140 L 1000 0 Z" fill="#9e0b0f"/>
                                    <path d="M 650 0 C 760 110 880 155 1000 155" stroke="#d4af37" stroke-width="4" fill="none"/>
                                    <path d="M 0 450 C 150 450 300 580 420 707 L 0 707 Z" fill="#610407"/>
                                    <path d="M 0 490 C 120 490 250 600 360 707 L 0 707 Z" fill="#9e0b0f"/>
                                    <path d="M 0 470 C 135 470 275 590 390 707" stroke="#d4af37" stroke-width="4" fill="none"/>
                                    <path d="M -50 0 C 200 100 200 607 -50 707" stroke="#e0ca85" stroke-width="35" opacity="0.35" fill="none"/>
                                </svg>
                                
                                <div class="relative z-10 h-full flex flex-col justify-between">
                                    <div class="flex justify-between items-start pt-2 px-4">
                                        <img src="https://raw.githubusercontent.com/aldoaoa/trainingsuite/refs/heads/main/logo.png" class="h-20 object-contain">
                                    </div>
                                    <div class="text-center px-12 -mt-4">
                                        <h1 class="font-certificate-title text-5xl font-bold tracking-[0.25em] mb-3">CERTIFICADO</h1>
                                        <p class="text-xs font-semibold tracking-[0.3em] mb-4">DE RECONOCIMIENTO A:</p>
                                        <div class="my-3"><span id="certName" contenteditable="true" class="font-name-script text-[54px]">{nombre_empleado_cert}</span></div>
                                        <div class="w-3/4 mx-auto border-b border-slate-300 my-3"></div>
                                        <div class="text-sm max-w-2xl mx-auto my-4 space-y-2">
                                            <p>Por completar el curso llamado “<span id="certCourse" contenteditable="true" class="font-bold">{nombre_curso_cert}</span>” en <span contenteditable="true" class="font-semibold">BCS-AIS Querétaro</span>.</p>
                                            <p class="text-xs pt-2">Se expide el <span id="certDay" contenteditable="true" class="font-medium">{dia_cert}</span> de <span id="certMonth" contenteditable="true" class="font-medium">{mes_cert}</span> del año <span id="certYear" contenteditable="true" class="font-medium">{anio_cert}</span>.</p>
                                        </div>
                                    </div>
                                    <div class="flex justify-between items-end pb-4 px-12">
                                        <div class="w-1/4"></div>
                                        <div class="text-center w-2/5">
                                            <div class="w-full border-b border-slate-400 mb-2"></div>
                                            <div id="certTrainer" contenteditable="true" class="text-sm font-bold tracking-wider">NOMBRE DEL CAPACITADOR</div>
                                            <div contenteditable="true" class="text-[11px] font-semibold text-slate-600 mt-0.5">CAPACITADOR</div>
                                        </div>
                                        <div class="w-1/4 flex justify-end">
                                            <div class="w-24 h-24 rounded-full bg-gradient-to-tr from-amber-600 to-amber-200 p-1 flex items-center justify-center"><div class="w-full h-full rounded-full border-2 border-dashed border-red-800 bg-yellow-100"></div></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </main>
                        <script>
                            let z = 0.8;
                            function applyZ() {{ document.getElementById('certificatePaper').style.transform = `scale(${{z}})`; }}
                            function zoom(f) {{ z *= f; applyZ(); }}
                            function syncFromInput() {{
                                document.getElementById('certName').innerText = document.getElementById('inputName').value;
                                document.getElementById('certCourse').innerText = document.getElementById('inputCourse').value;
                                document.getElementById('certDay').innerText = document.getElementById('inputDay').value;
                                document.getElementById('certMonth').innerText = document.getElementById('inputMonth').value;
                                document.getElementById('certYear').innerText = document.getElementById('inputYear').value;
                                document.getElementById('certTrainer').innerText = document.getElementById('inputTrainer').value;
                            }}
                            window.onload = applyZ;
                        </script>
                    </body>
                    </html>
                    """ 
                    
                    # Renderizar el HTML en Streamlit con altura suficiente
                    components.html(html_certificado, height=800, scrolling=True)

            else:
                st.warning("Este empleado no tiene cursos registrados con calificación aprobatoria (≥ 8.0).")
                
# -----------------------------------------------------------------------------
# PESTAÑA 3: AUDITORÍA DE BRECHAS
# -----------------------------------------------------------------------------
with tab_auditoria:
    st.info("El escaneo cronológico ahora requerirá agrupar por `num_empleado` y por `curso_evaluado` para buscar brechas de tiempo (gaps) independientemente en cada materia.")
