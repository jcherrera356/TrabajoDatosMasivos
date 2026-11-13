"""
Dashboard de Analitica Descriptiva - Capa Gold (datos_empresas)
================================================================
Pregunta de negocio: como se relaciona el comportamiento de las empresas
colombianas (creacion/cancelacion) con su participacion como proveedores
del Estado (SECOP) y con factores macroeconomicos como la TRM?

Dos formas de correr esta app (ver README.md en esta misma carpeta):
  1. Standalone, en tu maquina, conectando a un SQL Warehouse por token.
  2. Como Databricks App (recomendado): se autentica sola, sin token.

En ambos casos el codigo es el mismo: get_connection() detecta donde corre.
"""

import os
import time
import streamlit as st
import pandas as pd
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from databricks import sql
from databricks.sql.exc import OperationalError

st.set_page_config(page_title="Datos Empresas - Analitica Gold", layout="wide")

CATALOGO = "datos_empresas"


# ---------------------------------------------------------------------------
# Conexion: funciona standalone (variables de entorno) o como Databricks App
# ---------------------------------------------------------------------------
def _config(key: str, default: str = None) -> str:
    # Prioridad: variable de entorno (Databricks Apps la inyecta sola) -> st.secrets
    # (secrets.toml local o Secrets de Streamlit Cloud) -> default.
    value = os.getenv(key)
    if value:
        return value
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


@st.cache_resource
def get_connection():
    host = _config("DATABRICKS_HOST", "dbc-7478df09-02e1.cloud.databricks.com")
    http_path = _config("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/1245027be3dc085e")
    token = _config("DATABRICKS_TOKEN")
    if not token:
        st.error(
            "Falta la variable de entorno DATABRICKS_TOKEN. "
            "Si corres esta app como Databricks App, agrega el SQL Warehouse "
            "como 'resource' de la app en vez de usar un token (ver README.md)."
        )
        st.stop()
    return sql.connect(server_hostname=host, http_path=http_path, access_token=token)


INTENTOS_MAX = 4
ESPERA_ENTRE_INTENTOS_SEG = 8


@st.cache_data(ttl=600)
def query(sql_text: str) -> pd.DataFrame:
    # El SQL Warehouse se apaga solo por inactividad (auto-stop). La primera consulta
    # despues de un rato lo despierta, pero puede tardar en arrancar -sin reintentos,
    # esa consulta falla con un error de conexion en vez de simplemente esperar.
    for intento in range(1, INTENTOS_MAX + 1):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(sql_text)
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
            return pd.DataFrame(rows, columns=cols)
        except OperationalError:
            if intento == INTENTOS_MAX:
                st.error(
                    "No se pudo conectar al SQL Warehouse de Databricks despues de "
                    f"{INTENTOS_MAX} intentos. Es probable que el warehouse este "
                    "arrancando tras un periodo de inactividad (auto-stop) -esperá "
                    "un minuto y recarga la pagina."
                )
                st.stop()
            get_connection.clear()  # la conexion cacheada puede haber quedado invalida
            with st.spinner(
                f"El SQL Warehouse parece estar arrancando (auto-stop) -reintentando "
                f"({intento}/{INTENTOS_MAX})..."
            ):
                time.sleep(ESPERA_ENTRE_INTENTOS_SEG)
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Encabezado y KPIs generales (Nivel 1 del analisis descriptivo: dimension)
# ---------------------------------------------------------------------------
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_pascual_bravo.png")
st.image(LOGO_PATH, width=260)
st.title("Analitica Descriptiva - Capa Gold")
st.caption(
    "Pregunta de negocio: ¿como se relaciona la creacion y cancelacion de "
    "empresas en Colombia con su participacion como proveedores del Estado "
    "y con la TRM?"
)

kpis = query(f"""
    SELECT
      (SELECT COUNT(*) FROM {CATALOGO}.gold.de_dim_empresas)                                   AS empresas,
      (SELECT SUM(CASE WHEN es_activa THEN 1 ELSE 0 END) FROM {CATALOGO}.gold.de_dim_empresas)  AS activas,
      (SELECT COUNT(*) FROM {CATALOGO}.gold.de_fact_contratos)                                  AS contratos,
      (SELECT SUM(CASE WHEN proveedor_registrado_rues THEN 1 ELSE 0 END)
         FROM {CATALOGO}.gold.de_fact_contratos)                                                AS contratos_con_proveedor_rues
""")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Empresas (RUES)", f"{kpis['empresas'][0]:,}")
c2.metric("Empresas activas", f"{kpis['activas'][0]:,}", f"{100*kpis['activas'][0]/kpis['empresas'][0]:.1f}%")
c3.metric("Contratos (SECOP)", f"{kpis['contratos'][0]:,}")
c4.metric(
    "Con proveedor en RUES",
    f"{kpis['contratos_con_proveedor_rues'][0]:,}",
    f"{100*kpis['contratos_con_proveedor_rues'][0]/kpis['contratos'][0]:.1f}%",
)

