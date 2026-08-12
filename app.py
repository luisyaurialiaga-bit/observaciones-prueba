import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import unicodedata

# Configuración de la página
st.set_page_config(
    page_title="Sistema ITS SENACE",
    page_icon="🛡️",
    layout="wide"
)

PARQUET_PATH = "observaciones_clasificadas_FINAL_v33.parquet"
EXCEL_PATH = "observaciones_clasificadas_FINAL_v33.xlsx"


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
    Probado contra 300 textos reales sin generar cortes falsos.
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

    Se prioriza la variante CON MAS TILDES (normalmente la ortografia
    correcta), y solo se usa la frecuencia como desempate cuando dos
    variantes tienen la misma cantidad de tildes (ej. diferencias de
    mayusculas/minusculas). Esto evita que una version mal escrita pero
    mas repetida (ej. 'IBAN' sin tilde, si aparece mas veces que 'IBÁN')
    termine ganando por sobre la version correcta.
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
    """
    Parsea fechas con formato tipo 'San Isidro, 07 de mayo de 2026' o
    'Lima, 09 de febrero de 2022' (el nombre de la ciudad varia y se
    ignora). pd.to_datetime no entiende este formato en español, por eso
    se usa un parser propio.
    """
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



@st.cache_data(show_spinner="Cargando base de datos...")
def cargar_datos():
    if os.path.exists(PARQUET_PATH):
        df = pd.read_parquet(PARQUET_PATH)
    elif os.path.exists(EXCEL_PATH):
        df = pd.read_excel(EXCEL_PATH)
    else:
        return None

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

    # Unificar variantes del mismo nombre (con/sin tilde, mayus/minus) que
    # antes se contaban como personas distintas.
    mask_asignado = df['Coordinador'] != 'Sin Asignar'
    if mask_asignado.any():
        df.loc[mask_asignado, 'Coordinador'] = normalizar_nombres(df.loc[mask_asignado, 'Coordinador'])

    for col in ['Expediente', 'Especialidad Final', 'Empresa', 'Titulo Proyecto']:
        if col in df.columns:
            df[col] = df[col].fillna('Sin información').astype(str).str.strip()
            # Tambien normalizamos nombres de empresa por la misma razon
            if col == 'Empresa':
                mask_emp = df[col] != 'Sin información'
                if mask_emp.any():
                    df.loc[mask_emp, col] = normalizar_nombres(df.loc[mask_emp, col])

    return df, col_obs


# Encabezado Principal
st.title("🛡️ Sistema de Control de Calidad & Inteligencia ITS SENACE")
st.caption("Matriz de Observaciones Clasificadas - Base Histórica Normalizada")

datos = cargar_datos()

if datos is None:
    st.error(f"⚠️ No se encontró '{PARQUET_PATH}' ni '{EXCEL_PATH}' en la raíz del repositorio. Por favor asegúrate de subir alguno a GitHub.")
    st.stop()

df_all, col_obs = datos

tab1, tab2, tab3 = st.tabs(["🔍 Búsqueda de Observaciones", "📋 Consulta General", "📊 Dashboard Completo & Métricas"])

