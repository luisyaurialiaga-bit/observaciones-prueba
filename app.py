"""
app.py -- SIGO (Sistema de Inteligencia y Gestion de Observaciones), Sugle S.A.C.

App publica sobre Supabase: las tres pestañas -- Busqueda, Consulta
General y Dashboard -- leen todas de la misma tabla "observaciones" en
Supabase (una sola fuente de verdad).

Que incluye:
    - "Busqueda de Observaciones": HIBRIDA, combina busqueda por
      palabra exacta (Postgres full-text search) con busqueda por
      significado (pgvector) contra la base completa en Supabase,
      usando la funcion buscar_hibrido(). Incluye filtro por
      especialidad y por evaluador, y un resumen de totales por
      especialidad (funcion contar_busqueda()).
    - "Consulta General" y "Dashboard" traen todas las filas de
      Supabase (paginando de a 1000, el maximo por pedido de la API).
    - Marca Sugle: colores, tipografia Calibri, logo y barra "SIGO".

Antes de desplegar (Streamlit Community Cloud):
    En Settings > Secrets de la app, pegar:

        SUPABASE_URL = "https://jtujaaqnxvzipgdmkirr.supabase.co"
        SUPABASE_ANON_KEY = "el JWT que empieza con eyJhbGci..."

    Archivos que deben ir junto a este app.py en el repo:
        - logo-sugle.png
        - logo-sugle-claro.png (version del logo con texto en Lila,
          para que se lea sobre el fondo morado oscuro de la barra)
        - .streamlit/config.toml (con client.disableDataExport = true,
          para ocultar el boton de descarga CSV de las tablas)
        - temas_recurrentes.json (opcional -- si no esta, el Dashboard
          muestra un aviso en vez de fallar)
        - requirements.txt debe incluir: streamlit, supabase,
          fastembed, pandas, openpyxl, plotly, pyarrow

Uso local:
    streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import base64
import os
import re
import unicodedata
from supabase import create_client

# ---------------------------------------------------------
# Configuracion general
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema ITS SENACE", page_icon="🛡️", layout="wide")

# Reduce el espacio en blanco de arriba (Streamlit deja bastante margen
# por defecto antes del contenido) para aprovechar mejor la pantalla.
# Los colores/logo de marca de Sugle se agregan aparte, esto solo
# ajusta el espaciado.
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
        }
        /* El boton de "Download as CSV" YA NO se oculta por CSS aqui --
        ese selector (button[title="Download as CSV"]) nunca funciono
        de verdad, porque Streamlit no pone el texto como atributo
        "title" del boton (es un tooltip que se genera aparte, fuera
        del boton). La forma correcta y oficial de ocultarlo es la
        opcion de configuracion "client.disableDataExport" en
        .streamlit/config.toml -- ver ese archivo. */

        /* -----------------------------------------------------
        Marca Sugle: tipografia + fondo + botones.
        OJO: esto NO toca los colores de los graficos del Dashboard
        (esos se definen aparte en el codigo Python de cada grafico,
        con color_continuous_scale, etc.) -- eso se deja intacto a
        proposito, tal como se pidio.
        ----------------------------------------------------- */

        /* Tipografia de marca */
        html, body, [class*="css"], .stApp, button, input, textarea, select {
            font-family: Calibri, "Segoe UI", sans-serif !important;
        }

        /* Fondo de marca (Lila Sugle) */
        .stApp {
            background-color: #E5DBEB;
        }
        /* La barra superior de Streamlit (donde sale "Deploy") trae su
        propio fondo blanco por defecto -- la hacemos transparente para
        que se vea el mismo lila de fondo, sin una franja blanca arriba. */
        header[data-testid="stHeader"] {
            background-color: transparent;
        }

        /* Botones primarios (ej. "Buscar Observaciones") */
        .stButton > button[kind="primary"] {
            background-color: #A02671; /* Morado Barney */
            color: #FFFFFF;
            border: none;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #3F1840; /* Morado Vino */
            color: #FFFFFF;
        }

        /* Botones secundarios */
        .stButton > button[kind="secondary"] {
            background-color: #673366; /* Morado Uva */
            color: #FFFFFF;
            border: none;
        }
        .stButton > button[kind="secondary"]:hover {
            background-color: #3F1840; /* Morado Vino */
            color: #FFFFFF;
        }

        /* Barra superior de marca "SIGO". El truco de
        left:50%/margin-left:-50vw hace que la barra ocupe todo el
        ancho de la pantalla aunque este dentro del contenedor central
        de Streamlit (que tiene su propio margen a los lados). */
        .sigo-header {
            position: relative;
            left: 50%;
            right: 50%;
            margin-left: -50vw;
            margin-right: -50vw;
            width: 100vw;
            margin-top: -1.5rem;
            margin-bottom: 1.5rem;
            background-color: #3F1840; /* Morado Vino */
            padding: 14px 40px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-sizing: border-box;
        }
        .sigo-header .sigo-marca {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .sigo-header .sigo-marca img {
            height: 36px;
        }
        .sigo-header .sigo-marca span {
            color: #FFFFFF;
            font-weight: 700;
            font-size: 1.38rem;
            letter-spacing: 0.5px;
        }

        /* Firma discreta, fija abajo a la derecha en toda la pantalla */
        .sigo-firma {
            position: fixed;
            bottom: 6px;
            right: 12px;
            font-style: italic;
            font-size: 0.79rem;
            color: rgba(63, 24, 64, 0.25); /* Morado Vino, muy tenue */
            z-index: 9999;
            pointer-events: none;
        }
        .sigo-header .sigo-derecha {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .sigo-header .sigo-tagline {
            color: #E5DBEB; /* Lila Sugle */
            font-size: 0.95rem;
        }
        .sigo-header .sigo-avatar {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background-color: #A02671; /* Morado Barney */
            color: #FFFFFF;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 0.8rem;
            flex-shrink: 0;
        }

        /* Pestañas: puntito antes del texto + color activo Morado
        Barney (en vez del rojo por defecto de Streamlit), imitando el
        mockup de Sugle. */
        button[data-baseweb="tab"] p {
            display: flex;
            align-items: center;
            gap: 7px;
        }
        button[data-baseweb="tab"] p::before {
            content: "";
            display: inline-block;
            width: 6px;
            height: 6px;
            min-width: 6px;
            border-radius: 50%;
            background-color: #B9A9C4;
        }
        button[data-baseweb="tab"][aria-selected="true"] p {
            color: #A02671 !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] p::before {
            background-color: #A02671;
        }
        [data-baseweb="tab-highlight"] {
            background-color: #A02671 !important;
        }

        /* Pantalla de carga a pantalla completa (19-ago-2026), solo para
        la carga inicial de datos desde Supabase. Reemplaza el mensaje
        de texto de Streamlit por un fondo lila uniforme con 3 puntos
        de marca rebotando en el centro -- ver .sigo-loading-overlay
        mas abajo en el codigo Python, donde se muestra/oculta con
        st.empty() alrededor de cargar_datos_supabase(). */
        .sigo-loading-overlay {
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            background-color: #E5DBEB; /* Lila Sugle, igual al fondo de la app */
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 18px;
            z-index: 999999;
        }
        .sigo-loading-overlay .sigo-dot {
            width: 22px;
            height: 22px;
            border-radius: 50%;
            animation: sigo-rebote 0.9s ease-in-out infinite;
        }
        .sigo-loading-overlay .sigo-dot-1 { background-color: #A02671; animation-delay: 0s; }
        .sigo-loading-overlay .sigo-dot-2 { background-color: #673366; animation-delay: 0.15s; }
        .sigo-loading-overlay .sigo-dot-3 { background-color: #3F1840; animation-delay: 0.3s; }
        @keyframes sigo-rebote {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.6; }
            40% { transform: translateY(-18px); opacity: 1; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Color de fondo de marca (Lila Sugle) aplicado al "papel" y area de
# trazado de TODOS los graficos del Dashboard, para que no quede una
# caja blanca dentro de la pagina lila. OJO: esto es solo el fondo --
# no toca los colores de barras/lineas/torta de cada grafico (esos se
# definen aparte, con color_continuous_scale, color_discrete_map, etc.)
COLOR_FONDO_GRAFICOS = "#E5DBEB"


def aplicar_fondo_marca(fig):
    fig.update_layout(
        paper_bgcolor=COLOR_FONDO_GRAFICOS,
        plot_bgcolor=COLOR_FONDO_GRAFICOS,
    )
    return fig


MODELO_EMBEDDING = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


# ---------------------------------------------------------
# Conexion a Supabase + modelo de embeddings (para la pestaña Busqueda)
# ---------------------------------------------------------
@st.cache_resource(show_spinner="Conectando a la base de datos...")
def conectar_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


@st.cache_resource(show_spinner="Cargando el modelo de busqueda semantica (primera vez tarda un poco)...")
def cargar_modelo_embeddings():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODELO_EMBEDDING)


def vector_a_texto_postgres(vector):
    """pgvector espera el vector como texto tipo '[0.1,0.2,...]' para
    poder convertirlo (cast) al tipo vector(384) declarado en la
    funcion buscar_hibrido(). Un JSON crudo no siempre castea bien."""
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


# ---------------------------------------------------------
# Utilidades para Consulta General / Dashboard
# ---------------------------------------------------------
def valor_o_vacio(valor):
    """Devuelve el valor como texto limpio, o '' si es NaN/nulo -- evita
    que aparezca literalmente 'nan' en pantalla cuando una celda esta
    vacia (algo muy comun en columnas como Subsanacion, con ~61% vacias)."""
    if pd.isna(valor):
        return ''
    return str(valor).strip()


def formatear_parrafos(texto):
    """
    Reconstruye parrafos legibles en textos largos extraidos de PDF, donde
    los saltos de linea originales se perdieron y todo quedo en una sola
    linea corrida. Inserta un salto de parrafo antes de:
      - vinetas '•'
      - incisos tipo 'a)', 'b)', 'c)'... que empiezan una clausula nueva
        (precedidos de un punto/espacio y seguidos de mayuscula)
    """
    if not texto:
        return texto
    t = texto
    t = re.sub(r'\s*•\s*', '\n\n• ', t)
    t = re.sub(r'(?<=[.\s])([a-z])\)\s+(?=[A-ZÁÉÍÓÚÑ])', r'\n\n\1) ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def quitar_tildes(texto):
    """Quita tildes/diacríticos para poder comparar 'Iban' y 'Ibán' como el mismo nombre."""
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn')


def contar_tildes(texto):
    """Cuenta cuántos caracteres con tilde/diacrítico tiene el texto."""
    return sum(1 for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) == 'Mn')


def normalizar_nombres(serie):
    """
    Agrupa variantes de un mismo nombre que difieren solo en tildes/mayusculas
    (ej. 'Iban' y 'Ibán') y las reemplaza a TODAS por una unica forma canonica.
    Se prioriza la variante CON MAS TILDES, y solo se usa la frecuencia como
    desempate cuando dos variantes tienen la misma cantidad de tildes.
    """
    claves = serie.apply(lambda x: quitar_tildes(x).upper())

    def elegir_forma(grupo):
        conteos = grupo.value_counts()
        variantes = conteos.index.tolist()
        variantes_ordenadas = sorted(
            variantes,
            key=lambda v: (contar_tildes(v), conteos[v]),
            reverse=True
        )
        return variantes_ordenadas[0]

    forma_canonica = serie.groupby(claves).agg(elegir_forma)
    return claves.map(forma_canonica)


MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def parsear_fecha_es(texto):
    """Parsea fechas con formato tipo 'San Isidro, 07 de mayo de 2026'."""
    if not isinstance(texto, str):
        return pd.NaT
    m = re.search(r'(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})', texto, re.IGNORECASE)
    if not m:
        return pd.NaT
    dia, mes_txt, anio = m.groups()
    mes = MESES_ES.get(quitar_tildes(mes_txt).lower())
    if not mes:
        return pd.NaT
    try:
        return pd.Timestamp(year=int(anio), month=mes, day=int(dia))
    except ValueError:
        return pd.NaT


# Nombres de columna en Supabase (snake_case) -> nombres que ya usaba
# el Excel (con los que esta escrito el resto del codigo de Consulta
# General / Dashboard). Renombrando aca, no hay que tocar nada mas
# abajo en esas dos pestañas.
RENOMBRAR_SUPABASE = {
    "n": "N", "expediente": "Expediente", "titulo_proyecto": "Titulo Proyecto",
    "unidad_proyecto": "Unidad Proyecto", "tipo_estudio": "Tipo Estudio",
    "empresa": "Empresa", "informe": "Informe", "fecha": "Fecha",
    "coordinador": "Coordinador", "lider_proyecto": "Lider Proyecto",
    "esp_legal": "Esp. Legal", "esp_sig": "Esp. SIG",
    "esp_descrip_proyectos": "Esp. Descrip. Proyectos", "esp_fisico": "Esp. Fisico",
    "esp_biologico": "Esp. Biologico", "esp_social": "Esp. Social",
    "otros_evaluadores": "Otros Evaluadores", "archivo": "Archivo",
    "pagina": "Pagina", "tipo_matriz": "Tipo Matriz", "n_obs": "N Obs",
    "requisito": "Requisito", "item": "Item", "entidad": "Entidad",
    "fundamento": "Fundamento", "observacion": "Observacion",
    "subsanacion": "Subsanacion", "subsana_sino": "Subsana",
    "tiene_imagen": "Tiene Imagen", "ref_imagen": "Ref Imagen",
    "especialidad_final": "Especialidad Final", "metodo_clasificacion": "Metodo Clasificacion",
}

# Columnas a pedirle a Supabase -- todas menos "embedding" (384 numeros
# por fila, no hace falta para estas dos pestañas y solo pesaria mas
# la descarga) y "id"/"creado_en" (no se usan en Consulta General ni
# Dashboard).
COLUMNAS_SUPABASE = ",".join(RENOMBRAR_SUPABASE.keys())


@st.cache_data(show_spinner=False, ttl=600)
def cargar_datos_supabase(_supabase):
    """Trae TODAS las filas de la tabla observaciones, paginando de a
    1000 (limite por pedido de la API de Supabase/PostgREST). El
    guion bajo en '_supabase' es a proposito: le dice a st.cache_data
    que no intente usar ese argumento para decidir si el cache sigue
    valido (un cliente de Supabase no se puede "hashear"). El spinner
    default de Streamlit esta apagado (show_spinner=False) porque el
    llamado a esta funcion, mas abajo, ya muestra su propia pantalla
    de carga a pantalla completa (.sigo-loading-overlay)."""
    filas = []
    inicio = 0
    LOTE = 1000
    while True:
        resp = (
            _supabase.table("observaciones")
            .select(COLUMNAS_SUPABASE)
            .range(inicio, inicio + LOTE - 1)
            .execute()
        )
        lote = resp.data or []
        filas.extend(lote)
        if len(lote) < LOTE:
            break
        inicio += LOTE

    if not filas:
        return None

    df = pd.DataFrame(filas).rename(columns=RENOMBRAR_SUPABASE)
    return limpiar_dataframe(df)


TEMAS_JSON_PATH = "temas_recurrentes.json"


@st.cache_data(show_spinner=False)
def cargar_temas_recurrentes():
    """Lee temas_recurrentes.json (generado aparte por
    descubrir_temas_recurrentes.py) si existe. Devuelve None si todavia
    no se genero -- la pestaña de Dashboard muestra un aviso en ese caso
    en vez de fallar."""
    import json as _json
    if not os.path.exists(TEMAS_JSON_PATH):
        return None
    with open(TEMAS_JSON_PATH, encoding="utf-8") as f:
        return _json.load(f)


def limpiar_dataframe(df):
    col_obs = "Observacion"
    for col in ["Observación", "OBSERVACION", "Observacion", "observacion"]:
        if col in df.columns:
            col_obs = col
            break

    df[col_obs] = df[col_obs].astype(str).str.strip()
    df = df[df[col_obs].notna() & (df[col_obs] != "") & (df[col_obs].str.lower() != "nan")].copy()

    if 'Coordinador' not in df.columns:
        if 'Especialista' in df.columns:
            df['Coordinador'] = df['Especialista']
        else:
            df['Coordinador'] = 'Sin Asignar'

    df['Coordinador'] = df['Coordinador'].fillna('Sin Asignar').astype(str).str.strip().str.title()
    df['Coordinador'] = df['Coordinador'].replace({'Nan': 'Sin Asignar', 'None': 'Sin Asignar', '': 'Sin Asignar'})

    mask_asignado = df['Coordinador'] != 'Sin Asignar'
    if mask_asignado.any():
        df.loc[mask_asignado, 'Coordinador'] = normalizar_nombres(df.loc[mask_asignado, 'Coordinador'])

    # ALIAS_COORDINADOR: casos donde la MISMA persona aparece con
    # nombres de distinta longitud (ej. con o sin segundo nombre) --
    # normalizar_nombres() no los agrupa porque no son la misma cadena
    # salvo tildes/mayusculas, hace falta el alias manual. Se mapea al
    # nombre MAS COMPLETO como forma canonica.
    ALIAS_COORDINADOR = {
        'Marco Tello Cochachez': 'Marco Antonio Tello Cochachez',
    }
    df['Coordinador'] = df['Coordinador'].replace(ALIAS_COORDINADOR)

    for col in ['Expediente', 'Especialidad Final', 'Empresa', 'Titulo Proyecto']:
        if col in df.columns:
            # "Especialidad Final" en blanco significa que el motor de
            # reglas no logro asignarle una categoria -- "Sin clasificar"
            # es el termino correcto (no "Sin informacion", que suena a
            # que falta un dato de captura, cosa distinta).
            relleno = 'Sin clasificar' if col == 'Especialidad Final' else 'Sin información'
            df[col] = df[col].fillna(relleno).astype(str).str.strip()
            df.loc[df[col] == '', col] = relleno
            if col == 'Empresa':
                mask_emp = df[col] != 'Sin información'
                if mask_emp.any():
                    df.loc[mask_emp, col] = normalizar_nombres(df.loc[mask_emp, col])

    return df, col_obs


# ---------------------------------------------------------
# Encabezado principal
# ---------------------------------------------------------
def _logo_sugle_base64():
    """Lee logo-sugle-claro.png (debe estar en la misma carpeta que
    este archivo) y lo devuelve codificado en base64, para incrustarlo
    directo en el HTML del encabezado -- asi no depende de una ruta de
    archivo que se pueda romper al copiar la app a otra carpeta.

    Es una version del logo original (logo-sugle.png) con el texto
    "SUGLE" / "Sustainable Global Engineering" recoloreado a Lila
    (#E5DBEB) -- en negro/gris oscuro original se perdia contra el
    fondo morado oscuro de la barra. Los 3 anillos de color (rojo,
    azul, verde) se dejaron igual, esos si se veian bien."""
    try:
        with open("logo-sugle-claro.png", "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return None


_logo_b64 = _logo_sugle_base64()
_logo_html = (
    f'<img src="data:image/png;base64,{_logo_b64}">'
    if _logo_b64 else ""
)

st.markdown(
    f"""
    <div class="sigo-header">
        <div class="sigo-marca">
            {_logo_html}
            <span>SIGO</span>
        </div>
        <div class="sigo-derecha">
            <span class="sigo-tagline">Sistema de Inteligencia y Gestión de Observaciones</span>
            <div class="sigo-avatar">SG</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption("Matriz de observaciones clasificadas · Base histórica normalizada de expedientes ITS")

st.markdown('<div class="sigo-firma">jlya</div>', unsafe_allow_html=True)

supabase = conectar_supabase()

_placeholder_carga = st.empty()
_placeholder_carga.markdown(
    """
    <div class="sigo-loading-overlay">
        <div class="sigo-dot sigo-dot-1"></div>
        <div class="sigo-dot sigo-dot-2"></div>
        <div class="sigo-dot sigo-dot-3"></div>
    </div>
    """,
    unsafe_allow_html=True,
)
datos = cargar_datos_supabase(supabase)
_placeholder_carga.empty()

if datos is None:
    st.error("⚠️ No se pudo cargar información desde Supabase (la tabla respondió vacía). "
             "Verifica que la migración de datos se haya completado.")
    st.stop()

df_all, col_obs = datos

tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda de Observaciones", "📋 Consulta General", "📊 Dashboard Completo & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA HÍBRIDA (Supabase + IA)
# ---------------------------------------------------------
with tab1:
    st.header("Búsqueda Avanzada de Observaciones (palabra clave + IA)")

    # Envolver los campos en un st.form hace que presionar Enter en
    # cualquiera de ellos dispare la busqueda -- Streamlit lo hace
    # automaticamente para formularios, sin tener que programar nada
    # aparte para detectar la tecla Enter.
    with st.form("form_busqueda"):
        query = st.text_input(
            "Ingrese la consulta o temática a buscar:",
            placeholder="Ej: bofedal impacto, calidad de aire, plan de participación ciudadana..."
        )

        col1, col2, col3 = st.columns([1, 2, 2])
        with col1:
            top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)
        with col2:
            especialidad_filtro = st.text_input(
                "Filtrar por especialidad (opcional, dejar vacío = todas):",
                placeholder="Ej: Fisico, Social, Biologico..."
            )
        with col3:
            evaluador_filtro = st.text_input(
                "Filtrar por evaluador (opcional, dejar vacío = todos):",
                placeholder="Ej: Carlos Eduardo Moya Sulca..."
            )

        buscar = st.form_submit_button("Buscar Observaciones", type="primary")

    if buscar:
        if not query.strip():
            st.warning("Por favor ingrese un texto de consulta.")
        else:
            with st.spinner("Convirtiendo tu búsqueda en coordenadas de significado..."):
                modelo = cargar_modelo_embeddings()
                vector_consulta = list(modelo.embed([query]))[0].tolist()

            with st.spinner("Consultando la base (texto + IA)..."):
                resultado = supabase.rpc("buscar_hibrido", {
                    "consulta_texto": query,
                    "consulta_vector": vector_a_texto_postgres(vector_consulta),
                    "filtro_especialidad": especialidad_filtro.strip() or None,
                    "cantidad": top_k,
                    "filtro_evaluador": evaluador_filtro.strip() or None,
                }).execute()

            filas = resultado.data or []

            if not filas:
                st.info("No se encontraron observaciones que coincidan con la búsqueda.")
            else:
                # Cuenta el total real de coincidencias por texto (sin el
                # limite "cantidad" que usa buscar_hibrido) para mostrar
                # "encontrados en total" + desglose por especialidad,
                # ademas de la lista de resultados de abajo (que sigue
                # limitada a top_k, ordenada por relevancia combinada).
                total_encontrados = None
                desglose_especialidad = []
                try:
                    conteo = supabase.rpc("contar_busqueda", {
                        "consulta_texto": query,
                        "filtro_especialidad": especialidad_filtro.strip() or None,
                        "filtro_evaluador": evaluador_filtro.strip() or None,
                    }).execute()
                    desglose_especialidad = conteo.data or []
                    total_encontrados = sum(f["cantidad"] for f in desglose_especialidad)
                except Exception:
                    pass  # si la funcion contar_busqueda aun no existe en Supabase, seguimos sin el resumen

                if total_encontrados:
                    mostrando = min(len(filas), top_k)
                    st.success(
                        f"Se encontraron **{total_encontrados}** observaciones en total "
                        f"— mostrando las primeras **{mostrando}**:"
                    )
                    texto_desglose = " &nbsp;|&nbsp; ".join(
                        f"{f['especialidad_final']} ({f['cantidad']})" for f in desglose_especialidad
                    )
                    st.markdown(f"Por especialidad: {texto_desglose}")
                else:
                    # No hubo coincidencia EXACTA de texto para "total"
                    # (por eso contar_busqueda no devolvio nada) -- paso
                    # normal cuando la busqueda encontro resultados solo
                    # por significado (IA), no porque la palabra literal
                    # este en el texto (ej: "fragmentacion" sin que esa
                    # palabra exacta aparezca en ninguna observacion).
                    # Igual mostramos el desglose por especialidad, pero
                    # calculado sobre los resultados que si se muestran.
                    conteo_mostrados = {}
                    for f in filas:
                        esp = f.get("especialidad_final") or "Sin clasificar"
                        conteo_mostrados[esp] = conteo_mostrados.get(esp, 0) + 1
                    st.success(
                        f"Se encontraron **{len(filas)}** observaciones "
                        f"(por significado, sin coincidencia exacta de texto):"
                    )
                    texto_desglose = " &nbsp;|&nbsp; ".join(
                        f"{esp} ({cant})" for esp, cant in sorted(conteo_mostrados.items(), key=lambda x: -x[1])
                    )
                    st.markdown(f"Por especialidad: {texto_desglose}")

                for i, fila in enumerate(filas, 1):
                    exp = fila.get("expediente") or "Sin información"
                    empresa = fila.get("empresa") or "Sin información"
                    proyecto = fila.get("titulo_proyecto") or "Sin información"
                    especialidad = fila.get("especialidad_final") or ""
                    coordinador = fila.get("coordinador") or ""
                    item = fila.get("item") or ""
                    fundamento = fila.get("fundamento") or ""
                    observacion = fila.get("observacion") or "Sin detalle"
                    subsanacion = fila.get("subsanacion") or ""
                    informe = fila.get("informe") or ""
                    pagina = fila.get("pagina") or ""

                    score_texto = fila.get("score_texto")
                    score_semantico = fila.get("score_semantico")
                    score_combinado = fila.get("score_combinado")

                    with st.expander(f"📌 Resultado #{i} | Expediente: {exp}" + (f" | Evaluador: {coordinador}" if coordinador else "")):
                        etiquetas = []
                        if especialidad:
                            etiquetas.append(f"🏷️ {especialidad}")
                        if coordinador:
                            etiquetas.append(f"👤 {coordinador}")
                        if item:
                            etiquetas.append(f"📍 {item}")
                        if score_texto:
                            etiquetas.append(f"🔤 relevancia texto: {score_texto:.3f}")
                        if score_semantico is not None:
                            etiquetas.append(f"🧠 relevancia semántica: {score_semantico:.3f}")
                        if score_combinado is not None:
                            etiquetas.append(f"🎯 relevancia combinada: {score_combinado:.3f}")
                        if etiquetas:
                            st.caption(" &nbsp;|&nbsp; ".join(etiquetas))

                        st.markdown(f"**Proyecto:** {proyecto}")
                        st.markdown(f"**Empresa:** {empresa}")
                        st.markdown("---")

                        if fundamento:
                            st.markdown(f"**⚖️ Fundamento:**\n\n{formatear_parrafos(fundamento)}")
                            st.markdown("")

                        st.markdown(f"**Observación:**\n\n{formatear_parrafos(str(observacion))}")

                        if subsanacion:
                            st.markdown("")
                            st.markdown(f"**✅ Cómo se subsanó:**\n\n{formatear_parrafos(subsanacion)}")

                        if informe:
                            ref = f" — página {pagina}" if pagina else ""
                            st.caption(f"Fuente: {informe}{ref}")