st.divider()

# ---------------------------------------------------------------------------
# Empresas creadas y canceladas por mes (mismo rango de meses que el bloque TRM)
# ---------------------------------------------------------------------------
st.header("Empresas creadas y canceladas por mes")

df_mensual = query(f"""
    SELECT anio_mes, empresas_matriculadas AS empresas_creadas, empresas_canceladas, trm_promedio
    FROM {CATALOGO}.gold.de_agg_indicadores_mes
    WHERE trm_promedio IS NOT NULL
    ORDER BY anio_mes
""")
df_mensual["trm_promedio"] = df_mensual["trm_promedio"].astype(float)  # viene como Decimal del conector

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def mes_es(fecha) -> str:
    return f"{MESES_ES[fecha.month - 1]} de {fecha.year}"


filas_stats = []
for col, etiqueta in [("empresas_creadas", "Creadas"), ("empresas_canceladas", "Canceladas"), ("trm_promedio", "TRM (COP/USD)")]:
    fila_min = df_mensual.loc[df_mensual[col].idxmin()]
    fila_max = df_mensual.loc[df_mensual[col].idxmax()]
    filas_stats.append({
        "Serie": etiqueta,
        "Promedio": round(df_mensual[col].mean(), 1),
        "Minimo": round(fila_min[col], 1),
        "Mes (minimo)": mes_es(fila_min["anio_mes"]),
        "Maximo": round(fila_max[col], 1),
        "Mes (maximo)": mes_es(fila_max["anio_mes"]),
    })
stats_mensual = pd.DataFrame(filas_stats).set_index("Serie")
st.dataframe(stats_mensual, use_container_width=True)

mostrar_trm = st.checkbox("Mostrar TRM promedio mensual", key="chk_trm_mes")

if not mostrar_trm:
    fig = px.line(df_mensual, x="anio_mes", y=["empresas_creadas", "empresas_canceladas"],
                  labels={"anio_mes": "", "value": "Empresas", "variable": ""})
    fig.for_each_trace(lambda t: t.update(
        line_color="#2a78d6" if t.name == "empresas_creadas" else "#eb6834",
        name="Creadas" if t.name == "empresas_creadas" else "Canceladas",
    ))
    st.plotly_chart(fig, use_container_width=True)
else:
    # El TRM (pesos por dolar) es otra unidad, no otra escala del mismo conteo
    # de empresas: para ver su propia fluctuacion necesita su propio eje Y,
    # a la derecha, en vez de compartir el eje de conteos (ahi se aplana).
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df_mensual["anio_mes"], y=df_mensual["empresas_creadas"],
                              mode="lines", line_color="#2a78d6", name="Creadas"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_mensual["anio_mes"], y=df_mensual["empresas_canceladas"],
                              mode="lines", line_color="#eb6834", name="Canceladas"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_mensual["anio_mes"], y=df_mensual["trm_promedio"],
                              mode="lines", line_color="#1baf7a", line_dash="dot",
                              name="TRM promedio (COP/USD)"), secondary_y=True)
    fig.update_yaxes(title_text="Empresas", secondary_y=False)
    fig.update_yaxes(title_text="TRM (COP/USD)", secondary_y=True, showgrid=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "El TRM se muestra en el eje derecho (linea punteada), con su propia escala, "
        "para que se note su fluctuacion real frente a los conteos de empresas."
    )

ultimo_mes = mes_es(df_mensual["anio_mes"].iloc[-1])
st.caption(
    f"{int(df_mensual['empresas_creadas'].iloc[-1]):,} creadas y {int(df_mensual['empresas_canceladas'].iloc[-1]):,} "
    f"canceladas en {ultimo_mes} (mes parcial). Los picos de canceladas en abril y agosto de 2026 son "
    "depuraciones masivas de registros inactivos que la camara de comercio ejecuta en fechas puntuales, "
    "no cierres de empresa distribuidos en el mes."
)