# ---------------------------------------------------------
# PESTAÑA 1: BÚSQUEDA DE OBSERVACIONES
# ---------------------------------------------------------
with tab1:
    st.header("Búsqueda Avanzada de Observaciones")
    query = st.text_input("Ingrese la consulta o temática a buscar:", placeholder="Ej: bofedal impacto, calidad de aire, plan de participacion ciudadana...")

    col1, col2 = st.columns([1, 2])
    with col1:
        top_k = st.slider("Cantidad de resultados:", min_value=5, max_value=50, value=10)

    lista_especialidades = ["Todas"] + sorted([e for e in df_all['Especialidad Final'].dropna().unique() if e])

    with col2:
        especialidad_filtro = st.selectbox("Filtrar por Especialidad:", lista_especialidades)

    if st.button("Buscar Observaciones", type="primary"):
        if query.strip():
            # Busqueda por palabras: TODAS las palabras ingresadas deben
            # aparecer (en cualquier orden), no la frase exacta completa.
            # Ej: "bofedal impacto" encuentra observaciones que mencionen
            # ambas palabras, aunque esten separadas en el texto.
            palabras = [p for p in query.strip().split() if p]

            texto_busqueda = df_all[col_obs].fillna('')
            if 'Fundamento' in df_all.columns:
                # Tambien se busca en el Fundamento, porque a veces el
                # termino buscado aparece ahi y no literalmente en la
                # Observacion.
                texto_busqueda = texto_busqueda + ' ' + df_all['Fundamento'].fillna('')

            mask = pd.Series(True, index=df_all.index)
            for palabra in palabras:
                mask = mask & texto_busqueda.str.contains(re.escape(palabra), case=False, na=False)

            if especialidad_filtro != "Todas":
                mask = mask & (df_all['Especialidad Final'] == especialidad_filtro)

            total_encontradas = mask.sum()
            df_res = df_all[mask].head(top_k)

            if not df_res.empty:
                if total_encontradas > len(df_res):
                    st.success(f"Se encontraron **{total_encontradas}** observaciones en total — mostrando las primeras {len(df_res)}:")
                else:
                    st.success(f"Se encontraron **{total_encontradas}** observaciones en total:")

                # Desglose por especialidad de TODAS las coincidencias (no
                # solo las que se muestran), para ver de un vistazo donde
                # se concentra el tema buscado. Solo tiene sentido cuando
                # no se filtro ya por una especialidad especifica.
                if especialidad_filtro == "Todas" and 'Especialidad Final' in df_all.columns:
                    conteo_especialidad = df_all.loc[mask, 'Especialidad Final'].value_counts()
                    resumen = " &nbsp;|&nbsp; ".join(
                        f"{esp} ({cant})" for esp, cant in conteo_especialidad.items()
                    )
                    st.caption(f"Por especialidad: {resumen}")

                for idx, row in df_res.reset_index().iterrows():
                    num_res = idx + 1
                    exp = row.get('Expediente', 'Sin información')
                    coord = row.get('Coordinador', 'Sin Asignar')
                    proyecto = row.get('Titulo Proyecto', row.get('Proyecto', 'Sin información'))
                    empresa = row.get('Empresa', 'Sin información')
                    obs_texto = row.get(col_obs, 'Sin detalle')
                    fundamento = valor_o_vacio(row.get('Fundamento'))
                    subsanacion = valor_o_vacio(row.get('Subsanacion'))
                    item = valor_o_vacio(row.get('Item'))
                    especialidad = valor_o_vacio(row.get('Especialidad Final'))
                    fecha = valor_o_vacio(row.get('Fecha'))
                    tipo_matriz = valor_o_vacio(row.get('Tipo Matriz'))
                    informe = valor_o_vacio(row.get('Informe'))
                    pagina = valor_o_vacio(row.get('Pagina'))
                    tiene_imagen = valor_o_vacio(row.get('Tiene Imagen')).upper() == 'SI'

                    with st.expander(f"📌 Resultado #{num_res} | Expediente: {exp} | Evaluador: {coord}"):
                        # Etiquetas rapidas de contexto
                        etiquetas = []
                        if especialidad:
                            etiquetas.append(f"🏷️ {especialidad}")
                        if tipo_matriz:
                            etiquetas.append(f"📑 {tipo_matriz}")
                        if fecha:
                            etiquetas.append(f"📅 {fecha}")
                        if item:
                            etiquetas.append(f"📍 {item}")
                        if tiene_imagen:
                            etiquetas.append("🖼️ Con plano/figura")
                        if etiquetas:
                            st.caption(" &nbsp;|&nbsp; ".join(etiquetas))

                        st.markdown(f"**Proyecto:** {proyecto}")
                        st.markdown(f"**Empresa:** {empresa}")
                        st.markdown("---")

                        if fundamento:
                            st.markdown(f"**⚖️ Fundamento / Sustento legal:**\n\n{formatear_parrafos(fundamento)}")
                            st.markdown("")

                        st.markdown(f"**Observación:**\n\n{formatear_parrafos(str(obs_texto))}")

                        if subsanacion:
                            st.markdown("")
                            st.markdown(f"**✅ Cómo se subsanó:**\n\n{formatear_parrafos(subsanacion)}")

                        # Referencia citable: numero de Informe oficial + pagina,
                        # NO el nombre de archivo (los PDFs de SENACE traen nombres
                        # como 'signed_signed_signed_..._stamped_Informe-...pdf',
                        # inservibles para mostrar).
                        if informe:
                            ref_pagina = f" — página {pagina}" if pagina else ""
                            st.caption(f"Fuente: {informe}{ref_pagina}")
                        elif pagina:
                            st.caption(f"Fuente: página {pagina} del informe")
            else:
                st.info("No se encontraron observaciones que coincidan con la búsqueda.")
        else:
            st.warning("Por favor ingrese un texto de consulta.")

# ---------------------------------------------------------
# PESTAÑA 2: CONSULTA GENERAL
# ---------------------------------------------------------
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

    st.dataframe(df_mostrar, use_container_width=True, height=600)

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
                st.plotly_chart(fig_hm, use_container_width=True)
            else:
                st.caption("No hay suficientes datos cruzados para mostrar.")

    with col_chart6:
        col_item = next((c for c in ['Ítem', 'Item', 'ITEM'] if c in df_all.columns), None)
        if col_item:
            st.markdown("**Ítems / temas más recurrentes**")
            df_item = df_all[df_all[col_item].notna() & (df_all[col_item].astype(str).str.strip() != '')]
            df_item = df_item[col_item].astype(str).str.strip().value_counts().reset_index().head(15)
            df_item.columns = ['Ítem', 'Cantidad']
            fig_item = px.bar(
                df_item.sort_values('Cantidad'),
                x='Cantidad',
                y='Ítem',
                orientation='h',
                color='Cantidad',
                color_continuous_scale='Purples'
            )
            fig_item.update_layout(showlegend=False)
            st.plotly_chart(fig_item, use_container_width=True)

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
                st.plotly_chart(fig_tiempo, use_container_width=True)
            else:
                st.caption("No se pudieron interpretar las fechas de esta columna.")
