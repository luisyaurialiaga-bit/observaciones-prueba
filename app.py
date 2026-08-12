import streamlit as st
import pandas as pd
import plotly.express as px
import os

# Configuración de la página
st.set_page_config(
    page_title="Sistema ITS SENACE",
    page_icon="🛡️",
    layout="wide"
)

EXCEL_PATH = "observaciones_clasificadas_FINAL_v33.xlsx"

@st.cache_data(show_spinner="Cargando base de datos...")
def cargar_datos():
    if not os.path.exists(EXCEL_PATH):
        return None
    
    # Cargar optimizado
    df = pd.read_excel(EXCEL_PATH)
    
    # Identificar columna de observación
    col_obs = "Observacion"
    for col in ["Observación", "OBSERVACION", "Observacion", "observacion"]:
        if col in df.columns:
            col_obs = col
            break
            
    # Limpieza básica
    df[col_obs] = df[col_obs].astype(str).str.strip()
    df = df[df[col_obs].notna() & (df[col_obs] != "") & (df[col_obs].str.lower() != "nan")].copy()
    
    # Normalizar Coordinador / Especialista
    if 'Coordinador' not in df.columns:
        if 'Especialista' in df.columns:
            df['Coordinador'] = df['Especialista']
        else:
            df['Coordinador'] = 'Sin Asignar'
            
    df['Coordinador'] = df['Coordinador'].fillna('Sin Asignar').astype(str).str.strip().str.title()
    df['Coordinador'] = df['Coordinador'].replace({'Nan': 'Sin Asignar', 'None': 'Sin Asignar', '': 'Sin Asignar'})
    
    for col in ['Expediente', 'Especialidad Final', 'Empresa', 'Titulo Proyecto']:
        if col in df.columns:
            df[col] = df[col].fillna('Sin información').astype(str).str.strip()
            
    return df, col_obs

# Encabezado Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica Normalizada")

datos = cargar_datos()

if datos is None:
    st.error(f"⚠️ No se encontró el archivo '{EXCEL_PATH}' en la raíz del repositorio. Por favor asegúrate de subirlo a GitHub.")
    st.stop()

df_all, col_obs = datos

tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda de Observaciones", "📋 Consulta General", "📊 Dashboard Completo & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA DE OBSERVACIONES
# ---------------------------------------------------------
with tab1:
    st.header("Búsqueda Avanzada de Observaciones")
    query = st.text_input("Ingrese la consulta o temática a buscar:", placeholder="Ej: fauna, calidad de aire, plan de participacion ciudadana...")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)
    
    lista_evaluadores = ["Todos"] + sorted([e for e in df_all['Coordinador'].unique() if e not in ["Sin Asignar", ""]])
    
    with col2:
        evaluador_filtro = st.selectbox("Filtrar por Evaluador/Especialista:", lista_evaluadores)

    if st.button("Buscar Observaciones", type="primary"):
        if query.strip():
            # Filtrar por texto
            mask = df_all[col_obs].str.contains(query.strip(), case=False, na=False)
            
            # Filtrar por evaluador si aplica
            if evaluador_filtro != "Todos":
                mask = mask & (df_all['Coordinador'] == evaluador_filtro)
                
            df_res = df_all[mask].head(top_k)
            
            if not df_res.empty:
                st.success(f"Se encontraron {len(df_res)} observaciones relacionadas:")
                for idx, row in df_res.reset_index().iterrows():
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
# PESTAÑA 2: CONSULTA GENERAL
# ---------------------------------------------------------
with tab2:
    st.header("Explorador de la Base de Datos")
    st.write("Mostrando los primeros 100 registros:")
    st.dataframe(df_all.head(100), use_container_width=True)

# ---------------------------------------------------------
# PESTAÑA 3: DASHBOARD COMPLETO & MÉTRICAS
# ---------------------------------------------------------
with tab3:
    st.header("📊 Dashboard General de Estadísticas y Control")
    
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