# ---------------------------------------------------------------------------
# Correlacion entre las 3 series anteriores (creadas, canceladas, TRM)
# ---------------------------------------------------------------------------
st.subheader("Correlacion entre creadas, canceladas y TRM")

etiquetas = {"empresas_creadas": "Creadas", "empresas_canceladas": "Canceladas", "trm_promedio": "TRM promedio"}
corr_matrix = df_mensual[["empresas_creadas", "empresas_canceladas", "trm_promedio"]].corr().round(3)
nombres = [etiquetas[c] for c in corr_matrix.columns]

fig_corr = go.Figure(data=go.Heatmap(
    z=corr_matrix.values,
    x=nombres, y=nombres,
    zmin=-1, zmax=1, zmid=0,
    colorscale=[[0, "#2a78d6"], [0.5, "#f0efec"], [1, "#e34948"]],
    text=corr_matrix.values,
    texttemplate="%{text:.2f}",
    textfont={"size": 14},
    hovertemplate="%{y} vs %{x}: %{z:.3f}<extra></extra>",
    colorbar=dict(title="Pearson"),
))
fig_corr.update_layout(height=320, margin=dict(t=10, b=10))
fig_corr.update_yaxes(autorange="reversed")
st.plotly_chart(fig_corr, use_container_width=True)

st.caption(
    f"Correlacion de Pearson sobre los {len(df_mensual)} meses con TRM disponible. Creadas y canceladas tienen "
    f"una correlacion positiva debil ({corr_matrix.loc['empresas_creadas', 'empresas_canceladas']:.2f}) -ambas "
    "suben y bajan juntas con el nivel general de actividad del registro mercantil. El TRM, en cambio, no muestra "
    f"relacion con ninguna de las dos (ambas cercanas a 0: {corr_matrix.loc['empresas_creadas', 'trm_promedio']:.2f} "
    f"y {corr_matrix.loc['empresas_canceladas', 'trm_promedio']:.2f}), consistente con el hallazgo de la Fase 5 "
    "del notebook de CRISP-DM."
)

st.divider()

# ---------------------------------------------------------------------------
# Empresas creadas y canceladas por actividad economica
# ---------------------------------------------------------------------------
st.header("Empresas creadas y canceladas por actividad economica")

por_actividad_ciclo = query(f"""
    SELECT CONCAT(division_ciiu_principal, ' - ', MIN(descripcion_ciiu_principal)) AS actividad,
           COUNT(*) AS empresas_creadas,
           SUM(CASE WHEN NOT es_activa THEN 1 ELSE 0 END) AS empresas_canceladas,
           ROUND(100.0 * SUM(CASE WHEN NOT es_activa THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelacion
    FROM {CATALOGO}.gold.de_dim_empresas
    WHERE division_ciiu_principal IS NOT NULL
    GROUP BY division_ciiu_principal
    ORDER BY empresas_creadas DESC
    LIMIT 10
""")
fig = px.bar(
    por_actividad_ciclo.sort_values("empresas_creadas"),
    x=["empresas_creadas", "empresas_canceladas"], y="actividad", orientation="h",
    barmode="group",
    labels={"value": "Empresas", "actividad": "", "variable": ""},
)
fig.for_each_trace(lambda t: t.update(
    marker_color="#2a78d6" if t.name == "empresas_creadas" else "#eb6834",
    name="Creadas" if t.name == "empresas_creadas" else "Canceladas",
))
st.plotly_chart(fig, use_container_width=True)

tasa_cancelacion = query(f"""
    SELECT CONCAT(division_ciiu_principal, ' - ', MIN(descripcion_ciiu_principal)) AS actividad,
           ROUND(100.0 * SUM(CASE WHEN NOT es_activa THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelacion
    FROM {CATALOGO}.gold.de_dim_empresas
    WHERE division_ciiu_principal IS NOT NULL
    GROUP BY division_ciiu_principal
    HAVING COUNT(*) > 10000
    ORDER BY pct_cancelacion DESC
    LIMIT 1
""")
top_riesgo = tasa_cancelacion.iloc[0]
top_volumen = por_actividad_ciclo.iloc[0]
st.caption(
    f"{top_volumen['actividad']} concentra el mayor volumen, tanto de creadas ({top_volumen['empresas_creadas']:,}) "
    f"como de canceladas ({top_volumen['empresas_canceladas']:,}) -simplemente por ser la actividad mas comun en "
    f"el RUES. Pero en tasa de cancelacion relativa, {top_riesgo['actividad']} es la mas riesgosa, con "
    f"{top_riesgo['pct_cancelacion']}% de sus empresas canceladas (mas del doble que casi cualquier otra "
    "actividad con volumen comparable): el volumen absoluto y el riesgo relativo cuentan historias distintas."
)

