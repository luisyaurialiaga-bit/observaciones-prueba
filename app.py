import streamlit as st
import sqlite3
import os
import re
import pandas as pd
import plotly.express as px

# Configuración de la página
st.set_page_config(
    page_title="Sistema ITS SENACE",
    page_icon="🛡️",
    layout="wide"
)

DB_SQL_PATH = "datos_its.db"
EXCEL_PATH = "observaciones_clasificadas_FINAL_v33.xlsx"

def obtener_conexion_sql():
    return sqlite3.connect(DB_SQL_PATH)

def tabla_existe(nombre_tabla):
    if not os.path.exists(DB_SQL_PATH):
        return False
    try:
        conn = obtener_conexion_sql()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nombre_tabla,))
        existe = cursor.fetchone() is not None
        conn.close()
        return existe
    except Exception:
        return False

def obtener_columna_observacion(df_o_conn):
    """Detecta la columna de la observación en un DataFrame o en la tabla SQLite."""
    if isinstance(df_o_conn, pd.DataFrame):
        columnas = df_o_conn.columns.tolist()
    else:
        try:
            cursor = df_o_conn.cursor()
            cursor.execute("PRAGMA table_info(observaciones)")
            columnas = [info[1] for info in cursor.fetchall()]
        except Exception:
            return "Observacion"
            
    for col in ["Observación", "OBSERVACION", "Observacion", "observacion"]:
        if col in columnas:
            return col
    return columnas[0] if columnas else "Observacion"

def normalizar_nombre_evaluador(nombre):
    """Limpia y estandariza los nombres de los evaluadores/coordinadores."""
    if pd.isna(nombre):
        return "Sin Asignar"
    
    nombre_str = str(nombre).strip()
    
    if not nombre_str or nombre_str.lower() in ["nan", "none", "null", "-", "", "sin información", "sin informacion"]:
        return "Sin Asignar"
    
    nombre_limpio = re.sub(r'\s+', ' ', nombre_str).title()
    return nombre_limpio

def construir_base_rapida_y_normalizada():
    """Lee el Excel, aplica la normalización de datos y guarda en SQLite."""
    if not os.path.exists(EXCEL_PATH):
        st.error(f"No se encontró el archivo Excel: {EXCEL_PATH}.")
        return False
    
    df = pd.read_excel(EXCEL_PATH)
    col_obs = obtener_columna_observacion(df)
    
    # 1. Normalización de observaciones
    df[col_obs] = df[col_obs].astype(str).str.strip()
    df = df[
        df[col_obs].notna() & 
        (df[col_obs] != "") & 
        (df[col_obs].str.lower() != "nan") &
        (df[col_obs].str.lower() != "none")
    ].copy()
    
    # 2. Normalización de evaluadores
    if 'Coordinador' in df.columns:
        df['Coordinador'] = df['Coordinador'].apply(normalizar_nombre_evaluador)
    elif 'Especialista' in df.columns:
        df['Coordinador'] = df['Especialista'].apply(normalizar_nombre_evaluador)
    
    # 3. Limpieza de otras columnas
    for col in ['Expediente', 'Especialidad Final', 'Empresa', 'Titulo Proyecto']:
        if col in df.columns:
            df[col] = df[col].fillna('Sin información').astype(str).str.strip()
            df[col] = df[col].replace({'nan': 'Sin información', 'None': 'Sin información', '': 'Sin información'})

    conn = obtener_conexion_sql()
    df.to_sql("observaciones", conn, if_exists="replace", index=False)
    conn.close()
    return True

# 1. VERIFICACIÓN Y CREACIÓN DE BASE DE DATOS
if not tabla_existe("observaciones"):
    with st.spinner("⚡ Normalizando datos y regenerando base de datos..."):
        if construir_base_rapida_y_normalizada():
            st.rerun()

# Encabezado Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica Normalizada")

# Navegación por pestañas
tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda de Observaciones", "📋 Consulta General SQL", "📊 Dashboard Completo & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA DE OBSERVACIONES
# ---------------------------------------------------------
with tab1:
    st.header("Búsqueda Avanzada de Observaciones")
    query = st.text_input("Ingrese la consulta o temática a buscar:", placeholder="Ej: fauna, calidad de aire, plan de participacion ciudadana...")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)
    
    lista_evaluadores = ["Todos"]
    if tabla_existe("observaciones"):
        conn = obtener_conexion_sql()
        try:
            evaluadores_df = pd.read_sql_query('SELECT DISTINCT "Coordinador" FROM observaciones WHERE "Coordinador" IS NOT NULL AND "Coordinador" NOT IN ("", "Sin Asignar") ORDER BY "Coordinador"', conn)
            lista_evaluadores += evaluadores_df['Coordinador'].tolist()
        except Exception:
            pass
        finally:
            conn.close()

    with col2:
        evaluador_filtro = st.selectbox("Filtrar por Evaluador/Especialista:", lista_evaluadores)

    if st.button("Buscar Observaciones", type="primary"):
        if query.strip():
            conn = obtener_conexion_sql()
            col_obs = obtener_columna_observacion(conn)
            
            query_sql = f'SELECT * FROM observaciones WHERE "{col_obs}" LIKE ?'
            params = [f"%{query.strip()}%"]
            
            if evaluador_filtro != "Todos":
                query_sql += ' AND "Coordinador" = ?'
                params.append(evaluador_filtro)
            
            query_sql += f" LIMIT {top_k}"
            
            df_res = pd.read_sql_query(query_sql, conn, params=params)
            conn.close()
            
            if not df_res.empty:
                st.success(f"Se encontraron {len(df_res)} observaciones relacionadas:")
                for idx, row in df_res.iterrows():
                    num_res = idx + 1
                    exp = row.get('Expediente', 'Sin información')
                    coord = row.get('Coordinador', 'Sin Asignar')
                    proyecto = row.get('Titulo Proyecto', row.get('Proyecto', 'Sin información'))
                    empresa = row.get('Empresa', 'Sin información')
                    obs_texto = row.get(col_obs, 'Sin detalle')
                    
                    with st.expander(f"📌 Resultado #{num_res} | Expediente: {exp} | Evaluador: {coord}"):
                        st.markdown(f"**Proyecto:** {proyecto}")
                        st.markdown(f"**Empresa:** {empresa}")
                        st.markdown("---")
                        st.markdown(f"**Observación:**\n\n{obs_texto}")
            else:
                st.info("No se encontraron observaciones que coincidan con la búsqueda.")
        else:
            st.warning("Por favor ingrese un texto de consulta.")