# ---------------------------------------------------------
# PESTAÑA 2: CONSULTA GENERAL
# ---------------------------------------------------------
COLUMNAS_POR_DEFECTO = [
    "N", "Expediente", "Titulo Proyecto", "Unidad Proyecto", "Empresa",
    "Informe", "Fecha", "Coordinador", "N Obs", "Fundamento", "Observacion",
]

with tab2:
    st.header("Explorador de la Base de Datos")
    st.write(f"Total de registros: **{len(df_all):,}**")

    filtro_libre = st.text_input(
        "Filtrar (opcional) — busca en todas las columnas de texto:",
        placeholder="Ej: un nombre, una empresa, una palabra clave..."
    )

    if filtro_libre.strip():
        cols_texto = df_all.select_dtypes(include="object").columns
        mask = pd.Series(False, index=df_all.index)
        for c in cols_texto:
            mask = mask | df_all[c].astype(str).str.contains(filtro_libre.strip(), case=False, na=False)
        df_mostrar = df_all[mask]
        st.write(f"Coincidencias: **{len(df_mostrar):,}**")
    else:
        df_mostrar = df_all

    # column_order deja encendidas por defecto solo estas columnas --
    # el resto no desaparecen, se pueden volver a prender con el icono
    # de "ojo" que ya trae la tabla en su barra de herramientas (arriba
    # a la derecha).
    orden_columnas = [c for c in COLUMNAS_POR_DEFECTO if c in df_mostrar.columns]
    st.dataframe(df_mostrar, use_container_width=True, height=600, column_order=orden_columnas)

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
    col_kpi3.metric("Evaluadores", f"{total_evaluadores}")
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
            aplicar_fondo_marca(fig_eval)
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
            aplicar_fondo_marca(fig_tema)
            st.plotly_chart(fig_tema, use_container_width=True)

    col_chart3, col_chart4 = st.columns(2)

    with col_chart3:
        st.subheader("🏢 Top 20 Empresas con más Observaciones")
        if 'Empresa' in df_all.columns:
            df_emp = df_all[df_all['Empresa'] != 'Sin información']['Empresa'].value_counts().reset_index()
            df_emp.columns = ['Empresa', 'Cantidad']

            fig_emp = px.bar(
                df_emp.head(20).sort_values('Cantidad'),
                x='Cantidad',
                y='Empresa',
                orientation='h',
                color='Cantidad',
                color_continuous_scale='Reds'
            )
            fig_emp.update_layout(showlegend=False, height=650)
            aplicar_fondo_marca(fig_emp)
            st.plotly_chart(fig_emp, use_container_width=True)

    with col_chart4:
        st.subheader("📂 Top Expedientes con Mayor Número de Hallazgos")
        if 'Expediente' in df_all.columns:
            df_exp = df_all[df_all['Expediente'] != 'Sin información']['Expediente'].value_counts().reset_index()
            df_exp.columns = ['Expediente', 'Cantidad']
            df_exp = df_exp.head(10)

            def _partir_en_2_lineas(texto, max_por_linea=22):
                """Corta un nombre largo en 2 lineas (con <br>), partiendo
                en el espacio mas cercano a la mitad -- para que no salga
                una sola linea gigante al rotarla en vertical."""
                if len(texto) <= max_por_linea:
                    return texto
                espacios = [i for i, c in enumerate(texto) if c == ' ']
                if not espacios:
                    return texto
                corte = min(espacios, key=lambda i: abs(i - len(texto) // 2))
                return texto[:corte] + '<br>' + texto[corte + 1:]

            if 'Empresa' in df_all.columns:
                # una empresa por expediente (la mas frecuente, por si
                # hay alguna inconsistencia de captura entre filas)
                mapa_empresa = (
                    df_all[df_all['Expediente'].isin(df_exp['Expediente'])]
                    .groupby('Expediente')['Empresa']
                    .agg(lambda s: s.value_counts().idxmax() if len(s) else '')
                )
                df_exp['Empresa_label'] = df_exp['Expediente'].map(mapa_empresa).fillna('')
                df_exp.loc[df_exp['Empresa_label'] == 'Sin información', 'Empresa_label'] = ''
                df_exp['Empresa_label'] = df_exp['Empresa_label'].apply(
                    lambda t: _partir_en_2_lineas(t) if t else t
                )
            else:
                df_exp['Empresa_label'] = ''

            fig_exp = px.bar(
                df_exp,
                x='Expediente',
                y='Cantidad',
                color='Cantidad',
                color_continuous_scale='Greens'
            )
            # Se ocultan los ticks nativos (horizontales) del eje: el
            # numero de expediente se dibuja como parte de la misma
            # anotacion vertical que la empresa, para que ambos queden
            # alineados en un solo bloque de 3 lineas por barra (numero
            # + nombre de empresa en 2 lineas), todo mas abajo para
            # aprovechar el espacio en blanco.
            fig_exp.update_xaxes(showticklabels=False, title=dict(text='Expediente', standoff=10))
            fig_exp.update_layout(margin=dict(b=320), height=750)
            for _, fila_exp in df_exp.iterrows():
                texto = fila_exp['Expediente']
                if fila_exp['Empresa_label']:
                    texto += f"<br>{fila_exp['Empresa_label']}"
                fig_exp.add_annotation(
                    x=fila_exp['Expediente'], xref='x',
                    y=0, yref='paper', yshift=-37,
                    text=texto,
                    showarrow=False, textangle=90,
                    font=dict(size=11.5), align='left',
                    # yanchor='top' ancla el INICIO del bloque de texto
                    # (no el centro) al mismo punto para todas las
                    # barras -- sin esto, un nombre de empresa mas largo
                    # queda centrado y arranca mas abajo que uno corto,
                    # que es justo el desalineado que se vio en pantalla.
                    xanchor='center', yanchor='top',
                )
            aplicar_fondo_marca(fig_exp)
            st.plotly_chart(fig_exp, use_container_width=True)

    st.markdown("---")
    st.subheader("🧭 Vistas adicionales")

    col_chart5, col_chart6 = st.columns(2)

    with col_chart5:
        col_tema = 'Especialidad Final' if 'Especialidad Final' in df_all.columns else None
        if 'Coordinador' in df_all.columns and col_tema:
            st.markdown("**Mapa de calor: Evaluador × Especialidad**")
            df_hm = df_all[df_all['Coordinador'] != 'Sin Asignar']
            top_evaluadores = df_hm['Coordinador'].value_counts().head(12).index
            top_especialidades = df_hm[col_tema].value_counts().head(10).index
            df_hm = df_hm[df_hm['Coordinador'].isin(top_evaluadores) & df_hm[col_tema].isin(top_especialidades)]
            if not df_hm.empty:
                tabla_cruzada = pd.crosstab(df_hm['Coordinador'], df_hm[col_tema])
                fig_hm = px.imshow(
                    tabla_cruzada,
                    text_auto=True,
                    color_continuous_scale='Blues',
                    aspect="auto"
                )
                fig_hm.update_layout(xaxis_title="Especialidad", yaxis_title="Evaluador")
                aplicar_fondo_marca(fig_hm)
                st.plotly_chart(fig_hm, use_container_width=True)
            else:
                st.caption("No hay suficientes datos cruzados para mostrar.")

    with col_chart6:
        st.markdown("**Temas más recurrentes (agrupados por significado)**")
        temas = cargar_temas_recurrentes()
        if temas is None:
            st.caption(
                "Todavía no se generó este análisis. Corre `python descubrir_temas_recurrentes.py` "
                "(agrupa las observaciones por significado usando los vectores de Supabase) y copia "
                "el `temas_recurrentes.json` resultante a esta misma carpeta."
            )
        else:
            df_tema_rec = pd.DataFrame(temas).head(15)
            fig_item = px.bar(
                df_tema_rec.sort_values('cantidad'),
                x='cantidad',
                y='tema',
                orientation='h',
                color='cantidad',
                color_continuous_scale='Purples'
            )
            fig_item.update_layout(showlegend=False, yaxis_title='Tema', xaxis_title='Cantidad')
            aplicar_fondo_marca(fig_item)
            st.plotly_chart(fig_item, use_container_width=True)
            st.caption(
                "Cada tema agrupa observaciones parecidas EN SIGNIFICADO (no por texto exacto), "
                "usando los vectores de IA ya generados. Las palabras de cada tema son las más "
                "distintivas de ese grupo, no un título elegido a mano."
            )

    col_chart7, col_chart8 = st.columns(2)

    with col_chart7:
        col_imagen = next((c for c in ['Tiene Imagen', 'tiene_imagen'] if c in df_all.columns), None)
        if col_imagen:
            st.markdown("**Observaciones con evidencia gráfica**")
            df_img = df_all[col_imagen].astype(str).str.upper().str.strip()
            df_img = df_img.replace({'SI': 'Con imagen', 'SÍ': 'Con imagen', 'NO': 'Sin imagen'})
            df_img_counts = df_img.value_counts().reset_index()
            df_img_counts.columns = ['Estado', 'Cantidad']
            fig_img = px.pie(
                df_img_counts,
                names='Estado',
                values='Cantidad',
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            aplicar_fondo_marca(fig_img)
            st.plotly_chart(fig_img, use_container_width=True)

    with col_chart8:
        col_fecha = next((c for c in ['Fecha', 'FECHA', 'fecha'] if c in df_all.columns), None)
        if col_fecha:
            st.markdown("**Evolución de observaciones en el tiempo**")
            df_fecha = df_all.copy()
            df_fecha[col_fecha] = df_fecha[col_fecha].apply(parsear_fecha_es)
            df_fecha = df_fecha.dropna(subset=[col_fecha])
            if not df_fecha.empty:
                df_mensual = df_fecha.set_index(col_fecha).resample('ME').size().reset_index()
                df_mensual.columns = ['Mes', 'Cantidad']
                fig_tiempo = px.line(df_mensual, x='Mes', y='Cantidad', markers=True)
                aplicar_fondo_marca(fig_tiempo)
                st.plotly_chart(fig_tiempo, use_container_width=True)
            else:
                st.caption("No se pudieron interpretar las fechas de esta columna.")

    col_chart9, _ = st.columns(2)

    with col_chart9:
        col_fecha = next((c for c in ['Fecha', 'FECHA', 'fecha'] if c in df_all.columns), None)
        if col_fecha and 'Expediente' in df_all.columns:
            st.markdown("**ITS evaluados por año**")
            df_its = df_all.copy()
            df_its[col_fecha] = df_its[col_fecha].apply(parsear_fecha_es)
            df_its = df_its.dropna(subset=[col_fecha])
            if not df_its.empty:
                df_its['Año'] = df_its[col_fecha].dt.year
                its_por_anio = df_its.groupby('Año')['Expediente'].nunique().reset_index()
                its_por_anio.columns = ['Año', 'Cantidad de ITS']
                fig_its_anio = px.bar(
                    its_por_anio,
                    x='Año',
                    y='Cantidad de ITS',
                    color='Cantidad de ITS',
                    color_continuous_scale='Teal',
                    text='Cantidad de ITS'
                )
                fig_its_anio.update_layout(showlegend=False, xaxis=dict(type='category'))
                aplicar_fondo_marca(fig_its_anio)
                st.plotly_chart(fig_its_anio, use_container_width=True)

                sin_fecha = df_all['Expediente'].nunique() - df_its['Expediente'].nunique()
                if sin_fecha > 0:
                    st.caption(f"({sin_fecha} expediente(s) sin fecha identificable, no incluido(s) en el gráfico)")
            else:
                st.caption("No se pudieron interpretar las fechas de esta columna.")
