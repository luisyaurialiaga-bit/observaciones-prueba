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

def obtener_columna_observacion(conn):
    """Detecta dinámicamente cómo se llama la columna de texto de observación."""
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(observaciones)")
        columnas = [info[1] for info in cursor.fetchall()]
        
        for col in ["Observación", "OBSERVACION", "Observacion", "observacion"]:
            if col in columnas:
                return col
        return columnas[0] if columnas else "Observacion"
    except Exception:
        return "Observacion"

def construir_base_rapida():
    """Construcción ultrarrápida (solo SQLite) para evitar sobrecargar la CPU de la nube."""
    if not os.path.exists(EXCEL_PATH):
        st.error(f"No se encontró el archivo Excel: {EXCEL_PATH}.")
        return False
    
    # Cargar Excel y guardar SQLite directamente (tarda < 2 segundos)
    df = pd.read_excel(EXCEL_PATH)
    conn = obtener_conexion_sql()
    df.to_sql("observaciones", conn, if_exists="replace", index=False)
    conn.close()
    return True

# 1. VERIFICACIÓN Y CREACIÓN ULTRARRÁPIDA
if not tabla_existe("observaciones"):
    with st.spinner("⚡ Construyendo base de datos ultrarrápida..."):
        if construir_base_rapida():
            st.rerun()

# Encabezado Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica")

# Navegación por pestañas
tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda de Observaciones", "📋 Consulta General SQL", "📊 Dashboard & Métricas"])

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
            evaluadores_df = pd.read_sql_query('SELECT DISTINCT "Coordinador" FROM observaciones WHERE "Coordinador" IS NOT NULL AND "Coordinador" != "" ORDER BY "Coordinador"', conn)
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
            
            # Intento de búsqueda semántica con Chroma si existe el directorio
            busqueda_semantica_exitosa = False
            if os.path.exists(CHROMA_PATH):
                try:
                    from langchain_community.vectorstores import Chroma
                    from langchain_community.embeddings import FastEmbedEmbeddings
                    
                    with st.spinner("Buscando con Inteligencia Vectorial..."):
                        embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
                        vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
                        
                        search_kwargs = {"k": top_k}
                        if evaluador_filtro != "Todos":
                            search_kwargs["filter"] = {"evaluador": evaluador_filtro}
                        
                        results = vectorstore.similarity_search(query, **search_kwargs)
                        if results:
                            st.success(f"Se encontraron {len(results)} observaciones semánticamente relevantes:")
                            for idx, doc in enumerate(results, 1):
                                with st.expander(f"📌 Resultado #{idx} - Expediente: {doc.metadata.get('expediente', 'N/A')} | Evaluador: {doc.metadata.get('evaluador', 'N/A')}"):
                                    st.markdown(f"**Observación:**\n{doc.page_content}")
                                    st.caption(f"Clasificación / Tema: {doc.metadata.get('clasificacion', 'Sin clasificación')}")
                            busqueda_semantica_exitosa = True
                except Exception:
                    busqueda_semantica_exitosa = False
            
            # Fallback a búsqueda rápida mediante consulta SQL (coincidencia de texto)
            if not busqueda_semantica_exitosa:
                query_sql = f'SELECT * FROM observaciones WHERE "{col_obs}" LIKE ?'
                params = [f"%{query.strip()}%"]
                
                if evaluador_filtro != "Todos":
                    query_sql += ' AND "Coordinador" = ?'
                    params.append(evaluador_filtro)
                
                query_sql += f" LIMIT {top_k}"
                
                df_res = pd.read_sql_query(query_sql, conn, params=params)
                conn.close()
                
                st.success(f"Se encontraron {len(df_res)} observaciones relacionadas:")
                st.dataframe(df_res, use_container_width=True)
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
            df_metrics = pd.read_sql_query('SELECT "Coordinador", COUNT(*) as Cantidad FROM observaciones WHERE "Coordinador" IS NOT NULL AND "Coordinador" != "" GROUP BY "Coordinador" ORDER BY Cantidad DESC LIMIT 15', conn)
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
