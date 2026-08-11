import streamlit as st
import sqlite3
import pandas as pd
import os
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings

st.set_page_config(
    page_title="Control de Calidad & Asistente ITS - SENACE",
    page_icon="🛡️",
    layout="wide"
)

DB_SQL_PATH = "datos_its.db"
CHROMA_PATH = "chroma_db"

@st.cache_resource
def load_vectorstore():
    if os.path.exists(CHROMA_PATH):
        embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    return None

st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica")

if not os.path.exists(DB_SQL_PATH):
    st.error("⚠️ No se encontró la base de datos 'datos_its.db'. Ejecuta primero 'regenerar_base.py'.")
    st.stop()

# Cargar listas para filtros desde SQLite
conn = sqlite3.connect(DB_SQL_PATH)
try:
    especialidades_list = pd.read_sql('SELECT DISTINCT "Especialidad Final" FROM observaciones WHERE "Especialidad Final" IS NOT NULL ORDER BY "Especialidad Final"', conn)['Especialidad Final'].tolist()
except Exception:
    especialidades_list = []

try:
    sql_eval = """
    SELECT DISTINCT "Coordinador" AS eval FROM observaciones WHERE "Coordinador" IS NOT NULL AND "Coordinador" != ''
    UNION
    SELECT DISTINCT "Lider Proyecto" FROM observaciones WHERE "Lider Proyecto" IS NOT NULL AND "Lider Proyecto" != ''
    ORDER BY eval
    """
    evaluadores_list = pd.read_sql(sql_eval, conn)['eval'].tolist()
except Exception:
    evaluadores_list = []
conn.close()

tabs = st.tabs(["🔍 Buscador Semántico (IA)", "✏️ Explorador de Tabla", "📊 Dashboard & Métricas"])

# TAB 1: BÚSQUEDA SEMÁNTICA
with tabs[0]:
    st.header("🧠 Buscador Inteligente por Contexto")
    st.markdown("Busca observaciones por significado en lenguaje natural y filtra por Evaluador o Especialidad.")
    
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        sel_evaluador = st.selectbox("Filtrar por Evaluador/Especialista:", ["TODOS"] + evaluadores_list) if evaluadores_list else "TODOS"
    with col_f2:
        sel_especialidad = st.selectbox("Filtrar por Especialidad Final:", ["TODAS"] + especialidades_list) if especialidades_list else "TODAS"
    with col_f3:
        top_k = st.slider("Resultados max:", min_value=5, max_value=50, value=10)

    query_text = st.text_input(
        "Ingresa temática o concepto a buscar en las observaciones:", 
        placeholder="Ej. monitoreo calidad de agua, modelamiento, topografía, etc."
    )

    if st.button("🔍 Buscar Hallazgos", type="primary") or query_text:
        vectorstore = load_vectorstore()
        if vectorstore:
            with st.spinner("Buscando en la base vectorial..."):
                filter_dict = {}
                conditions = []
                
                if sel_evaluador != "TODOS":
                    conditions.append({"evaluador": sel_evaluador})
                if sel_especialidad != "TODAS":
                    conditions.append({"especialidad": sel_especialidad})
                
                if len(conditions) == 1:
                    filter_dict = conditions[0]
                elif len(conditions) > 1:
                    filter_dict = {"$and": conditions}
                
                search_term = query_text if query_text.strip() else "observacion ambiental"
                
                if filter_dict:
                    results = vectorstore.similarity_search(search_term, k=top_k, filter=filter_dict)
                else:
                    results = vectorstore.similarity_search(search_term, k=top_k)
            
            st.subheader(f"📌 Top {len(results)} hallazgos encontrados:")
            if not results:
                st.info("No se encontraron coincidencias para los filtros seleccionados.")
            else:
                for i, res in enumerate(results, 1):
                    meta = res.metadata if hasattr(res, 'metadata') and res.metadata else {}
                    expediente = meta.get('Expediente', 'Sin Expediente')
                    especialidad = meta.get('Especialidad Final') or meta.get('especialidad', 'General')
                    titulo_proyecto = meta.get('Titulo Proyecto', 'Sin Título')
                    
                    with st.expander(f"Resultado #{i} | Expediente: {expediente} | Especialidad: {especialidad} | Proyecto: {titulo_proyecto}"):
                        st.write(res.page_content)
        else:
            st.warning("⚠️ No se encontró la carpeta 'chroma_db'. Ejecuta primero 'python regenerar_base.py'.")