st.divider()

# ---------------------------------------------------------------------------
# Bloque A: TRM vs creacion/cancelacion de empresas (cruce temporal, Gold agg)
# ---------------------------------------------------------------------------
st.header("A. TRM y el ciclo de vida de las empresas")

df_mes = query(f"""
    SELECT anio_mes, trm_promedio, variacion_trm_pct,
           empresas_matriculadas, empresas_canceladas, saldo_neto_empresas
    FROM {CATALOGO}.gold.de_agg_indicadores_mes
    WHERE trm_promedio IS NOT NULL
    ORDER BY anio_mes
""")

if df_mes.empty:
    st.info("No hay meses con TRM disponible todavia.")
else:
    col_izq, col_der = st.columns(2)
    with col_izq:
        fig = px.line(df_mes, x="anio_mes", y="trm_promedio", title="TRM promedio mensual (COP por USD)")
        fig.update_traces(line_color="#0E7C86")
        st.plotly_chart(fig, use_container_width=True)
    with col_der:
        fig = px.bar(df_mes, x="anio_mes", y="empresas_canceladas", title="Empresas canceladas por mes")
        fig.update_traces(marker_color="#F2A541")
        st.plotly_chart(fig, use_container_width=True)

    corr = query(f"""
        SELECT
          ROUND(TRY_DIVIDE(COVAR_POP(trm_promedio, empresas_canceladas),
                           STDDEV_POP(trm_promedio) * STDDEV_POP(empresas_canceladas)), 3) AS corr_trm_cancelaciones,
          ROUND(TRY_DIVIDE(COVAR_POP(trm_promedio, empresas_matriculadas),
                           STDDEV_POP(trm_promedio) * STDDEV_POP(empresas_matriculadas)), 3) AS corr_trm_matriculas,
          COUNT(*) AS meses_con_trm
        FROM {CATALOGO}.gold.de_agg_indicadores_mes
        WHERE trm_promedio IS NOT NULL
    """)
    r = corr.iloc[0]
    st.caption(
        f"Correlacion exploratoria (Pearson) sobre {int(r['meses_con_trm'])} meses con TRM disponible: "
        f"TRM vs. cancelaciones = {r['corr_trm_cancelaciones']}, "
        f"TRM vs. matriculas nuevas = {r['corr_trm_matriculas']}. "
        f"Con pocos meses de historia, es exploratorio, no concluyente."
    )

st.divider()

# ---------------------------------------------------------------------------
# Bloque B: Proveedores del Estado registrados en RUES (cruce SECOP x RUES)
# ---------------------------------------------------------------------------
st.header("B. Proveedores del Estado y su huella en el RUES")

cobertura = query(f"""
    SELECT tipo_documento_proveedor,
           COUNT(*) AS contratos,
           SUM(CASE WHEN proveedor_registrado_rues THEN 1 ELSE 0 END) AS con_rues,
           ROUND(100 * AVG(CASE WHEN proveedor_registrado_rues THEN 1 ELSE 0 END), 2) AS pct_con_rues
    FROM {CATALOGO}.gold.de_fact_contratos
    GROUP BY tipo_documento_proveedor
    ORDER BY contratos DESC
""")

actividad_proveedores = query(f"""
    SELECT CONCAT(e.division_ciiu_principal, ' - ', MIN(e.descripcion_ciiu_principal)) AS actividad,
           COUNT(*) AS contratos,
           ROUND(SUM(f.valor_contrato) / 1e9, 2) AS valor_miles_millones_cop
    FROM {CATALOGO}.gold.de_fact_contratos f
    JOIN {CATALOGO}.gold.de_dim_empresas e ON e.llave_empresa = f.llave_empresa_proveedor
    GROUP BY e.division_ciiu_principal
    ORDER BY valor_miles_millones_cop DESC
    LIMIT 10
""")

col_izq, col_der = st.columns([1, 1.3])
with col_izq:
    st.dataframe(cobertura, use_container_width=True, hide_index=True)
    st.caption(
        "La mayoria de proveedores del Estado son personas naturales con cedula "
        "(contratistas de prestacion de servicios); el RUES cargado tampoco cubre "
        "el pais completo, por eso la cobertura general es baja."
    )
