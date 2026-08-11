import pandas as pd
import os
import sqlite3
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_core.documents import Document

EXCEL_PATH = "observaciones_clasificadas_FINAL_v33.xlsx"
DB_SQL_PATH = "datos_its.db"
CHROMA_PATH = "chroma_db"

print("1. Leyendo archivo Excel...")
df = pd.read_excel(EXCEL_PATH)

print("2. Guardando en SQLite (datos_its.db)...")
conn = sqlite3.connect(DB_SQL_PATH)
df.to_sql("observaciones", conn, if_exists="replace", index=False)
conn.close()

print("3. Preparando documentos para ChromaDB...")
docs = []
for idx, row in df.iterrows():
    # Extraer valores reales evitando nulos
    expediente = str(row.get('Expediente', '')).strip()
    if not expediente or expediente.lower() == 'nan':
        expediente = "Sin Expediente"
        
    especialidad = str(row.get('Especialidad Final', '')).strip()
    if not especialidad or especialidad.lower() == 'nan':
        especialidad = "General"

    titulo_proyecto = str(row.get('Titulo Proyecto', '')).strip()
    if not titulo_proyecto or titulo_proyecto.lower() == 'nan':
        titulo_proyecto = "Sin Título"
        
    coordinador = str(row.get('Coordinador', '')).strip()
    observacion = str(row.get('Observacion', '')).strip()
    fundamento = str(row.get('Fundamento', '')).strip()
    
    # Texto completo que leerá la IA para buscar
    contenido = f"Expediente: {expediente} | Especialidad: {especialidad} | Proyecto: {titulo_proyecto} | Observación: {observacion} | Fundamento: {fundamento}"
    
    # Guardar metadatos exactos que leerá Streamlit
    metadata = {
        "Expediente": expediente,
        "Especialidad Final": especialidad,
        "especialidad": especialidad,
        "Titulo Proyecto": titulo_proyecto,
        "evaluador": coordinador if coordinador and coordinador.lower() != 'nan' else "No Asignado"
    }
    
    docs.append(Document(page_content=contenido, metadata=metadata))

print(f"4. Reconstruyendo ChromaDB en la carpeta '{CHROMA_PATH}'...")
embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

if os.path.exists(CHROMA_PATH):
    import shutil
    shutil.rmtree(CHROMA_PATH)

Chroma.from_documents(docs, embeddings, persist_directory=CHROMA_PATH)
print("✅ ¡Proceso completado con éxito! La base inteligente fue actualizada.")