# TAB 2: EXPLORADOR DE TABLA
with tabs[1]:
    st.header("✏️ Explorador de Tabla de Datos")
    conn = sqlite3.connect(DB_SQL_PATH)
    
    col_e1, col_e2 = st.columns([2, 2])
    with col_e1:
        filtro_esp = st.selectbox("Especialidad:", ["TODAS"] + especialidades_list) if especialidades_list else "TODAS"
    with col_e2:
        palabra_clave = st.text_input("Buscar por Texto:")
    
    query = 'SELECT * FROM observaciones WHERE 1=1'
    params = []
    
    if filtro_esp != "TODAS":
        query += ' AND "Especialidad Final" = ?'
        params.append(filtro_esp)
    if palabra_clave:
        query += ' AND ("Observacion" LIKE ? OR "Fundamento" LIKE ? OR "Titulo Proyecto" LIKE ?)'
        params.extend([f"%{palabra_clave}%", f"%{palabra_clave}%", f"%{palabra_clave}%"])
        
    query += " LIMIT 500"
    
    df_res = pd.read_sql(query, conn, params=params)
    conn.close()
    
    st.write(f"Mostrando {len(df_res)} registros:")
    st.dataframe(df_res, use_container_width=True, height=450)

# TAB 3: DASHBOARD Y METRICAS COMPLETAS
with tabs[2]:
    st.header("📊 Dashboard de Gestión & Métricas Historicas SENACE")
    conn = sqlite3.connect(DB_SQL_PATH)
    
    # Consultas para KPIs principales
    total_reg = pd.read_sql('SELECT COUNT(*) as Total FROM observaciones', conn)['Total'].iloc[0]
    total_expedientes = pd.read_sql('SELECT COUNT(DISTINCT "Expediente") as Total FROM observaciones WHERE "Expediente" IS NOT NULL', conn)['Total'].iloc[0]
    total_empresas = pd.read_sql('SELECT COUNT(DISTINCT "Empresa") as Total FROM observaciones WHERE "Empresa" IS NOT NULL', conn)['Total'].iloc[0]
    
    # Tarjetas KPI
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    col_kpi1.metric("Total Observaciones", f"{total_reg:,}")
    col_kpi2.metric("Expedientes Evaluados", f"{total_expedientes:,}")
    col_kpi3.metric("Empresas / Titulares", f"{total_empresas:,}")
    col_kpi4.metric("Especialidades", len(especialidades_list))
    
    st.markdown("---")
    
    # Gráficos de distribución
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        st.subheader("📌 Observaciones por Especialidad")
        df_esp = pd.read_sql('SELECT "Especialidad Final" AS Especialidad, COUNT(*) as Cantidad FROM observaciones WHERE "Especialidad Final" IS NOT NULL GROUP BY "Especialidad Final" ORDER BY Cantidad DESC LIMIT 10', conn)
        st.bar_chart(df_esp.set_index("Especialidad"))
        
    with col_g2:
        st.subheader("🏢 Top 10 Empresas con más Observaciones")
        df_emp = pd.read_sql('SELECT "Empresa", COUNT(*) as Cantidad FROM observaciones WHERE "Empresa" IS NOT NULL AND "Empresa" != "" GROUP BY "Empresa" ORDER BY Cantidad DESC LIMIT 10', conn)
        st.bar_chart(df_emp.set_index("Empresa"))
        
    st.markdown("---")
    
    col_g3, col_g4 = st.columns(2)
    
    with col_g3:
        st.subheader("👥 Carga de Trabajo por Coordinador / Líder")
        df_coord = pd.read_sql('SELECT "Coordinador", COUNT(*) as Cantidad FROM observaciones WHERE "Coordinador" IS NOT NULL AND "Coordinador" != "" GROUP BY "Coordinador" ORDER BY Cantidad DESC LIMIT 10', conn)
        st.bar_chart(df_coord.set_index("Coordinador"))
        
    with col_g4:
        st.subheader("📄 Top 10 Proyectos con más Hallazgos")
        df_proy = pd.read_sql('SELECT "Titulo Proyecto" AS Proyecto, COUNT(*) as Cantidad FROM observaciones WHERE "Titulo Proyecto" IS NOT NULL AND "Titulo Proyecto" != "" GROUP BY "Titulo Proyecto" ORDER BY Cantidad DESC LIMIT 10', conn)
        st.dataframe(df_proy, use_container_width=True, height=300)
        
    conn.close()