with col_der:
    fig = px.bar(
        actividad_proveedores.sort_values("valor_miles_millones_cop"),
        x="valor_miles_millones_cop", y="actividad", orientation="h",
        title="Valor contratado por actividad economica del proveedor (solo proveedores en RUES)",
        labels={"valor_miles_millones_cop": "Miles de millones de COP", "actividad": ""},
    )
    fig.update_traces(marker_color="#15B3A6")
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Bloque C: panorama general de contratacion (exploratorio, Nivel 1-2)
# ---------------------------------------------------------------------------
st.header("C. Panorama general de la contratacion publica")

por_sector = query(f"""
    SELECT sector,
           COUNT(*) AS contratos,
           ROUND(SUM(valor_contrato) / 1e9, 1) AS valor_miles_millones_cop,
           ROUND(100 * AVG(CASE WHEN es_contratacion_directa THEN 1 ELSE 0 END), 1) AS pct_directa,
           ROUND(100 * AVG(CASE WHEN es_pyme THEN 1 ELSE 0 END), 1) AS pct_pyme
    FROM {CATALOGO}.gold.de_fact_contratos
    GROUP BY sector
    ORDER BY valor_miles_millones_cop DESC
    LIMIT 10
""")
fig = px.bar(
    por_sector.sort_values("valor_miles_millones_cop"),
    x="valor_miles_millones_cop", y="sector", orientation="h",
    title="Top 10 sectores por valor contratado",
    hover_data=["pct_directa", "pct_pyme"],
    labels={"valor_miles_millones_cop": "Miles de millones de COP", "sector": ""},
)
fig.update_traces(marker_color="#2F3C7E")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Bloque D: ubicacion (camara de comercio) y participacion como proveedor
# ---------------------------------------------------------------------------
st.header("D. ¿La ubicacion se relaciona con ser proveedor del Estado?")

por_camara = query(f"""
    SELECT e.camara_comercio,
           COUNT(DISTINCT e.llave_empresa) AS total_empresas,
           ROUND(100.0 * COUNT(DISTINCT f.llave_empresa_proveedor) / COUNT(DISTINCT e.llave_empresa), 3) AS pct_proveedoras
    FROM {CATALOGO}.gold.de_dim_empresas e
    LEFT JOIN {CATALOGO}.gold.de_fact_contratos f ON f.llave_empresa_proveedor = e.llave_empresa
    GROUP BY e.camara_comercio
    HAVING COUNT(DISTINCT e.llave_empresa) > 5000
    ORDER BY pct_proveedoras DESC
    LIMIT 10
""")
fig = px.bar(
    por_camara.sort_values("pct_proveedoras"),
    x="pct_proveedoras", y="camara_comercio", orientation="h",
    labels={"pct_proveedoras": "% de empresas que son proveedoras del Estado", "camara_comercio": ""},
)
fig.update_traces(marker_color="#2a78d6")
st.plotly_chart(fig, use_container_width=True)
top_camara = por_camara.sort_values("pct_proveedoras", ascending=False).iloc[0]
camaras_grandes = query(f"""
    SELECT e.camara_comercio,
           ROUND(100.0 * COUNT(DISTINCT f.llave_empresa_proveedor) / COUNT(DISTINCT e.llave_empresa), 2) AS pct_proveedoras
    FROM {CATALOGO}.gold.de_dim_empresas e
    LEFT JOIN {CATALOGO}.gold.de_fact_contratos f ON f.llave_empresa_proveedor = e.llave_empresa
    WHERE e.camara_comercio = 'BOGOTA'
    GROUP BY e.camara_comercio
""")
pct_bogota = camaras_grandes["pct_proveedoras"].iloc[0] if not camaras_grandes.empty else None
st.caption(
    f"{top_camara['camara_comercio'].title()} tiene la mayor proporcion de empresas proveedoras del Estado "
    f"({top_camara['pct_proveedoras']}%)"
    + (f", varias veces mas que Bogota ({pct_bogota}%)" if pct_bogota is not None else "")
    + ": en camaras de ciudades intermedias, una porcion mayor del tejido empresarial local depende de la "
    "contratacion publica regional que en las grandes capitales."
)

st.divider()

