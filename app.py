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
        HF_TOKEN = "el token de Hugging Face que empieza con hf_..."
        GEMINI_API_KEY = "la key de Google AI Studio para el chat de Evaluador IA"

    HF_TOKEN (24-ago-2026): token de solo lectura de huggingface.co
    (Settings > Access Tokens, tipo "Read", gratis, sin tarjeta). Se usa
    para generar el vector de cada busqueda via la API de Hugging Face
    en vez de cargar el modelo de embeddings (~520MB) dentro de la app
    -- el plan gratis de Streamlit Cloud tiene ~1GB de RAM, y cargar el
    modelo localmente dejaba la app al borde del limite (medido: ~970MB
    de pico), causando reinicios frecuentes. Si HF_TOKEN no esta
    configurado, la app sigue funcionando pero vuelve a cargar el
    modelo local (mas lento y pesado) -- ver generar_embedding().

    GEMINI_API_KEY (24-ago-2026): key gratis de aistudio.google.com/apikey
    (sin tarjeta). Habilita el chat de la pestaña "Evaluador IA", que usa
    Gemini con function calling para consultar en vivo la base de
    observaciones (ver conectar_gemini() y las herramientas
    consultar_estadisticas_observaciones()/buscar_observaciones_relacionadas()).
    Si no esta configurado, esa pestaña sigue mostrando el resto del
    contenido pero el chat avisa que no esta disponible.

    Archivos que deben ir junto a este app.py en el repo:
        - logo-sugle.png
        - logo-sugle-claro.png (version del logo con texto en Lila,
          para que se lea sobre el fondo morado oscuro de la barra)
        - .streamlit/config.toml (con client.disableDataExport = true,
          para ocultar el boton de descarga CSV de las tablas)
        - temas_recurrentes.json (opcional -- si no esta, el Dashboard
          muestra un aviso en vez de fallar)
        - requirements.txt debe incluir: streamlit, supabase,
          fastembed, pandas, openpyxl, plotly, pyarrow, google-genai

Uso local:
    streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import base64
