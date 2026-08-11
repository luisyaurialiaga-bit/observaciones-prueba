import sqlite3
import unicodedata
import re
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings

DB_SQL_PATH = "datos_its.db"
CHROMA_PATH = "chroma_db"

def quitar_tildes_y_limpiar(texto):
    if not texto or str(texto).lower() in ['nan', 'none', 'no asignado']:
        return "No Asignado"
    
    texto = str(texto).strip().upper()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

print("1. Normalizando en SQLite (datos_its.db)...")
conn = sqlite3.connect(DB_SQL_PATH)
cursor = conn.cursor()

columnas = [
    'Coordinador', 'Lider Proyecto', 'Esp. Legal', 'Esp. SIG', 
    'Esp. Descrip. Proyectos', 'Esp. Fisico', 'Esp. Biologico', 
    'Esp. Social', 'Otros Evaluadores'
]

for col in columnas:
    try:
        cursor.execute(f'SELECT DISTINCT "{col}" FROM observaciones WHERE "{col}" IS NOT NULL AND "{col}" != ""')
        valores = cursor.fetchall()
        for (val,) in valores:
            val_norm = quitar_tildes_y_limpiar(val)
            if val != val_norm:
                cursor.execute(f'UPDATE observaciones SET "{col}" = ? WHERE "{col}" = ?', (val_norm, val))
    except Exception as e:
        pass

conn.commit()
conn.close()
print("  └─ SQLite actualizado.")

print("2. Normalizando en ChromaDB por lotes...")
embeddings = FastEmbedEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)

data = vectorstore.get()
ids = data['ids']
metadatas = data['metadatas']

actualizados = 0
for i in range(len(ids)):
    meta = metadatas[i] if metadatas[i] else {}
    evaluador_actual = meta.get('evaluador', '')
    evaluador_norm = quitar_tildes_y_limpiar(evaluador_actual)
    
    if evaluador_actual != evaluador_norm:
        meta['evaluador'] = evaluador_norm
        actualizados += 1

# Actualización por lotes (máximo 2000 por lote para evitar el límite de 5461)
BATCH_SIZE = 2000
total_registros = len(ids)

print(f"Iniciando actualización de {total_registros} registros en lotes de {BATCH_SIZE}...")

for i in range(0, total_registros, BATCH_SIZE):
    batch_ids = ids[i : i + BATCH_SIZE]
    batch_metadatas = metadatas[i : i + BATCH_SIZE]
    
    vectorstore._collection.update(
        ids=batch_ids,
        metadatas=batch_metadatas
    )
    
    num_lote = (i // BATCH_SIZE) + 1
    total_lotes = (total_registros + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  └─ Lote {num_lote}/{total_lotes} procesado con éxito.")

print("✅ ¡Proceso completado con éxito sin rebasar los límites!")