# ---------------------------------------------------------------------------
# Bloque E: actividad economica y participacion en contratacion estatal
# ---------------------------------------------------------------------------
st.header("E. ¿Que actividades economicas concentran mas proveedores del Estado?")

por_actividad = query(f"""
    SELECT CONCAT(e.division_ciiu_principal, ' - ', MIN(e.descripcion_ciiu_principal)) AS actividad,
           COUNT(DISTINCT e.llave_empresa) AS total_empresas,
           ROUND(100.0 * COUNT(DISTINCT f.llave_empresa_proveedor) / COUNT(DISTINCT e.llave_empresa), 3) AS pct_proveedoras
    FROM {CATALOGO}.gold.de_dim_empresas e
    LEFT JOIN {CATALOGO}.gold.de_fact_contratos f ON f.llave_empresa_proveedor = e.llave_empresa
    WHERE e.division_ciiu_principal IS NOT NULL
    GROUP BY e.division_ciiu_principal
    HAVING COUNT(DISTINCT e.llave_empresa) > 10000
    ORDER BY pct_proveedoras DESC
    LIMIT 10
""")
fig = px.bar(
    por_actividad.sort_values("pct_proveedoras"),
    x="pct_proveedoras", y="actividad", orientation="h",
    labels={"pct_proveedoras": "% de empresas que son proveedoras del Estado", "actividad": ""},
)
fig.update_traces(marker_color="#1baf7a")
st.plotly_chart(fig, use_container_width=True)
top_actividad = por_actividad.sort_values("pct_proveedoras", ascending=False).iloc[0]
st.caption(
    f"{top_actividad['actividad']} lidera con {top_actividad['pct_proveedoras']}% de sus empresas como "
    "proveedoras del Estado. Las actividades en el top son, en general, las que el Estado mas contrata "
    "(infraestructura, salud publica, control fiscal, sistemas), lo que explica la concentracion."
)

st.divider()

# ---------------------------------------------------------------------------
# Bloque F: tipo de empresa (persona natural vs juridica)
# ---------------------------------------------------------------------------
st.header("F. ¿El tipo de empresa se relaciona con ser proveedor y con sobrevivir?")

por_tipo = query(f"""
    SELECT
      CASE WHEN e.organizacion_juridica = 'PERSONA NATURAL' THEN 'Persona Natural' ELSE 'Persona Juridica' END AS tipo_empresa,
      COUNT(DISTINCT e.llave_empresa) AS total_empresas,
      ROUND(100.0 * COUNT(DISTINCT f.llave_empresa_proveedor) / COUNT(DISTINCT e.llave_empresa), 3) AS pct_proveedoras,
      ROUND(100.0 * SUM(CASE WHEN e.es_activa THEN 1 ELSE 0 END) / COUNT(DISTINCT e.llave_empresa), 2) AS pct_activas
    FROM {CATALOGO}.gold.de_dim_empresas e
    LEFT JOIN {CATALOGO}.gold.de_fact_contratos f ON f.llave_empresa_proveedor = e.llave_empresa
    GROUP BY CASE WHEN e.organizacion_juridica = 'PERSONA NATURAL' THEN 'Persona Natural' ELSE 'Persona Juridica' END
""")
col_izq, col_der = st.columns(2)
with col_izq:
    fig = px.bar(por_tipo, x="tipo_empresa", y="pct_proveedoras",
                 labels={"tipo_empresa": "", "pct_proveedoras": "% proveedoras del Estado"})
    fig.update_traces(marker_color="#2a78d6")
    st.plotly_chart(fig, use_container_width=True)
with col_der:
    fig = px.bar(por_tipo, x="tipo_empresa", y="pct_activas",
                 labels={"tipo_empresa": "", "pct_activas": "% activas (no canceladas)"})
    fig.update_traces(marker_color="#eb6834")
    st.plotly_chart(fig, use_container_width=True)
fila_natural = por_tipo.loc[por_tipo["tipo_empresa"] == "Persona Natural"].iloc[0]
fila_juridica = por_tipo.loc[por_tipo["tipo_empresa"] == "Persona Juridica"].iloc[0]
st.caption(
    f"Las personas juridicas tienen {fila_juridica['pct_proveedoras'] / fila_natural['pct_proveedoras']:.1f}x "
    f"mas probabilidad de ser proveedoras del Estado que las personas naturales "
    f"({fila_juridica['pct_proveedoras']}% vs {fila_natural['pct_proveedoras']}%) y tambien sobreviven mas "
    f"({fila_juridica['pct_activas']}% activas vs {fila_natural['pct_activas']}%): formalizarse como "
    "sociedad se asocia tanto con mas acceso a contratacion publica como con mayor supervivencia."
)