import json
import os
import re
import unicodedata
import urllib.request
from supabase import create_client, ClientOptions
from postgrest.exceptions import APIError
from google import genai
from google.genai import types as genai_types

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
        /* Bloquea el scroll de la PAGINA/ventana completa (html/body) --
        Streamlit ya arma el layout para que solo el panel de contenido
        ([data-testid="stMain"]) tenga su propio scroll interno, con el
        sidebar como un panel aparte de alto fijo (100vh). Pero en
        algunas ventanas/tamaños de pantalla, si el documento llega a
        medir mas alto que el viewport (por cualquier motivo), el
        NAVEGADOR agrega su propio scroll de pagina como respaldo -- y
        ESE si mueve todo junto, sidebar incluido (el bug reportado: la
        barra lateral "se iba" al hacer scroll en una tabla larga). Con
        esto, ese scroll de respaldo del navegador queda desactivado
        del todo, y solo puede scrollear el panel de contenido interno,
        como ya se veia en las pestañas cortas. */
        html, body {
            overflow: hidden !important;
        }
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

        /* Todos los iconos Material (:material/xxx: en botones, headers,
        captions, etc.) 20% mas grandes que el tamaño por defecto de
        Streamlit (24-ago-2026, pedido explicito) -- em relativo al tamaño
        heredado en cada contexto, no un px fijo, para que escale bien en
        cualquier lugar donde aparezca un icono. */
        [data-testid="stIconMaterial"] {
            font-size: 1.2em !important;
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
        /* padding-top chico + flex column de alto completo: asi el
        bloque de marca queda pegado arriba y el pie (.sigo-sidebar-footer,
        ver mas abajo) se puede empujar al fondo con margin-top:auto. */
        [data-testid="stSidebar"] > div {
            padding-top: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            box-sizing: border-box;
        }
        /* stSidebarHeader (la fila con la flechita de colapsar, arriba
        del todo) trae 60px de alto reservados por Streamlit aunque su
        contenido real (la flechita) ocupa bastante menos -- eso era lo
        que empujaba el grupo 1 (logo + SIGO) mas abajo de lo pedido. */
        [data-testid="stSidebarHeader"] {
            height: 34px !important;
            min-height: 34px !important;
            margin-bottom: 0 !important;
        }
        /* Cadena de flex completa hasta el pie: Streamlit mete AL MENOS
        un contenedor intermedio (stSidebarUserContent, y en algunas
        versiones tambien stVerticalBlockBorderWrapper) entre el div de
        arriba y el stVerticalBlock donde vive nuestro contenido. Si
        alguno de esos eslabones no es "display:flex" con "flex:1", el
        flex:1 de los que estan mas abajo no sirve de nada (un hijo no
        crece con flex:1 si su padre no es un contenedor flex) -- por
        eso el pie se quedaba pegado abajo del menu en vez de ir al
        fondo real del sidebar. Se marcan TODOS los eslabones posibles;
        el selector que no exista en esta version de Streamlit
        simplemente no matchea nada, sin romper nada. */
        [data-testid="stSidebarUserContent"],
        [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            display: flex;
            flex-direction: column;
            flex: 1;
            min-height: 0;
            padding-top: 0 !important;
        }
        /* stSidebarUserContent trae ademas 96px de padding-bottom por
        defecto de Streamlit (confirmado inspeccionando el computed
        style) -- era la causa real de que quedara un hueco grande
        entre el pie y el borde inferior real del sidebar, a pesar de
        que toda la cadena de flex ya estaba bien armada. */
        [data-testid="stSidebarUserContent"] {
            padding-bottom: 20px !important;
        }
        /* Este es el eslabon que faltaba (confirmado inspeccionando el
        HTML real que arma Streamlit): stSidebarUserContent envuelve
        stVerticalBlock en un div propio SIN data-testid, asi que ningun
        selector basado en testid lo alcanzaba -- se lo targetea por
        posicion (hijo directo de stSidebarUserContent). Sin este paso,
        el flex:1 de los eslabones de arriba y de abajo no servia de
        nada, porque un hijo no crece con flex:1 si el div que esta
        justo en el medio no es el tambien un contenedor flex. */
        [data-testid="stSidebarUserContent"] > div {
            display: flex;
            flex-direction: column;
            flex: 1;
            min-height: 0;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label {
            color: #E5DBEB;
        }
        /* Espacio extra ENTRE los 4 botones de navegacion (ademas del
        gap que ya trae Streamlit por defecto entre elementos). */
        [data-testid="stSidebar"] .stButton {
            margin-bottom: 10px;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
            text-align: left;
            justify-content: flex-start;
            border-radius: 8px;
            padding: 13px 16px;
            font-weight: 500;
            font-size: 1.05rem;
        }
        /* Streamlit envuelve el icono + la etiqueta de cada boton en un
        div propio adentro del <button>, que por defecto centra su
        contenido (justify-content: center) sin importar el
        justify-content que le pongamos al <button> de afuera -- por eso
        el texto se veia centrado en vez de en fila pegado a la
        izquierda. Se fuerza aca, en ese div interno directo. */
        [data-testid="stSidebar"] .stButton > button > div {
            justify-content: flex-start !important;
            width: 100%;
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
            gap: 12px;
            padding: 0 12px 20px 12px;
            margin-bottom: 48px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        }
        .sigo-sidebar-brand img {
            height: 42px;
        }
        .sigo-sidebar-brand .sigo-sidebar-titulo {
            font-weight: 700;
            font-size: 1.35rem;
            color: #FFFFFF;
            line-height: 1.15;
        }
        .sigo-sidebar-brand .sigo-sidebar-subtitulo {
            font-size: 0.76rem;
            color: #C6AFCB;
            line-height: 1.25;
            margin-top: 3px;
        }

        /* Pie del sidebar: se ancla al fondo via margin-top:auto en el
        contenedor directo que Streamlit genera para este st.markdown
        (localizado con :has(), sin importar cuantos divs intermedios
        agregue Streamlit) -- el .stVerticalBlock de arriba es el que le
        da el alto completo para que "auto" tenga margen de sobra donde
        empujar. Tamaño de texto SIN cambios a proposito (se pidio dejar
        este bloque como estaba, mientras el resto del sidebar crecia). */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > *:has(.sigo-sidebar-footer) {
            margin-top: auto;
        }
        .sigo-sidebar-footer {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 18px 12px 14px 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.12);
            /* Refuerzo ademas del margin-top:auto de arriba: sticky lo
            deja pegado al borde inferior real del sidebar aunque el
            margin-top:auto no llegue exacto al fondo (por ejemplo si
            queda algun padding heredado de Streamlit debajo). Necesita
            su propio fondo solido porque, al ser sticky, en algun
            momento del scroll queda "flotando" sobre el resto del
            contenido en vez de en su lugar normal en el flujo. */
            position: sticky;
            bottom: 0;
            background-color: #3F1840; /* Morado Vino, igual al sidebar */
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
            font-size: 1.75rem;
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

        /* Ticker de datos de IA (21-ago-2026): franja delgada -- mismo
        tamaño de letra que "Consultoría minero-ambiental" del pie del
        sidebar (0.72rem) -- pegada abajo del panel PRINCIPAL, SIEMPRE
        visible (no se va con el scroll ni desaparece en pestañas
        cortas). Se probaron primero position:sticky (se quedaba
        flotando en pestañas cortas, sin llegar al fondo real de la
        ventana) y position:fixed anclado a stMain via transform (no
        funciono: stMain es a la vez el que hace scroll Y el que
        ancla, asi que el ticker se iba con el resto del contenido al
        scrollear el Dashboard).

        Solucion: el ticker va fixed a TODA la ventana (left:0, ancho
        completo) pero en una capa (z-index) MAS BAJA que el sidebar
        -- como el sidebar tiene fondo solido opaco y llega hasta el
        borde inferior real (ver .sigo-sidebar-footer, mas arriba), lo
        tapa por completo en esa franja, sin tener que calcular a mano
        el ancho del sidebar (que ademas el usuario puede arrastrar
        para hacerlo mas angosto/ancho). El resultado visual es
        identico a si el ticker arrancara justo despues del sidebar. */
        /* SOLO z-index, sin tocar "position" -- Streamlit ya le pone su
        propio position (fixed) al sidebar para que se quede quieto
        mientras el panel principal hace scroll; pisarlo con
        "position: relative" (como se hizo en un intento anterior) lo
        volvia parte del flujo normal de la pagina y se iba de la
        pantalla al scrollear una tabla larga -- justo el bug reportado. */
        [data-testid="stSidebar"] {
            z-index: 10;
        }
        .sigo-ticker-wrap {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            width: 100%;
            height: 30px;
            overflow: hidden;
            background-color: #FFFFFF;
            border-top: 1px solid #E1D6E8;
            z-index: 5;
        }
        /* En la pestaña "Conversa con SIGO" hay ademas un st.chat_input
        fijo al fondo de la pantalla (widget nativo de Streamlit) -- sin
        este ajuste, el ticker (tambien fijo al fondo) queda tapado por
        ese cuadro. Se sube el ticker lo suficiente para que ambos se
        vean, uno encima del otro. */
        .sigo-ticker-wrap.sigo-ticker-sobre-chat {
            bottom: 68px;
        }
        /* Cuadro de "Pregúntale algo a SIGO..." (pestaña Conversa con
        SIGO): resaltado con el morado de marca en vez del gris por
        defecto de Streamlit, para que se note que es EL cuadro
        principal de la pagina. */
        [data-testid="stChatInput"] {
            border: 2px solid #A02671;
            border-radius: 14px;
            background-color: #FFFFFF;
            box-shadow: 0 2px 8px rgba(63, 24, 64, 0.12);
        }
        /* Para que el ticker (fixed) no tape la ultima fila de
        contenido de cada pestaña. */
        .block-container {
            padding-bottom: 2.5rem;
        }
        .sigo-ticker-track {
            display: inline-flex;
            align-items: center;
            height: 30px;
            white-space: nowrap;
            animation: sigo-ticker-desplazar 37.5s linear infinite; /* 2x mas rapido que el original (75s) */
        }
        .sigo-ticker-track .sigo-ticker-copia {
            padding-right: 3rem;
        }
        .sigo-ticker-item {
            font-size: 0.72rem;
            color: #6B5E71;
        }
        .sigo-ticker-item b {
            color: #A02671; /* Morado Barney */
        }
        .sigo-ticker-sep {
            margin: 0 1.4rem;
            color: #D9CCE3;
        }
        @keyframes sigo-ticker-desplazar {
            from { transform: translateX(0); }
            to { transform: translateX(-50%); }
        }
        /* Quieta para quien prefiera menos movimiento en pantalla. */
        @media (prefers-reduced-motion: reduce) {
            .sigo-ticker-track {
                animation: none;
            }
        }

        /* ------------------------------------------------------
        Ajustes responsivos para celular (21-ago-2026). Mismo diseño
        y estructura que en escritorio -- esto solo corrige lo que se
        corta/aprieta en una pantalla angosta. Streamlit ya colapsa el
        sidebar solo (boton "»") por debajo de este ancho, eso no hay
        que tocarlo.
        ------------------------------------------------------ */
        @media (max-width: 768px) {
            /* El ticker de datos de IA es decorativo -- en una pantalla
            chica ocupa demasiado espacio util, mejor ocultarlo del
            todo que achicarlo hasta ilegible. */
            .sigo-ticker-wrap {
                display: none;
            }
            /* Ya no hace falta el espacio extra abajo reservado para
            el ticker (ver mas arriba, .block-container padding-bottom
            2.5rem) si el ticker esta oculto. */
            .block-container {
                padding-bottom: 1rem;
            }
            /* Titulo/subtitulo a la izquierda + estadisticas a la
            derecha no entran uno al lado del otro en una pantalla
            angosta (las stats se cortaban) -- se apilan en columna. */
            .sigo-topbar {
                flex-direction: column;
            }
            .sigo-topbar-stats {
                text-align: left;
                white-space: normal;
            }
            /* Objetivos tactiles mas grandes (dedo en vez de mouse) en
            botones, inputs y desplegables. */
            .stButton > button,
            [data-testid="stForm"] button {
                padding-top: 12px;
                padding-bottom: 12px;
            }
            [data-testid="stTextInput"] input,
            [data-testid="stSelectbox"] > div > div {
                min-height: 44px;
            }
        }

        /* Barra de navegacion horizontal para celular (ver ES_MOVIL en
        el codigo Python -- st.container(key="sigo_mobile_nav")).
        Streamlit le agrega la clase "st-key-<key>" al contenedor solo
        por el "key" que se le paso, sin tener que adivinar ningun
        testid. Reusa la paleta morada del sidebar de escritorio para
        que se sienta la misma marca. */
        .st-key-sigo_mobile_nav {
            background-color: #3F1840;
            border-radius: 10px;
            padding: 0.5rem 0.4rem;
            margin-bottom: 1.2rem;
        }
        /* Streamlit apila st.columns en columna por debajo de cierto
        ancho (pensado para el contenido normal de la pagina) -- para
        ESTA barra puntual se fuerza que los 4 botones sigan siempre
        en una sola fila, aunque el telefono sea angosto (para eso son
        etiquetas cortas: "Buscar", "Consulta", etc.). min-width:0 es
        necesario para que cada columna se achique de verdad en vez de
        desbordar. */
        .st-key-sigo_mobile_nav [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap;
            gap: 0.3rem;
        }
        .st-key-sigo_mobile_nav [data-testid="stColumn"] {
            min-width: 0;
            flex: 1 1 0;
            width: auto !important;
        }
        .st-key-sigo_mobile_nav [data-testid="stIconMaterial"] {
            display: block;
            margin: 0 auto 2px auto;
        }
        .st-key-sigo_mobile_nav .stButton > button {
            flex-direction: column;
            gap: 2px;
            font-size: 0.68rem;
            padding: 8px 2px;
            border-radius: 8px;
        }
        .st-key-sigo_mobile_nav button[kind="secondary"] {
            background-color: transparent;
            border: none;
            color: #D9CCE3;
        }
        .st-key-sigo_mobile_nav button[kind="primary"] {
            background-color: rgba(255, 255, 255, 0.15);
            border: none;
            color: #FFFFFF;
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

        /* Fondo de los campos de texto (ej. el filtro de "Consulta
        General"): el gris por defecto de Streamlit casi no se notaba
        sobre el fondo lila clarito de la app (#F4F1F7, ver .stApp mas
        arriba) -- blanco solido para que contraste. */
        [data-testid="stTextInput"] input {
            background-color: #FFFFFF;
            border: 1px solid #D9CCE3;
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
def _leer_secreto(nombre):
    """st.secrets (secrets.toml) es el mecanismo de Streamlit Cloud. En
    otros hosts (ej. Hugging Face Spaces) las credenciales llegan como
    variables de entorno en vez de un secrets.toml -- se prueba
    st.secrets primero y se cae a os.environ si no esta disponible, asi
    el mismo codigo sirve para cualquiera de los dos sin cambios."""
    try:
        return st.secrets[nombre]
    except (FileNotFoundError, KeyError):
        return os.environ.get(nombre)


@st.cache_resource(show_spinner="Conectando a la base de datos...")
def conectar_supabase():
    url = _leer_secreto("SUPABASE_URL")
    key = _leer_secreto("SUPABASE_ANON_KEY")
    # Timeout explicito (20s por pedido): sin esto, si Supabase esta
    # lento o "dormido" (plan gratuito se pausa por inactividad), la
    # app se queda con el spinner de carga trabado indefinidamente en
    # vez de mostrar un error que se pueda reintentar.
    opciones = ClientOptions(postgrest_client_timeout=20)
    return create_client(url, key, options=opciones)


HF_INFERENCE_URL = (
    f"https://router.huggingface.co/hf-inference/models/{MODELO_EMBEDDING}/pipeline/feature-extraction"
)


@st.cache_resource(show_spinner="Cargando el modelo de busqueda semantica (primera vez tarda un poco)...")
def cargar_modelo_embeddings():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODELO_EMBEDDING)


def generar_embedding(texto):
    """Genera el vector de significado de una consulta de busqueda.

    Por defecto llama a la API gratuita de Hugging Face (mismo modelo,
    mismo mean pooling que los vectores ya guardados en Supabase --
    verificado 24-ago-2026, similitud 0.999999 contra el modelo local)
    en vez de cargar el modelo completo (~520MB de RAM) dentro de la
    app: el plan gratis de Streamlit Cloud tiene ~1GB, y cargar el
    modelo localmente deja la app al borde del limite (medido: ~970MB
    de pico con los datos + el modelo cargados a la vez), causando
    reinicios frecuentes por falta de memoria.

    Si la API no esta disponible (sin HF_TOKEN configurado, sin red, o
    un error del lado de Hugging Face), cae al modelo local como
    respaldo -- mas lento y pesado, pero la busqueda sigue funcionando
    en vez de romperse del todo."""
    token = _leer_secreto("HF_TOKEN")
    if token:
        try:
            cuerpo = json.dumps({"inputs": texto}).encode("utf-8")
            peticion = urllib.request.Request(
                HF_INFERENCE_URL,
                data=cuerpo,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(peticion, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception:
            pass  # cae al modelo local abajo

    modelo = cargar_modelo_embeddings()
    return list(modelo.embed([texto]))[0].tolist()


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


def etiqueta_relevancia(score_texto, score_semantico):
    """Traduce los puntajes tecnicos de la busqueda hibrida (similitud
    coseno, ts_rank, RRF) a UNA sola etiqueta simple, pensada para
    alguien sin conocimientos de IA (24-ago-2026: antes se mostraban
    los 3 numeros crudos, ej. "relevancia semantica: 0.564", que no le
    decian nada a nadie fuera de contexto tecnico).

    No se muestra el coseno ni el RRF tal cual porque ninguno de los
    dos es un porcentaje interpretable: el coseno de estos modelos
    tiene un "piso" alto incluso para texto NO relacionado (por eso
    buscar_hibrido ya exige un minimo de 0.55 antes de mostrar un
    resultado puramente semantico -- ver esa funcion en Supabase), y el
    RRF es una escala de orden/ranking, no de confianza.

    El porcentaje que se muestra aca es solo una referencia intuitiva
    (reescala el rango 0.55-0.85 observado en pruebas a 50-99%), no una
    probabilidad estadistica real."""
    if score_texto:
        return ":material/search: Coincide con el texto exacto de tu búsqueda"
    if score_semantico is not None:
        porcentaje = round(50 + (score_semantico - 0.55) / (0.85 - 0.55) * 49)
        porcentaje = max(50, min(99, porcentaje))
        nivel = "Alta" if score_semantico >= 0.65 else "Media"
        return f":material/psychology: Relevancia por significado: {nivel} (~{porcentaje}%)"
    return None


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


# Ticker del proceso "¿Como llegamos hasta aca?" (franja inferior del
# panel principal, ver .sigo-ticker-wrap en el CSS). Antes mostraba
# datos de adopcion de IA en empresas (Deloitte/McKinsey/MIT NANDA);
# 24-ago-2026 se reemplazo por el resumen de los 7 pasos con los que se
# construyo la base -- el mismo contenido que antes vivia solo en la
# pestaña "Evaluador IA", ahora visible desde cualquier pestaña.
DATOS_PROCESO_TICKER = [
    ("1. Descarga histórica", "expedientes ITS evaluados por SENACE a lo largo de los años, con miles de observaciones reales"),
    ("2. Discriminación y depuración", "cada observación clasificada por especialidad, descartando registros incompletos o duplicados"),
    ("3. Extracción y estructuración", "información estructurada en una base tabular: expediente, empresa, especialidad, fundamento y observación"),
    ("4. Normalización", "texto normalizado y vectores de significado (IA) generados para habilitar búsqueda por texto y por significado"),
    ("5. Base de datos limpia y clasificada", "20 515 observaciones históricas, consultables en segundos desde la pestaña de Búsqueda"),
    ("6. Análisis de tendencias", "se identificó qué TIPO de hallazgo es más frecuente en la historia de SENACE"),
    ("7. Análisis de severidad", "cada observación clasificada como DE FONDO o DE FORMA, cruzado por especialidad"),
]


def _render_ticker_proceso():
    """Franja inferior del panel principal con el resumen de como se
    construyo la base (los mismos 7 pasos de la pestaña "Evaluador IA"),
    en scroll horizontal continuo (CSS puro, sin JS) -- se llama una
    sola vez al final del script, fuera del if/elif de paginas, para
    que aparezca en las 5 pestañas."""
    item_html = "".join(
        f'<span class="sigo-ticker-item"><b>{titulo}:</b> {dato}</span><span class="sigo-ticker-sep">•</span>'
        for titulo, dato in DATOS_PROCESO_TICKER
    )
    # En "conversa" hay ademas un st.chat_input fijo al fondo -- se sube
    # el ticker con una clase extra para que no quede tapado (ver CSS
    # ".sigo-ticker-wrap.sigo-ticker-sobre-chat").
    clase_extra = " sigo-ticker-sobre-chat" if st.session_state.sigo_pagina == "conversa" else ""
    st.markdown(
        f"""
        <div class="sigo-ticker-wrap{clase_extra}">
            <div class="sigo-ticker-track">
                <span class="sigo-ticker-copia">{item_html}</span>
                <span class="sigo-ticker-copia">{item_html}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


@st.cache_data(show_spinner=False, ttl=600)
def cargar_objetivos_its(_supabase):
    """Trae expediente + categorias de la tabla objetivos_its (24-ago-2026,
    clasificacion por componente de la operacion minera que modifica
    cada objetivo -- ver migracion clasificar_objetivos_its_por_componente
    en Supabase). Solo se usa para el grafico del Dashboard, por eso no
    trae la columna 'objetivo' completa (mas liviano)."""
    filas = []
    inicio = 0
    LOTE = 1000
    while True:
        resp = (
            _supabase.table("objetivos_its")
            .select("expediente,categorias")
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

    return pd.DataFrame(filas)


# ---------------------------------------------------------
# Chat "Evaluador IA" (Gemini + function calling sobre Supabase)
# ---------------------------------------------------------
# Version verificada probando en vivo el 24-ago-2026 (mas confiable que la
# doc: "gemini-2.5-flash" ya daba 404 "no longer available to new users",
# y "gemini-3.7-flash" -el que la doc marcaba como ultimo estable- daba 503
# "high demand" de forma repetida). "gemini-3.6-flash" es el que la propia
# API recomienda en el mensaje de error del 404, y respondio bien en las
# pruebas. Si vuelve a fallar, revisar cual es el modelo Flash gratis
# vigente en ese momento (cambian seguido).
MODELO_GEMINI = "gemini-3.6-flash"


@st.cache_resource(show_spinner=False)
def conectar_gemini():
    api_key = _leer_secreto("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


# Las funciones de abajo son las UNICAS herramientas que el modelo puede
# invocar -- nunca ejecuta SQL libre. Ambas son de solo lectura, usan el
# mismo cliente "supabase" (anon key, RLS de solo-lectura) y el mismo
# camino ya auditado de la pestaña de Busqueda (generar_embedding +
# buscar_hibrido), y devuelven texto resumido y acotado (no el JSON crudo)
# para no gastar de mas la cuota gratis de tokens de Gemini.

def consultar_estadisticas_observaciones(especialidad: str = "", empresa: str = "", coordinador: str = "") -> str:
    """Cuenta cuantas observaciones historicas de SENACE hay en la base,
    opcionalmente filtrando por especialidad, empresa o evaluador. Usar
    para preguntas tipo "cuantas observaciones tiene la empresa X" o
    "cuantas observaciones de especialidad Y hay en total".

    Args:
        especialidad: Especialidad exacta (Fisico, Biologico, Social, Legal,
            Descripcion de Proyectos, Sig, Esp. Legal, entre otras). Vacio
            para no filtrar por especialidad.
        empresa: Nombre (o parte del nombre) de la empresa/titular minero.
            Vacio para no filtrar por empresa.
        coordinador: Nombre (o parte del nombre) del evaluador de SENACE.
            Vacio para no filtrar por evaluador.

    Returns:
        Texto con el total de observaciones que cumplen el filtro pedido.
    """
    consulta = supabase.table("observaciones").select("id", count="exact")
    if especialidad:
        # ilike + quitar_tildes (no un match exacto): la base guarda las
        # especialidades SIN tilde (ej. "Fisico"), pero el modelo a veces
        # las escribe con tilde ("Físico") -- sin esto, fallaba en el
        # primer intento y gastaba varias llamadas de mas reintentando
        # variantes (24-ago-2026, confirmado probando en vivo: 6 llamadas
        # a herramientas para UNA sola pregunta, agotando la cuota
        # gratis de Gemini de 5 solicitudes/minuto).
        consulta = consulta.ilike("especialidad_final", quitar_tildes(especialidad))
    if empresa:
        consulta = consulta.ilike("empresa", f"%{empresa}%")
    if coordinador:
        consulta = consulta.ilike("coordinador", f"%{coordinador}%")
    resultado = consulta.execute()
    total = resultado.count or 0

    filtros = [f"{nombre}={valor}" for nombre, valor in
               [("especialidad", especialidad), ("empresa", empresa), ("coordinador", coordinador)] if valor]
    if filtros:
        return f"{total} observaciones encontradas con filtro ({', '.join(filtros)})."
    return f"{total} observaciones en total en la base de datos."


def buscar_observaciones_relacionadas(tema: str, especialidad: str = "", top_k: int = 5) -> str:
    """Busca observaciones historicas de SENACE relacionadas a un tema o
    palabra clave (busqueda hibrida: texto exacto + significado). Usar para
    preguntas tipo "que dice SENACE sobre bofedales" o "que observaciones
    hay de calidad de aire".

    Args:
        tema: Tema, palabra o frase a buscar (ej. "bofedal impacto",
            "calidad de aire").
        especialidad: Especialidad exacta para acotar la busqueda (opcional,
            vacio para no filtrar).
        top_k: Cantidad de resultados a traer, entre 1 y 10.

    Returns:
        Texto con un resumen de cada resultado (expediente, especialidad,
        fragmento de la observacion).
    """
    top_k = max(1, min(10, top_k))
    vector_consulta = generar_embedding(tema)
    resultado = supabase.rpc("buscar_hibrido", {
        "consulta_texto": tema,
        "consulta_vector": vector_a_texto_postgres(vector_consulta),
        "filtro_especialidad": especialidad or None,
        "cantidad": top_k,
    }).execute()
    filas = resultado.data or []
    if not filas:
        return f'No se encontraron observaciones relacionadas a "{tema}".'

    resumen = [f'Resultados para "{tema}" ({len(filas)}):']
    for i, fila in enumerate(filas, 1):
        obs = (fila.get("observacion") or "")[:280]
        resumen.append(
            f"{i}. Expediente {fila.get('expediente', '?')} | "
            f"{fila.get('especialidad_final', 'Sin clasificar')} | {obs}"
        )
    return "\n".join(resumen)


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
# Deteccion de celular (21-ago-2026) -- via el header HTTP User-Agent
# real del navegador (st.context, disponible desde Streamlit 1.37),
# NO por ancho de ventana. A proposito: la tabla de Consulta General
# es un grid tipo canvas (glide-data-grid) -- no se le pueden ocultar
# columnas con CSS, hace falta decidir en Python (via column_order)
# que columnas mandarle, y eso solo se puede hacer sabiendo de
# antemano si es un telefono real o una ventana de escritorio angosta.
# ---------------------------------------------------------
def _detectar_movil():
    try:
        ua = (st.context.headers.get("User-Agent") or "").lower()
    except Exception:
        return False
    return any(clave in ua for clave in ("mobile", "android", "iphone"))


ES_MOVIL = _detectar_movil()

# ---------------------------------------------------------
# Navegacion (21-ago-2026): sidebar tipo SaaS en escritorio, barra
# horizontal arriba del contenido en celular (ver ES_MOVIL). La pagina
# activa se guarda en session_state para sobrevivir los reruns que
# dispara Streamlit en cada interaccion. Iconos Material Symbols
# (nativos de Streamlit, sin depender de un CDN externo).
# etiqueta_corta se usa solo en la barra de celular (4 botones en una
# fila angosta no entran con el nombre completo de escritorio).
PAGINAS_SIGO = [
    ("conversa", ":material/forum:", "Conversa con SIGO", "Chat"),
    ("busqueda", ":material/search:", "Búsqueda de Observaciones", "Buscar"),
    ("consulta", ":material/table_view:", "Consulta General", "Consulta"),
    ("dashboard", ":material/bar_chart:", "Dashboard & Métricas", "Panel"),
    ("evaluador", ":material/psychology:", "Evaluador IA", "Evaluar"),
]
if "sigo_pagina" not in st.session_state:
    st.session_state.sigo_pagina = "conversa"

if ES_MOVIL:
    # Barra horizontal de navegacion, arriba del todo del panel
    # principal -- reemplaza el sidebar (que en celular quedaria
    # escondido detras de un boton, una interaccion de mas que no
    # aporta en una demo rapida desde el telefono).
    with st.container(key="sigo_mobile_nav"):
        _cols_nav = st.columns(len(PAGINAS_SIGO))
        for _col, (_clave, _icono, _etiqueta, _etiqueta_corta) in zip(_cols_nav, PAGINAS_SIGO):
            with _col:
                _es_activa = st.session_state.sigo_pagina == _clave
                if st.button(
                    _etiqueta_corta,
                    key=f"nav_m_{_clave}",
                    icon=_icono,
                    type="primary" if _es_activa else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.sigo_pagina = _clave
                    st.rerun()
else:
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
        for _clave, _icono, _etiqueta, _etiqueta_corta in PAGINAS_SIGO:
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

if not ES_MOVIL:
    st.markdown('<div class="sigo-firma">jlya</div>', unsafe_allow_html=True)

# La pantalla de carga a pantalla completa solo se muestra en la
# PRIMERA carga real de la sesion del navegador -- Streamlit re-ejecuta
# este script completo en cada clic (buscar, cambiar de pestaña,
# filtrar), y conectar_supabase()/cargar_datos_supabase() ya estan en
# cache (instantaneos) en esos reruns posteriores. Sin esta bandera, el
# overlay se disparaba en CADA interaccion, no solo al abrir la app --
# eso era el "se borra toda la pantalla" reportado.
_es_primera_carga = "sigo_datos_cargados" not in st.session_state

if _es_primera_carga:
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
    if _es_primera_carga:
        datos = cargar_datos_supabase(supabase)
    else:
        # No es la primera carga: en el caso normal (cache vigente) esto
        # es instantaneo. Si el cache vencio (ttl=600) o el recurso se
        # reinicio, se ve un spinner chico en vez del overlay completo --
        # sigue habiendo feedback, pero sin el borrado de pantalla.
        with st.spinner("Actualizando datos..."):
            datos = cargar_datos_supabase(supabase)
except Exception as e:
    if _es_primera_carga:
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

if _es_primera_carga:
    _placeholder_carga.empty()
    st.session_state["sigo_datos_cargados"] = True

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
    "conversa": (
        "Conversa con SIGO",
        "Chat sobre la base histórica de observaciones SENACE",
    ),
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
# Orden pensado para quien revisa la base completa: primero el
# contenido del hallazgo (fundamento, observacion), despues la
# categoria/tema, y recien despues los metadatos de ubicacion
# (expediente, empresa, etc.) de mayor a menor relevancia. Subsanacion
# se dejo FUERA de la vista por defecto (queda disponible con el icono
# de "ojo" de la tabla) porque esta vacia/incompleta en muchas filas.
COLUMNAS_POR_DEFECTO = [
    "N", "Fundamento", "Observacion",
    "Expediente", "Empresa", "Coordinador", "Titulo Proyecto", "Fecha",
    "Informe", "Unidad Proyecto",
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
# PÁGINA: CONVERSA CON SIGO (chat con Gemini sobre la base historica)
# ---------------------------------------------------------
if st.session_state.sigo_pagina == "conversa":
    cliente_gemini = conectar_gemini()
    if cliente_gemini is None:
        st.caption(
            "El chat todavía no está disponible en este entorno (falta configurar "
            "GEMINI_API_KEY). Se consigue gratis, sin tarjeta, en "
            "aistudio.google.com/apikey."
        )
    else:
        if "sigo_chat_gemini_sesion" not in st.session_state:
            st.session_state["sigo_chat_gemini_sesion"] = cliente_gemini.chats.create(
                model=MODELO_GEMINI,
                config=genai_types.GenerateContentConfig(
                    system_instruction=(
                        "Eres el asistente de SIGO, la herramienta de control de calidad de "
                        "Sugle S.A.C. Respondes preguntas sobre la base histórica de "
                        "observaciones que SENACE ha hecho a estudios ITS de proyectos "
                        "mineros en Perú. Cuando la pregunta pida un dato concreto (cantidad, "
                        "ejemplos, contenido de observaciones), usa SIEMPRE las herramientas "
                        "disponibles para consultar la base real -- nunca inventes cifras ni "
                        "observaciones que no vengan de una herramienta. Las especialidades "
                        "que existen en la base son: Fisico, Biologico, Social, Legal, "
                        "Descripcion de Proyectos, Sig, entre otras. Responde en español, de "
                        "forma breve y concreta."
                    ),
                    tools=[consultar_estadisticas_observaciones, buscar_observaciones_relacionadas],
                ),
            )
        if "sigo_chat_gemini_historial" not in st.session_state:
            st.session_state["sigo_chat_gemini_historial"] = []

        # Contenedor con borde visible (24-ago-2026, pedido explicito:
        # "resalta mas el cuadro donde se chatea") -- sin esto los
        # mensajes flotaban sueltos sobre el fondo de la app, sin ningun
        # limite visual que marcara "esto es el chat".
        contenedor_chat = st.container(height=420, border=True)
        with contenedor_chat:
            for mensaje in st.session_state["sigo_chat_gemini_historial"]:
                with st.chat_message(mensaje["rol"]):
                    st.markdown(mensaje["texto"])

        pregunta = st.chat_input("Pregúntale algo a SIGO sobre la base histórica...")
        if pregunta:
            st.session_state["sigo_chat_gemini_historial"].append({"rol": "user", "texto": pregunta})
            with contenedor_chat:
                with st.chat_message("user"):
                    st.markdown(pregunta)

                with st.chat_message("assistant"):
                    with st.spinner("Consultando la base..."):
                        try:
                            respuesta = st.session_state["sigo_chat_gemini_sesion"].send_message(pregunta)
                            texto_respuesta = respuesta.text or "No pude generar una respuesta."
                        except Exception as e:
                            texto_respuesta = (
                                "No se pudo consultar a Gemini en este momento (puede ser el "
                                f"límite del plan gratis). Detalle técnico: `{e}`"
                            )
                    st.markdown(texto_respuesta)
            st.session_state["sigo_chat_gemini_historial"].append({"rol": "assistant", "texto": texto_respuesta})

        st.caption(
            ":material/info: Corre sobre el plan gratis de Gemini (límite de solicitudes por "
            "minuto/día) -- si tarda o falla, espera unos segundos y vuelve a intentar."
        )

# ---------------------------------------------------------
# PÁGINA: BÚSQUEDA HÍBRIDA (Supabase + IA)
# ---------------------------------------------------------
elif st.session_state.sigo_pagina == "busqueda":

    # Opciones del desplegable de especialidad, sacadas directamente de
    # df_all (ya cargado desde Supabase mas arriba) -- asi la lista
    # siempre refleja los valores reales de la base, sin mantenerla a
    # mano.
    OPCION_TODAS_ESP = "(Todas)"
    OPCION_TODOS_OBJ = "(Todos)"
    opciones_especialidad = [OPCION_TODAS_ESP] + (
        sorted(df_all['Especialidad Final'].dropna().unique().tolist())
        if 'Especialidad Final' in df_all.columns else []
    )
    # Categorias de objetivos_its (24-ago-2026, clasificacion por
    # componente de la operacion minera -- ver migracion
    # clasificar_objetivos_its_por_componente en Supabase). Lista fija
    # en vez de sacarla de la base: son las mismas 15 categorias que
    # define esa clasificacion, no van a cambiar salvo que se reclasifique.
    CATEGORIAS_OBJETIVO_ITS = [
        "Planta de procesos", "Componentes auxiliares", "Manejo de aguas",
        "Deposito de relaves", "Plataformas de perforacion / exploracion",
        "Accesos / vias", "Mina / tajo / labores subterraneas",
        "Deposito de desmonte / material esteril", "Energia electrica",
        "Cronograma / plazo", "Monitoreo ambiental", "Residuos solidos",
        "Canteras / material de prestamo", "Precision / aclaracion (sin cambio fisico)",
        "Otros",
    ]
    opciones_objetivo = [OPCION_TODOS_OBJ] + CATEGORIAS_OBJETIVO_ITS

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
            objetivo_filtro = st.selectbox(
                "Filtrar por Objetivo del ITS (opcional):",
                options=opciones_objetivo,
            )

        buscar = st.form_submit_button(
            "Buscar Observaciones",
            type="primary",
            icon=":material/search:",
            use_container_width=True,
        )

    especialidad_valor = None if especialidad_filtro == OPCION_TODAS_ESP else especialidad_filtro
    objetivo_valor = None if objetivo_filtro == OPCION_TODOS_OBJ else objetivo_filtro

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
                vector_consulta = generar_embedding(query)

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
                        "filtro_categoria_objetivo": objetivo_valor,
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
                        "filtro_categoria_objetivo": objetivo_valor,
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

                st.caption(":material/speed: Relevancia por significado — 0% muy bajo, 100% muy alto")

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

                    titulo_resultado = f"Resultado #{i} | Expediente: {exp}" + (f" | Evaluador: {coordinador}" if coordinador else "")
                    with st.expander(titulo_resultado, icon=":material/push_pin:"):
                        etiquetas = []
                        if especialidad:
                            etiquetas.append(f":material/label: {especialidad}")
                        if coordinador:
                            etiquetas.append(f":material/person: {coordinador}")
                        if item:
                            etiquetas.append(f":material/location_on: {item}")
                        _etiqueta_rel = etiqueta_relevancia(score_texto, score_semantico)
                        if _etiqueta_rel:
                            etiquetas.append(_etiqueta_rel)
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
    if ES_MOVIL:
        # En celular, una tabla ancha con muchas columnas obliga a
        # scrollear horizontal con el dedo, incomodo -- se manda solo
        # la columna con el contenido real (esto SI hay que decidirlo
        # en Python: la tabla es un grid tipo canvas, no se le pueden
        # ocultar columnas con CSS como al resto de la pagina).
        orden_columnas = [c for c in ["Observacion"] if c in df_mostrar.columns]
    else:
        orden_columnas = [c for c in COLUMNAS_POR_DEFECTO if c in df_mostrar.columns]
    # Alto fijo pensado para que el titulo + filtro + tabla completa
    # entren en una pantalla normal SIN que aparezca la barra de
    # desplazamiento del panel principal (la tabla igual tiene SU
    # PROPIO scroll interno para recorrer las 20 mil filas, eso es
    # aparte y no se puede quitar). 35px por fila + 38px de encabezado,
    # ajustado a mano para que se vean ~13 filas completas.
    FILAS_VISIBLES_TABLA = 13
    ALTO_TABLA = 38 + FILAS_VISIBLES_TABLA * 35
    _config_columnas = {"Especialidad Final": st.column_config.Column(label="Especialidad")}
    if ES_MOVIL:
        # Sin esto, "Observacion" (unica columna visible en celular)
        # se queda con su ancho angosto de siempre y el texto se corta
        # -- hay que pedirle explicitamente que ocupe todo el ancho.
        _config_columnas["Observacion"] = st.column_config.Column(width="large")
    st.dataframe(
        df_mostrar,
        use_container_width=True,
        height=ALTO_TABLA,
        column_order=orden_columnas,
        # El indice numerico de pandas (la columna sin titulo, a la
        # izquierda del todo) no sirve de nada aca -- la columna "N"
        # real de la base ya cumple ese rol y va primera en el orden
        # de arriba, asi que el indice se apaga del todo.
        hide_index=True,
        # Solo cambia la ETIQUETA visible de la columna -- el nombre
        # real ("Especialidad Final") no se toca, porque el Dashboard
        # y el filtro de Busqueda siguen usandolo tal cual. Se deja
        # configurado por si el usuario la vuelve a prender con el
        # icono de "ojo" (esta fuera de COLUMNAS_POR_DEFECTO).
        column_config=_config_columnas,
    )

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

    st.markdown("---")
    st.markdown("**Objetivos de los ITS por componente modificado**")
    df_objetivos = cargar_objetivos_its(supabase)
    if df_objetivos is None:
        st.caption(
            "Todavía no se cargó la tabla objetivos_its. Corre `python cargar_objetivos_its.py` "
            "para subir la matriz de objetivos a Supabase."
        )
    else:
        df_obj_cat = df_objetivos.explode("categorias")
        conteo_obj_cat = df_obj_cat["categorias"].value_counts().reset_index()
        conteo_obj_cat.columns = ["Categoria", "Cantidad"]
        fig_obj = px.bar(
            conteo_obj_cat.sort_values("Cantidad"),
            x="Cantidad",
            y="Categoria",
            orientation="h",
            color="Cantidad",
            color_continuous_scale="Purples",
        )
        fig_obj.update_layout(showlegend=False, yaxis_title="Categoría", xaxis_title="Cantidad de objetivos", height=450)
        aplicar_fondo_marca(fig_obj)
        st.plotly_chart(fig_obj, use_container_width=True)
        st.caption(
            f"Basado en {df_objetivos['expediente'].nunique():,} expedientes y "
            f"{len(df_objetivos):,} objetivos. Un mismo objetivo puede modificar más de un "
            "componente a la vez (ej. una planta de tratamiento de aguas cuenta tanto en "
            "\"Manejo de aguas\" como en \"Planta de procesos\"), por eso la suma supera el "
            "total de objetivos. \"Otros\" agrupa objetivos muy específicos sin un patrón "
            "temático claro (viveros, laboratorios, sistemas de dosificación química, etc.)."
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
        "pestaña. Mientras tanto, ve a \"Conversa con SIGO\" en el menú para preguntarle "
        "sobre la base histórica de observaciones. Más abajo puedes ver todo el proceso "
        "con el que se construyó esta base.",
        icon=":material/construction:",
    )

# ---------------------------------------------------------
# Ticker del proceso "¿Como llegamos hasta aca?" -- fuera del if/elif
# de arriba a proposito, para que se renderice al final de CUALQUIER
# pagina (siempre es lo ultimo que se dibuja, pegado abajo del panel
# principal). Se salta del todo en celular (ES_MOVIL): es decorativo,
# y en una pantalla chica quita espacio util que en escritorio sobra.
# ---------------------------------------------------------
if not ES_MOVIL:
    _render_ticker_proceso()
