import streamlit as st
import sqlite3
import os
import subprocess
import pandas as pd
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings

# Configuración de página
st.set_page_config(
    page_title="Sistema ITS SENACE",
    page_icon="🛡️",
    layout="wide"
)

DB_SQL_PATH = "datos_its.db"
CHROMA_PATH = "chroma_db"

# 1. GENERACIÓN AUTOMÁTICA DE BASE DE DATOS EN LA NUBE
if not os.path.exists(DB_SQL_PATH):
    if os.path.exists("regenerar_base.py"):
        with st.spinner("⚡ Inicializando base de datos en la nube por primera vez... Esto tomará cerca de un minuto."):
            subprocess.run(["python", "regenerar_base.py"])
    else:
        st.error("⚠️ No se encontró la base de datos 'datos_its.db' ni el script 'regenerar_base.py'.")
        st.stop()

# 2. CARGA DE BASE VECTORIAL Y CONEXIONES
@st.cache_resource
def cargar_vectorstore():
    embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)

def obtener_conexion_sql():
    return sqlite3.connect(DB_SQL_PATH)

# Título Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica")

# Pestañas de la Aplicación
tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda Semántica", "📋 Consulta General SQL", "📊 Dashboard & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA SEMÁNTICA
# ---------------------------------------------------------
with tab1:
    st.header("Búsqueda Avanzada de Observaciones")
    query = st.text_input("Ingrese la consulta o temática a buscar:", placeholder="Ej: monitoreo de calidad de aire, plan de participacion ciudadana...")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)
    
    # Obtener evaluadores para filtro
    conn = obtener_conexion_sql()
    try:
        evaluadores_df = pd.read_sql_query("SELECT DISTINCT Coordinador FROM observaciones WHERE Coordinador IS NOT NULL AND Coordinador != '' ORDER BY Coordinador", conn)
        lista_evaluadores = ["Todos"] + evaluadores_df['Coordinador'].tolist()
    except:
        lista_evaluadores = ["Todos"]
    conn.close()

    with col2:
        evaluador_filtro = st.selectbox("Filtrar por Evaluador/Especialista:", lista_evaluadores)

    if st.button("Buscar Observaciones", type="primary"):
        if query.strip():
            with st.spinner("Buscando las observaciones más relevantes..."):
                vectorstore = cargar_vectorstore()
                
                # Configurar filtro metadata si aplica
                search_kwargs = {"k": top_k}
                if evaluador_filtro != "Todos":
                    search_kwargs["filter"] = {"evaluador": evaluador_filtro}
                
                results = vectorstore.similarity_search(query, **search_kwargs)
                
                st.success(f"Se encontraron {len(results)} observaciones relevantes:")
                
                for idx, doc in enumerate(results, 1):
                    with st.expander(f"📌 Resultado #{idx} - Expediente: {doc.metadata.get('expediente', 'N/A')} | Evaluador: {doc.metadata.get('evaluador', 'N/A')}"):
                        st.markdown(f"**Observación:**\n{doc.page_content}")
                        st.caption(f"Clasificación / Tema: {doc.metadata.get('clasificacion', 'Sin clasificación')}")
        else:
            st.warning("Por favor ingrese un texto de consulta.")

# ---------------------------------------------------------
# PESTAÑA 2: CONSULTA GENERAL SQL
# ---------------------------------------------------------
with tab2:
    st.header("Explorador de la Base de Datos")
    conn = obtener_conexion_sql()
    df_preview = pd.read_sql_query("SELECT * FROM observaciones LIMIT 100", conn)
    conn.close()
    
    st.write("Mostrando los primeros 100 registros:")
    st.dataframe(df_preview, width="stretch")

# ---------------------------------------------------------
# PESTAÑA 3: DASHBOARD
# ---------------------------------------------------------
with tab3:
    st.header("Estadísticas y Carga de Trabajo")
    conn = obtener_conexion_sql()
    df_metrics = pd.read_sql_query("SELECT Coordinador, COUNT(*) as Cantidad FROM observaciones GROUP BY Coordinador ORDER BY Cantidad DESC LIMIT 15", conn)
    conn.close()
    
    if not df_metrics.empty:
        st.subheader("👥 Carga de Trabajo por Coordinador / Líder")
        st.bar_chart(df_metrics.set_index("Coordinador"))
    else:
        st.info("No hay datos para mostrar en las métricas.")