# ---------------------------------------------------------
# PESTAÑA 2: CONSULTA GENERAL SQL
# ---------------------------------------------------------
with tab2:
    st.header("Explorador de la Base de Datos")
    if tabla_existe("observaciones"):
        conn = obtener_conexion_sql()
        df_preview = pd.read_sql_query("SELECT * FROM observaciones LIMIT 100", conn)
        conn.close()
        st.write("Mostrando los primeros 100 registros normalizados:")
        st.dataframe(df_preview, use_container_width=True)
    else:
        st.info("La tabla 'observaciones' aún no está construida en SQLite.")

# ---------------------------------------------------------
# PESTAÑA 3: DASHBOARD COMPLETO & MÉTRICAS
# ---------------------------------------------------------
with tab3:
    st.header("📊 Dashboard General de Estadísticas y Control")
    
    if tabla_existe("observaciones"):
        conn = obtener_conexion_sql()
        df_all = pd.read_sql_query("SELECT * FROM observaciones", conn)
        conn.close()
        
        # 1. TARJETAS DE INDICADORES CLAVE (KPIs)
        col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
        
        total_obs = len(df_all)
        total_expedientes = df_all['Expediente'].nunique() if 'Expediente' in df_all.columns else 0
        total_evaluadores = df_all[df_all['Coordinador'] != 'Sin Asignar']['Coordinador'].nunique() if 'Coordinador' in df_all.columns else 0
        total_empresas = df_all['Empresa'].nunique() if 'Empresa' in df_all.columns else 0
        
        col_kpi1.metric("Total Observaciones", f"{total_obs:,}")
        col_kpi2.metric("Expedientes Evaluados", f"{total_expedientes:,}")
        col_kpi3.metric("Evaluadores Activos", f"{total_evaluadores}")
        col_kpi4.metric("Empresas / Titulares", f"{total_empresas:,}")
        
        st.markdown("---")
        
        # 2. GRÁFICOS INTERACTIVOS (FILA 1)
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("👥 Carga de Trabajo por Evaluador")
            if 'Coordinador' in df_all.columns:
                df_eval = df_all[df_all['Coordinador'] != 'Sin Asignar']['Coordinador'].value_counts().reset_index()
                df_eval.columns = ['Evaluador', 'Cantidad']
                
                fig_eval = px.bar(
                    df_eval.head(10), 
                    x='Cantidad', 
                    y='Evaluador', 
                    orientation='h',
                    color='Cantidad',
                    color_continuous_scale='Blues',
                    text='Cantidad'
                )
                fig_eval.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False)
                st.plotly_chart(fig_eval, use_container_width=True)
                
        with col_chart2:
            st.subheader("🏷️ Distribución por Especialidad / Tema")
            col_tema = 'Especialidad Final' if 'Especialidad Final' in df_all.columns else None
            if col_tema:
                df_tema = df_all[col_tema].value_counts().reset_index()
                df_tema.columns = ['Especialidad', 'Cantidad']
                
                fig_tema = px.pie(
                    df_tema.head(8), 
                    names='Especialidad', 
                    values='Cantidad',
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                st.plotly_chart(fig_tema, use_container_width=True)

        # 3. GRÁFICOS INTERACTIVOS (FILA 2)
        col_chart3, col_chart4 = st.columns(2)
        
        with col_chart3:
            st.subheader("🏢 Top 10 Empresas con más Observaciones")
            if 'Empresa' in df_all.columns:
                df_emp = df_all[df_all['Empresa'] != 'Sin información']['Empresa'].value_counts().reset_index()
                df_emp.columns = ['Empresa', 'Cantidad']
                
                fig_emp = px.bar(
                    df_emp.head(10), 
                    x='Empresa', 
                    y='Cantidad',
                    color='Cantidad',
                    color_continuous_scale='Reds'
                )
                fig_emp.update_xaxes(tickangle=45)
                st.plotly_chart(fig_emp, use_container_width=True)
                
        with col_chart4:
            st.subheader("📂 Top Expedientes con Mayor Número de Hallazgos")
            if 'Expediente' in df_all.columns:
                df_exp = df_all[df_all['Expediente'] != 'Sin información']['Expediente'].value_counts().reset_index()
                df_exp.columns = ['Expediente', 'Cantidad']
                
                fig_exp = px.bar(
                    df_exp.head(10), 
                    x='Expediente', 
                    y='Cantidad',
                    color='Cantidad',
                    color_continuous_scale='Greens'
                )
                fig_exp.update_xaxes(tickangle=45)
                st.plotly_chart(fig_exp, use_container_width=True)
    else:
        st.info("La tabla de observaciones aún no está disponible para generar el dashboard.")
