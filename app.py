import streamlit as st
import sqlite3
import os
import pandas as pd

# Configuración de la página
st.set_page_config(
    page_title="Sistema ITS SENACE",
    page_icon="🛡️",
    layout="wide"
)

DB_SQL_PATH = "datos_its.db"
EXCEL_PATH = "observaciones_clasificadas_FINAL_v33.xlsx"
CHROMA_PATH = "chroma_db"

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

def construir_base_datos():
    """Lee el Excel y construye SQLite directamente sin subprocesos."""
    if not os.path.exists(EXCEL_PATH):
        st.error(f"No se encontró el archivo Excel: {EXCEL_PATH}. Verifica que esté en la raíz del repositorio.")
        return False
    
    st.info("Leyendo archivo Excel y generando base de datos SQLite...")
    df = pd.read_excel(EXCEL_PATH)
    
    conn = obtener_conexion_sql()
    df.to_sql("observaciones", conn, if_exists="replace", index=False)
    conn.close()
    
    # Opcional: Generar embeddings si las librerías vectoriales están disponibles
    try:
        from langchain_community.vectorstores import Chroma
        from langchain_community.embeddings import FastEmbedEmbeddings
        from langchain_core.documents import Document
        
        st.info("Generando base vectorial ChromaDB...")
        docs = []
        for idx, row in df.iterrows():
            obs = str(row.get('Observación', '') or row.get('OBSERVACION', '')).strip()
            if obs and obs.lower() != 'nan':
                exp = str(row.get('Expediente', 'Sin Expediente')).strip()
                coord = str(row.get('Coordinador', 'Sin Coordinador')).strip()
                clasif = str(row.get('Especialidad Final', 'General')).strip()
                
                doc = Document(
                    page_content=obs,
                    metadata={
                        "expediente": exp,
                        "evaluador": coord,
                        "clasificacion": clasif
                    }
                )
                docs.append(doc)
        
        if docs:
            embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            Chroma.from_documents(docs, embeddings, persist_directory=CHROMA_PATH)
    except Exception as e:
        st.warning(f"Nota: Base SQLite creada correctamente. (Aviso vectorial: {e})")
        
    return True

# 1. VERIFICACIÓN Y CREACIÓN DE BASE DE DATOS
if not tabla_existe("observaciones"):
    with st.spinner("⏳ Generando base de datos inicial..."):
        exito = construir_base_datos()
        if exito:
            st.rerun()

# Encabezado Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica")

# Navegación por pestañas
tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda Semántica", "📋 Consulta General SQL", "📊 Dashboard & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA SEMÁNTICA
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
            evaluadores_df = pd.read_sql_query("SELECT DISTINCT Coordinador FROM observaciones WHERE Coordinador IS NOT NULL AND Coordinador != '' ORDER BY Coordinador", conn)
            lista_evaluadores += evaluadores_df['Coordinador'].tolist()
        except Exception:
            pass
        finally:
            conn.close()

    with col2:
        evaluador_filtro = st.selectbox("Filtrar por Evaluador/Especialista:", lista_evaluadores)

    if st.button("Buscar Observaciones", type="primary"):
        if query.strip():
            if not os.path.exists(CHROMA_PATH):
                # Búsqueda por coincidencia de texto en SQL como fallback si ChromaDB aún no está listo
                conn = obtener_conexion_sql()
                df_res = pd.read_sql_query(f"SELECT * FROM observaciones WHERE Observación LIKE '%{query}%' LIMIT {top_k}", conn)
                conn.close()
                st.success(f"Se encontraron {len(df_res)} observaciones por texto:")
                st.dataframe(df_res, use_container_width=True)
            else:
                with st.spinner("Buscando las observaciones más relevantes..."):
                    try:
                        from langchain_community.vectorstores import Chroma
                        from langchain_community.embeddings import FastEmbedEmbeddings
                        
                        embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
                        vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
                        
                        search_kwargs = {"k": top_k}
                        if evaluador_filtro != "Todos":
                            search_kwargs["filter"] = {"evaluador": evaluador_filtro}
                        
                        results = vectorstore.similarity_search(query, **search_kwargs)
                        st.success(f"Se encontraron {len(results)} observaciones relevantes:")
                        
                        for idx, doc in enumerate(results, 1):
                            with st.expander(f"📌 Resultado #{idx} - Expediente: {doc.metadata.get('expediente', 'N/A')} | Evaluador: {doc.metadata.get('evaluador', 'N/A')}"):
                                st.markdown(f"**Observación:**\n{doc.page_content}")
                                st.caption(f"Clasificación / Tema: {doc.metadata.get('clasificacion', 'Sin clasificación')}")
                    except Exception as e:
                        st.error(f"Error durante la búsqueda semántica: {e}")
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
        st.write("Mostrando los primeros 100 registros:")
        st.dataframe(df_preview, use_container_width=True)
    else:
        st.info("La tabla 'observaciones' aún no está construida en SQLite.")

# ---------------------------------------------------------
# PESTAÑA 3: DASHBOARD & MÉTRICAS
# ---------------------------------------------------------
with tab3:
    st.header("Estadísticas y Carga de Trabajo")
    if tabla_existe("observaciones"):
        conn = obtener_conexion_sql()
        try:
            df_metrics = pd.read_sql_query("SELECT Coordinador, COUNT(*) as Cantidad FROM observaciones GROUP BY Coordinador ORDER BY Cantidad DESC LIMIT 15", conn)
            if not df_metrics.empty:
                st.subheader("👥 Carga de Trabajo por Coordinador / Líder")
                st.bar_chart(df_metrics.set_index("Coordinador"))
            else:
                st.info("No hay registros disponibles para calcular las métricas.")
        except Exception as e:
            st.error(f"Error al calcular métricas: {e}")
        finally:
            conn.close()
    else:
        st.info("La tabla de observaciones aún no está disponible.")
