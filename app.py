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
from supabase import create_client, ClientOptions
from postgrest.exceptions import APIError

# ---------------------------------------------------------
# Configuracion general
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema ITS SENACE", page_icon=":material/shield:", layout="wide")

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

        /* Fondo general: gris muy claro con tinte lila -- antes era el
        lila solido de marca en TODA la pantalla, lo que no dejaba
        resaltar las tarjetas blancas (formulario, sidebar activo,
        etc.). El lila de marca fuerte ahora vive solo en el sidebar. */
        .stApp {
            background-color: #F4F1F7;
        }
        /* La barra superior de Streamlit (donde sale "Deploy") trae su
        propio fondo blanco por defecto -- la hacemos transparente para
        que se vea el mismo fondo de la app, sin una franja blanca arriba. */
        header[data-testid="stHeader"] {
            background-color: transparent;
        }

        /* Botones primarios (ej. "Buscar Observaciones"). El selector
        NO se limita a ".stButton > button" a proposito: los botones de
        formulario (st.form_submit_button) viven en un contenedor
        distinto (stFormSubmitButton), y con el selector viejo nunca
        heredaban el morado de marca -- por eso salian en rojo, el
        color por defecto de Streamlit. */
        button[kind="primary"] {
            background-color: #A02671; /* Morado Barney */
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
        }
        button[kind="primary"]:hover {
            background-color: #3F1840; /* Morado Vino */
            color: #FFFFFF;
        }

        /* Botones secundarios: pill blanco con borde lila (usado en
        "Reintentar" y en los chips de accesos rapidos/busquedas
        recientes de la pestaña de Busqueda). */
        button[kind="secondary"] {
            background-color: #FFFFFF;
            color: #673366; /* Morado Uva */
            border: 1px solid #D9CCE3;
            border-radius: 999px;
        }
        button[kind="secondary"]:hover {
            background-color: #F4E9F1;
            color: #3F1840; /* Morado Vino */
            border-color: #A02671;
        }

        /* Sidebar de navegacion (reemplaza las pestañas de arriba). */
        [data-testid="stSidebar"] {
            background-color: #3F1840; /* Morado Vino */
        }
        [data-testid="stSidebar"] > div {
            padding-top: 1.4rem;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label {
            color: #E5DBEB;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
            text-align: left;
            justify-content: flex-start;
            border-radius: 8px;
            padding: 10px 14px;
            font-weight: 500;
            font-size: 0.92rem;
        }
        /* Item de navegacion INACTIVO: transparente sobre el fondo
        morado del sidebar. */
        [data-testid="stSidebar"] button[kind="secondary"] {
            background-color: transparent;
            border: none;
            color: #D9CCE3;
        }
        [data-testid="stSidebar"] button[kind="secondary"]:hover {
            background-color: rgba(255, 255, 255, 0.08);
            color: #FFFFFF;
            border: none;
        }
        /* Item de navegacion ACTIVO: resaltado + barra lateral clara,
        imitando el mockup. */
        [data-testid="stSidebar"] button[kind="primary"] {
            background-color: rgba(255, 255, 255, 0.12);
            color: #FFFFFF;
            border-left: 3px solid #E5DBEB;
            border-radius: 8px;
        }
        [data-testid="stSidebar"] button[kind="primary"]:hover {
            background-color: rgba(255, 255, 255, 0.18);
        }

        .sigo-sidebar-brand {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 0 12px 20px 12px;
            margin-bottom: 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        }
        .sigo-sidebar-brand img {
            height: 32px;
        }
        .sigo-sidebar-brand .sigo-sidebar-titulo {
            font-weight: 700;
            font-size: 1.1rem;
            color: #FFFFFF;
            line-height: 1.15;
        }
        .sigo-sidebar-brand .sigo-sidebar-subtitulo {
            font-size: 0.68rem;
            color: #C6AFCB;
            line-height: 1.25;
            margin-top: 2px;
        }

        .sigo-sidebar-footer {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 18px 12px 6px 12px;
            margin-top: 18px;
            border-top: 1px solid rgba(255, 255, 255, 0.12);
        }
        .sigo-sidebar-footer .sigo-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background-color: #A02671; /* Morado Barney */
            color: #FFFFFF;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 0.75rem;
            flex-shrink: 0;
        }
        .sigo-sidebar-footer .sigo-sidebar-footer-texto strong {
            display: block;
            color: #FFFFFF;
            font-size: 0.82rem;
        }
        .sigo-sidebar-footer .sigo-sidebar-footer-texto span {
            color: #C6AFCB;
            font-size: 0.72rem;
        }

        /* Barra superior del area de contenido (reemplaza el hero
        morado + el titulo repetido en cada pestaña): titulo/subtitulo
        de la pagina actual a la izquierda, estadisticas en vivo a la
        derecha. */
        .sigo-topbar {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            margin-bottom: 1.5rem;
            padding-bottom: 1.1rem;
            border-bottom: 1px solid #E1D6E8;
        }
        .sigo-topbar-titulo {
            font-size: 1.5rem;
            font-weight: 700;
            color: #221527;
            line-height: 1.25;
        }
        .sigo-topbar-subtitulo {
            font-size: 0.92rem;
            color: #6B5E71;
            margin-top: 2px;
        }
        .sigo-topbar-stats {
            font-size: 0.85rem;
            color: #6B5E71;
            white-space: nowrap;
            margin-top: 4px;
            text-align: right;
        }

        /* Tarjeta blanca del formulario de busqueda -- st.form ya trae
        su propio contenedor (stForm), asi que solo hay que vestirlo. */
        [data-testid="stForm"] {
            background-color: #FFFFFF;
            border-radius: 12px;
            padding: 1.6rem 1.8rem;
            border: 1px solid #E9E1EE;
            box-shadow: 0 1px 3px rgba(63, 24, 64, 0.06);
        }

        /* Encabezado chico de las secciones de "accesos rapidos" y
        "busquedas recientes" debajo del formulario. */
        .sigo-seccion-chips {
            margin: 1.5rem 0 0.6rem 0;
            font-size: 0.78rem;
            font-weight: 700;
            color: #8A7C90;
            text-transform: uppercase;
            letter-spacing: 0.04em;
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

        /* Pantalla de carga a pantalla completa (19-ago-2026), solo para
        la carga inicial de datos desde Supabase. Reemplaza el mensaje
        de texto de Streamlit por un fondo uniforme con 3 puntos
        de marca rebotando en el centro -- ver .sigo-loading-overlay
        mas abajo en el codigo Python, donde se muestra/oculta con
        st.empty() alrededor de cargar_datos_supabase(). */
        .sigo-loading-overlay {
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            background-color: #F4F1F7; /* igual al fondo general de la app */
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

# Color de fondo de marca aplicado al "papel" y area de trazado de
# TODOS los graficos del Dashboard, para que no quede una caja blanca
# (ni una caja de otro tono) dentro de la pagina. Debe coincidir con
# el fondo general definido en el CSS de arriba (.stApp). OJO: esto es
# solo el fondo -- no toca los colores de barras/lineas/torta de cada
# grafico (esos se definen aparte, con color_continuous_scale, etc.)
COLOR_FONDO_GRAFICOS = "#F4F1F7"


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
    # Timeout explicito (20s por pedido): sin esto, si Supabase esta
    # lento o "dormido" (plan gratuito se pausa por inactividad), la
    # app se queda con el spinner de carga trabado indefinidamente en
    # vez de mostrar un error que se pueda reintentar.
    opciones = ClientOptions(postgrest_client_timeout=20)
    return create_client(url, key, options=opciones)


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


TENDENCIAS_JSON_PATH = "ranking_tipos_hallazgo.json"


@st.cache_data(show_spinner=False)
def cargar_ranking_tendencias():
    """Lee ranking_tipos_hallazgo.json (generado aparte por
    clasificar_tipo_hallazgo.py) si existe. Devuelve None si todavia
    no se genero -- el Dashboard muestra un aviso en ese caso en vez
    de fallar."""
    import json as _json
    if not os.path.exists(TENDENCIAS_JSON_PATH):
        return None
    with open(TENDENCIAS_JSON_PATH, encoding="utf-8") as f:
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

# ---------------------------------------------------------
# Sidebar de navegacion (21-ago-2026, reemplaza las pestañas de
# arriba por un menu lateral tipo SaaS -- ver mockup de referencia).
# La pagina activa se guarda en session_state para sobrevivir los
# reruns que dispara Streamlit en cada interaccion.
# ---------------------------------------------------------
# Iconos Material Symbols (nativos de Streamlit, sin depender de un
# CDN externo) en vez de emojis, para un look mas profesional.
PAGINAS_SIGO = [
    ("busqueda", ":material/search:", "Búsqueda de Observaciones"),
    ("consulta", ":material/table_view:", "Consulta General"),
    ("dashboard", ":material/bar_chart:", "Dashboard & Métricas"),
    ("evaluador", ":material/psychology:", "Evaluador IA"),
]
if "sigo_pagina" not in st.session_state:
    st.session_state.sigo_pagina = "busqueda"

with st.sidebar:
    st.markdown(
        f"""
        <div class="sigo-sidebar-brand">
            {_logo_html}
            <div>
                <div class="sigo-sidebar-titulo">SIGO</div>
                <div class="sigo-sidebar-subtitulo">Sistema de Inteligencia y<br>Gestión de Observaciones</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for _clave, _icono, _etiqueta in PAGINAS_SIGO:
        _es_activa = st.session_state.sigo_pagina == _clave
        if st.button(
            _etiqueta,
            key=f"nav_{_clave}",
            icon=_icono,
            type="primary" if _es_activa else "secondary",
            use_container_width=True,
        ):
            st.session_state.sigo_pagina = _clave
            st.rerun()
    st.markdown(
        """
        <div class="sigo-sidebar-footer">
            <div class="sigo-avatar">SG</div>
            <div class="sigo-sidebar-footer-texto">
                <strong>Equipo Sugle</strong>
                <span>Consultoría minero-ambiental</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown('<div class="sigo-firma">jlya</div>', unsafe_allow_html=True)

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
try:
    supabase = conectar_supabase()
    datos = cargar_datos_supabase(supabase)
except Exception as e:
    _placeholder_carga.empty()
    st.error(
        "No se pudo conectar con la base de datos (Supabase no respondió a "
        f"tiempo o hubo un error de conexión).\n\nDetalle tecnico: `{e}`",
        icon=":material/warning:",
    )
    if st.button("Reintentar", icon=":material/refresh:"):
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()
    st.stop()
_placeholder_carga.empty()

if datos is None:
    st.error("No se pudo cargar información desde Supabase (la tabla respondió vacía). "
             "Verifica que la migración de datos se haya completado.",
             icon=":material/warning:")
    st.stop()

df_all, col_obs = datos

# ---------------------------------------------------------
# Barra superior del contenido: titulo/subtitulo de la pagina actual
# + estadisticas en vivo, en reemplazo del hero morado + titulo
# repetido en cada pestaña que habia antes.
# ---------------------------------------------------------
_TEXTOS_TOPBAR = {
    "busqueda": (
        "Búsqueda de Observaciones",
        "Buscador temático y por significado (IA) sobre el historial de observaciones SENACE",
    ),
    "consulta": (
        "Consulta General",
        "Explorador completo de la matriz de observaciones históricas",
    ),
    "dashboard": (
        "Dashboard & Métricas",
        "Estadísticas, tendencias y patrones de exigencia técnica sobre toda la base",
    ),
    "evaluador": (
        "Evaluador IA",
        "Análisis automático de documentos ITS contra el criterio histórico de SENACE",
    ),
}
COLUMNAS_POR_DEFECTO = [
    "N", "Expediente", "Titulo Proyecto", "Unidad Proyecto", "Empresa",
    "Informe", "Fecha", "Coordinador", "N Obs", "Fundamento", "Observacion",
]

_titulo_pagina, _subtitulo_pagina = _TEXTOS_TOPBAR[st.session_state.sigo_pagina]
_total_expedientes_topbar = df_all['Expediente'].nunique() if 'Expediente' in df_all.columns else 0
st.markdown(
    f"""
    <div class="sigo-topbar">
        <div>
            <div class="sigo-topbar-titulo">{_titulo_pagina}</div>
            <div class="sigo-topbar-subtitulo">{_subtitulo_pagina}</div>
        </div>
        <div class="sigo-topbar-stats">{len(df_all):,} observaciones · {_total_expedientes_topbar:,} expedientes</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# PÁGINA: BÚSQUEDA HÍBRIDA (Supabase + IA)
# ---------------------------------------------------------
if st.session_state.sigo_pagina == "busqueda":

    # Opciones de los desplegables de especialidad/evaluador, sacadas
    # directamente de df_all (ya cargado desde Supabase mas arriba) --
    # asi la lista siempre refleja los valores reales de la base, sin
    # mantenerla a mano. "Sin Asignar" se excluye del de evaluador
    # porque no es un evaluador real (mismo criterio que el resto del
    # Dashboard, ver mask_asignado en limpiar_dataframe()).
    OPCION_TODAS_ESP = "(Todas)"
    OPCION_TODOS_EVAL = "(Todos)"
    opciones_especialidad = [OPCION_TODAS_ESP] + (
        sorted(df_all['Especialidad Final'].dropna().unique().tolist())
        if 'Especialidad Final' in df_all.columns else []
    )
    opciones_evaluador = [OPCION_TODOS_EVAL] + (
        sorted(df_all.loc[df_all['Coordinador'] != 'Sin Asignar', 'Coordinador'].dropna().unique().tolist())
        if 'Coordinador' in df_all.columns else []
    )

    def _sigo_set_query(texto):
        """Callback de los chips de accesos rapidos/busquedas recientes:
        precarga el campo de busqueda y marca que hay que buscar de
        una, sin esperar un segundo click en "Buscar Observaciones".
        Tiene que ser un on_click (no escribir session_state despues
        del formulario a secas) porque Streamlit no deja modificar el
        valor de un widget con key ya instanciado en el mismo run --
        el callback SI corre antes de que el widget se vuelva a crear."""
        st.session_state["sigo_query"] = texto
        st.session_state["sigo_auto_buscar"] = True

    # Envolver los campos en un st.form hace que presionar Enter en
    # cualquiera de ellos dispare la busqueda -- Streamlit lo hace
    # automaticamente para formularios, sin tener que programar nada
    # aparte para detectar la tecla Enter.
    with st.form("form_busqueda"):
        query = st.text_input(
            "Ingrese la consulta o temática a buscar:",
            key="sigo_query",
            placeholder="Ej: bofedal impacto, calidad de aire, plan de participación ciudadana..."
        )

        col1, col2, col3 = st.columns([1, 2, 2])
        with col1:
            top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)
        with col2:
            especialidad_filtro = st.selectbox(
                "Filtrar por especialidad (opcional):",
                options=opciones_especialidad,
            )
        with col3:
            evaluador_filtro = st.selectbox(
                "Filtrar por evaluador (opcional):",
                options=opciones_evaluador,
            )

        buscar = st.form_submit_button("Buscar Observaciones", type="primary")

    especialidad_valor = None if especialidad_filtro == OPCION_TODAS_ESP else especialidad_filtro
    evaluador_valor = None if evaluador_filtro == OPCION_TODOS_EVAL else evaluador_filtro

    if st.session_state.pop("sigo_auto_buscar", False):
        buscar = True

    # Accesos rapidos + busquedas recientes: solo se muestran ANTES de
    # buscar -- en el mismo rerun en el que se despliegan resultados,
    # este bloque se oculta (por eso "desaparece" al llegar la data).
    if not buscar:
        temas_sugeridos = cargar_temas_recurrentes()
        if temas_sugeridos:
            sugerencias = [t["tema"] for t in temas_sugeridos[:5]]
        else:
            sugerencias = [
                "Bofedal impacto", "Calidad de aire", "Plan de participación ciudadana",
                "Biodiversidad", "Cronograma de actividades",
            ]
        st.markdown('<div class="sigo-seccion-chips">Accesos rápidos</div>', unsafe_allow_html=True)
        cols_chip = st.columns(len(sugerencias))
        for _col_chip, _tema in zip(cols_chip, sugerencias):
            with _col_chip:
                st.button(
                    _tema,
                    key=f"sigo_chip_{_tema}",
                    on_click=_sigo_set_query,
                    args=(_tema.replace(" / ", " "),),
                    use_container_width=True,
                )

        _recientes = st.session_state.get("sigo_recientes", [])
        if _recientes:
            st.markdown('<div class="sigo-seccion-chips">Búsquedas recientes</div>', unsafe_allow_html=True)
            cols_rec = st.columns(len(_recientes))
            for _col_rec, _q in zip(cols_rec, _recientes):
                with _col_rec:
                    st.button(
                        _q,
                        key=f"sigo_reciente_{_q}",
                        icon=":material/history:",
                        on_click=_sigo_set_query,
                        args=(_q,),
                        use_container_width=True,
                    )

    if buscar:
        if not query.strip():
            st.warning("Por favor ingrese un texto de consulta.")
        else:
            _recientes = st.session_state.get("sigo_recientes", [])
            if query in _recientes:
                _recientes.remove(query)
            st.session_state["sigo_recientes"] = ([query] + _recientes)[:5]

            with st.spinner("Convirtiendo tu búsqueda en coordenadas de significado..."):
                modelo = cargar_modelo_embeddings()
                vector_consulta = list(modelo.embed([query]))[0].tolist()

            with st.spinner("Consultando la base (texto + IA)..."):
                # buscar_hibrido puede tardar demasiado con consultas de
                # una sola palabra muy generica (ej. "aire", "agua") --
                # el texto de esa palabra hace match con casi todas las
                # 20 mil filas, lo que dispara el statement_timeout de
                # Postgres (codigo 57014). Se atrapa aca para mostrar un
                # aviso util en vez de reventar la app con un traceback.
                filas = None
                try:
                    resultado = supabase.rpc("buscar_hibrido", {
                        "consulta_texto": query,
                        "consulta_vector": vector_a_texto_postgres(vector_consulta),
                        "filtro_especialidad": especialidad_valor,
                        "cantidad": top_k,
                        "filtro_evaluador": evaluador_valor,
                    }).execute()
                    filas = resultado.data or []
                except APIError as e:
                    if getattr(e, "code", None) == "57014":
                        st.error(
                            "La búsqueda tardó demasiado en la base de datos. Esto suele pasar "
                            "con palabras sueltas muy genéricas (ej. \"aire\", \"agua\"). Prueba con "
                            "una frase más específica, de 2 o más palabras "
                            "(ej. \"calidad de aire\" en vez de \"aire\").",
                            icon=":material/schedule:",
                        )
                    else:
                        st.error(f"Ocurrió un problema al consultar la base de datos: {e}", icon=":material/warning:")
                except Exception as e:
                    st.error(f"Ocurrió un problema inesperado al consultar la base de datos: {e}", icon=":material/warning:")

            if filas is None:
                pass  # ya se mostro el aviso de error arriba
            elif not filas:
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
                        "filtro_especialidad": especialidad_valor,
                        "filtro_evaluador": evaluador_valor,
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

                    titulo_resultado = f"Resultado #{i} | Expediente: {exp}" + (f" | Evaluador: {coordinador}" if coordinador else "")
                    with st.expander(titulo_resultado, icon=":material/push_pin:"):
                        etiquetas = []
                        if especialidad:
                            etiquetas.append(f":material/label: {especialidad}")
                        if coordinador:
                            etiquetas.append(f":material/person: {coordinador}")
                        if item:
                            etiquetas.append(f":material/location_on: {item}")
                        if score_texto:
                            etiquetas.append(f":material/text_fields: relevancia texto: {score_texto:.3f}")
                        if score_semantico is not None:
                            etiquetas.append(f":material/psychology: relevancia semántica: {score_semantico:.3f}")
                        if score_combinado is not None:
                            etiquetas.append(f":material/track_changes: relevancia combinada: {score_combinado:.3f}")
                        if etiquetas:
                            st.caption(" &nbsp;|&nbsp; ".join(etiquetas))

                        st.markdown(f"**Proyecto:** {proyecto}")
                        st.markdown(f"**Empresa:** {empresa}")
                        st.markdown("---")

                        if fundamento:
                            st.markdown(f"**:material/balance: Fundamento:**\n\n{formatear_parrafos(fundamento)}")
                            st.markdown("")

                        st.markdown(f"**Observación:**\n\n{formatear_parrafos(str(observacion))}")

                        if subsanacion:
                            st.markdown("")
                            st.markdown(f"**:material/check_circle: Cómo se subsanó:**\n\n{formatear_parrafos(subsanacion)}")

                        if informe:
                            ref = f" — página {pagina}" if pagina else ""
                            st.caption(f"Fuente: {informe}{ref}")

# ---------------------------------------------------------
# PÁGINA: CONSULTA GENERAL
# ---------------------------------------------------------
elif st.session_state.sigo_pagina == "consulta":
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
# PÁGINA: DASHBOARD COMPLETO & MÉTRICAS
# ---------------------------------------------------------
elif st.session_state.sigo_pagina == "dashboard":
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
        st.subheader(":material/groups: Carga de Trabajo por Evaluador")
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
        st.subheader(":material/label: Distribución por Especialidad / Tema")
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
        st.subheader(":material/apartment: Top 20 Empresas con más Observaciones")
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
        st.subheader(":material/folder_open: Top Expedientes con Mayor Número de Hallazgos")
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
    st.subheader(":material/explore: Vistas adicionales")

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

    st.markdown("---")
    st.markdown("**Ranking de tendencias por tipo de hallazgo**")
    ranking_tend = cargar_ranking_tendencias()
    if ranking_tend is None:
        st.caption(
            "Todavía no se generó este análisis. Corre `python clasificar_tipo_hallazgo.py` "
            "(clasifica las observaciones históricas por tipo de pedido: sustento, aclaración, "
            "corrección, contradicción, etc.) y copia el `ranking_tipos_hallazgo.json` resultante "
            "a esta misma carpeta."
        )
    else:
        df_tend = pd.DataFrame(ranking_tend["ranking_tendencias"])
        fig_tend = px.bar(
            df_tend.sort_values('cantidad'),
            x='cantidad',
            y='categoria',
            orientation='h',
            color='cantidad',
            color_continuous_scale='RdPu',
            text='porcentaje'
        )
        fig_tend.update_traces(texttemplate='%{text}%', textposition='outside')
        fig_tend.update_layout(showlegend=False, yaxis_title='Tipo de hallazgo', xaxis_title='Cantidad de observaciones', height=450)
        aplicar_fondo_marca(fig_tend)
        st.plotly_chart(fig_tend, use_container_width=True)
        st.caption(
            "Cada observación puede pedir varias cosas a la vez (sustento, corrección, aclaración...), "
            "por eso una misma observación puede contar en más de una categoría y los porcentajes "
            "suman más de 100%. No es un error."
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

elif st.session_state.sigo_pagina == "evaluador":
    st.caption(
        "Próximamente: sube tu documento y SIGO lo revisará con el mismo criterio "
        "que aprendió de miles de observaciones reales de SENACE."
    )

    st.markdown("---")
    st.subheader("¿Cómo llegamos hasta acá?")

    pasos = [
        ("1", "Descarga histórica",
         "Se recopilaron los expedientes ITS evaluados por SENACE a lo largo de los años, "
         "con miles de observaciones reales emitidas por especialistas."),
        ("2", "Discriminación y depuración",
         "Cada observación se clasificó por especialidad (Físico, Biológico, Social, Legal, "
         "Descripción de Proyectos, entre otras), descartando registros incompletos o duplicados."),
        ("3", "Extracción y estructuración",
         "La información se extrajo a una base tabular (Excel → base de datos), conservando "
         "expediente, empresa, especialidad, fundamento y observación de cada hallazgo."),
        ("4", "Normalización",
         "El texto se normalizó y se generaron vectores de significado (IA) para cada "
         "observación, habilitando búsquedas por texto exacto y por significado."),
        ("5", "Base de datos limpia y clasificada",
         "Resultado: 20 515 observaciones históricas, consultables en segundos desde la "
         "pestaña de Búsqueda."),
        ("6", "Análisis de tendencias",
         "Sobre el 100% de la base se identificó qué TIPO de hallazgo es más frecuente en la "
         "historia de SENACE: falta de sustento técnico, aclaración, corrección, contradicción "
         "interna, omisión de análisis, entre otros."),
        ("7", "Análisis de severidad",
         "Cada observación histórica se clasificó como DE FONDO (crítica: impactos, cuerpos de "
         "agua, especies protegidas, viabilidad del ITS) o DE FORMA (leyenda, escala, "
         "denominación), cruzado por especialidad."),
    ]

    for numero, titulo, texto in pasos:
        st.markdown(f"""
        <div style="display:flex; gap:16px; margin-bottom:18px; align-items:flex-start;">
            <div style="background-color:#3F1840; color:#E5DBEB; min-width:36px; height:36px;
                        border-radius:50%; display:flex; align-items:center; justify-content:center;
                        font-weight:bold; font-size:16px; flex-shrink:0;">{numero}</div>
            <div>
                <div style="font-weight:bold; color:#3F1840; font-size:16px;">{titulo}</div>
                <div style="color:#333; font-size:14px;">{texto}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("""
    <div style="background-color:#E5DBEB; border-left:5px solid #A02671; padding:18px 22px;
                border-radius:6px; margin-bottom:20px;">
        <div style="font-weight:bold; color:#3F1840; font-size:17px; margin-bottom:6px;">
            Con esos dos ejes — tendencia y severidad — como base
        </div>
        <div style="color:#333; font-size:14.5px;">
            El documento que se suba aquí será observado por un modelo de IA avanzado, comparando
            su contenido contra los patrones reales que SENACE ha emitido históricamente — no contra
            suposiciones genéricas. El mismo documento podrá además pasar por más de un modelo de IA
            (por ejemplo Claude y ChatGPT) para contrastar resultados y aumentar la confiabilidad del
            análisis.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.info(
        "La carga de documentos y el análisis automático todavía no están activos en esta "
        "pestaña. Esta vista explica el proceso completo que los sustentará.",
        icon=":material/construction:",
    )
