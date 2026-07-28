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

# --- CONSOLIDACIÓN DE PESTAÑAS ---
tab_dash, tab_gestion_datos, tab_consulta, tab_auditoria = st.tabs([
    "📊 Dashboard Interactivo", 
    "⚙️ Gestión de Datos", 
    "🔍 Consulta y Actualización", # <--- NUEVA PESTAÑA
    "🕵️ Auditoría de Brechas"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: DASHBOARD INTERACTIVO
# -----------------------------------------------------------------------------
with tab_dash:
    st.markdown("#### 📊 Dashboard de Certificación y Cumplimiento")
    st.write("Las métricas presentadas aquí están cruzadas con el Headcount actual. **Excluyen automáticamente** las evaluaciones del personal dado de baja.")
    
    with st.spinner("Sincronizando padrón y evaluaciones..."):
        try:
            resp_emp = supabase.table("empleados_planta").select("num_empleado, nombre_completo, departamento, area").eq("estatus", "Active").execute()
            df_activos = pd.DataFrame(resp_emp.data)
            
            resp_train = supabase.table("entrenamientos_planta").select("num_empleado, fecha_entrenamiento, calificacion_total, curso_evaluado").execute()
            df_train = pd.DataFrame(resp_train.data)
        except Exception as e:
            df_activos = pd.DataFrame()
            df_train = pd.DataFrame()
            st.error(f"Error al conectar con la base de datos: {e}")

    if not df_activos.empty and not df_train.empty:
        df_dash = pd.merge(df_train, df_activos, on="num_empleado", how="inner")
        
        if not df_dash.empty:
            df_dash['fecha_entrenamiento'] = pd.to_datetime(df_dash['fecha_entrenamiento'])
            
            c_filtro1, c_filtro2 = st.columns(2)
            cursos_db = sorted(df_dash['curso_evaluado'].unique().tolist())
            filtro_curso = c_filtro1.selectbox("Filtro por Curso:", ["Todos"] + cursos_db)
            
            deptos_db = sorted(df_dash['departamento'].dropna().unique().tolist())
            filtro_depto = c_filtro2.selectbox("Filtro por Departamento:", ["Todos"] + deptos_db)
            
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
            
            # --- TARJETA DE IDENTIFICACIÓN ---
            c_id1, c_id2, c_id3, c_id4 = st.columns(4)
            c_id1.metric("Número de Empleado", emp_id)
            c_id2.metric("Nombre", datos_empleado['nombre_completo'])
            c_id3.metric("Departamento", datos_empleado['departamento'])
            
            # Etiqueta visual de estatus
            color_estatus = "🟢" if datos_empleado['estatus'] == 'Active' else "🔴"
            c_id4.metric("Estatus", f"{color_estatus} {datos_empleado['estatus']}")

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
# PESTAÑA 3: AUDITORÍA DE BRECHAS
# -----------------------------------------------------------------------------
with tab_auditoria:
    st.info("El escaneo cronológico ahora requerirá agrupar por `num_empleado` y por `curso_evaluado` para buscar brechas de tiempo (gaps) independientemente en cada materia.")