st.divider()

# ---------------------------------------------------------------------------
# Bloque G: respuesta directa - ser proveedor del Estado y supervivencia
# ---------------------------------------------------------------------------
st.header("G. ¿Ser proveedor del Estado se relaciona con sobrevivir mas tiempo?")

por_grupo = query(f"""
    SELECT
      CASE WHEN f.llave_empresa_proveedor IS NOT NULL THEN 'Proveedor del Estado' ELSE 'No proveedor' END AS grupo,
      COUNT(DISTINCT e.llave_empresa) AS total_empresas,
      ROUND(100.0 * SUM(CASE WHEN e.es_activa THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_activas
    FROM {CATALOGO}.gold.de_dim_empresas e
    LEFT JOIN (SELECT DISTINCT llave_empresa_proveedor FROM {CATALOGO}.gold.de_fact_contratos) f
      ON f.llave_empresa_proveedor = e.llave_empresa
    GROUP BY CASE WHEN f.llave_empresa_proveedor IS NOT NULL THEN 'Proveedor del Estado' ELSE 'No proveedor' END
""")
fig = px.bar(por_grupo, x="grupo", y="pct_activas",
             labels={"grupo": "", "pct_activas": "% de empresas activas"})
fig.update_traces(marker_color=["#eb6834", "#2a78d6"])
st.plotly_chart(fig, use_container_width=True)
pct_activas_proveedor = por_grupo.loc[por_grupo["grupo"] == "Proveedor del Estado", "pct_activas"].iloc[0]
pct_activas_no_proveedor = por_grupo.loc[por_grupo["grupo"] == "No proveedor", "pct_activas"].iloc[0]
diferencia_activas = round(pct_activas_proveedor - pct_activas_no_proveedor, 1)
st.caption(
    f"{pct_activas_proveedor}% de las empresas que alguna vez fueron proveedoras del Estado siguen activas, "
    f"frente a {pct_activas_no_proveedor}% de las que nunca lo fueron -una diferencia de {diferencia_activas} "
    "puntos porcentuales. Esta es la respuesta mas directa a la pregunta de negocio: ser proveedor del Estado "
    "se asocia con una mayor supervivencia empresarial, aunque la diferencia es modesta y puede reflejar tanto "
    "el efecto de un ingreso mas estable como un sesgo de seleccion (el Estado tiende a contratar empresas ya "
    "consolidadas, no recien creadas)."
)

st.divider()

# ---------------------------------------------------------------------------
# Conclusiones generales (respuesta consolidada a la pregunta de negocio)
# ---------------------------------------------------------------------------
st.header("Conclusiones")
st.markdown(f"""
Volviendo a la pregunta de negocio: *¿como se relaciona la creacion y cancelacion de empresas en Colombia
con su participacion como proveedores del Estado y con la TRM?*

- **La TRM no se relaciona con el ciclo de vida empresarial.** Las correlaciones con creacion y cancelacion
  mensual son practicamente cero ({corr_matrix.loc['empresas_creadas', 'trm_promedio']:.2f} y
  {corr_matrix.loc['empresas_canceladas', 'trm_promedio']:.2f}). No hay evidencia, en los meses disponibles,
  de que el tipo de cambio influya en que una empresa nazca o cierre.
- **Ser proveedor del Estado si se relaciona con la supervivencia**, aunque de forma modesta:
  {pct_activas_proveedor}% de activas entre proveedoras vs {pct_activas_no_proveedor}% entre no proveedoras.
- **Esa relacion es mas fuerte en algunos segmentos que en otros:** las personas juridicas (vs. naturales)
  y las empresas de ciudades intermedias y sectores ligados a infraestructura/salud/TI (vs. grandes
  capitales y comercio general) tienen tasas de participacion estatal notablemente mas altas.
- **Conclusion honesta:** el factor que mas se relaciona con el ciclo de vida de una empresa en estos datos
  no es macroeconomico (TRM), sino estructural -el tipo de organizacion juridica y su relacion con el Estado
  como cliente.
""")

st.caption(
    "Datos leidos en vivo de datos_empresas.gold.* via SQL Warehouse de Databricks. "
    "Consulta con cache de 10 minutos (st.cache_data)."
)
