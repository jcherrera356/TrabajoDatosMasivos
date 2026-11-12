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
import streamlit as st
import pandas as pd
import plotly.express as px
from databricks import sql

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


@st.cache_data(ttl=600)
def query(sql_text: str) -> pd.DataFrame:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql_text)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Encabezado y KPIs generales (Nivel 1 del analisis descriptivo: dimension)
# ---------------------------------------------------------------------------
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
# Evolucion historica completa de empresas creadas (serie anual, 1916-hoy)
# ---------------------------------------------------------------------------
st.header("Evolucion de empresas creadas por año")

df_anual = query(f"""
    SELECT YEAR(anio_mes) AS anio,
           SUM(empresas_matriculadas) AS empresas_creadas,
           SUM(empresas_canceladas) AS empresas_canceladas
    FROM {CATALOGO}.gold.de_agg_indicadores_mes
    GROUP BY YEAR(anio_mes)
    ORDER BY anio
""")

ultimo_anio = int(df_anual["anio"].iloc[-1])
mostrar_canceladas = st.checkbox("Comparar con empresas canceladas", key="chk_canceladas")

fig = px.line(df_anual, x="anio", y="empresas_creadas", labels={"anio": "", "empresas_creadas": "Empresas creadas"})
fig.update_traces(line_color="#2a78d6", name="Creadas", showlegend=mostrar_canceladas)
if mostrar_canceladas:
    fig.add_scatter(x=df_anual["anio"], y=df_anual["empresas_canceladas"], mode="lines",
                     line_color="#eb6834", name="Canceladas")
st.plotly_chart(fig, use_container_width=True)

st.caption(
    f"{df_anual['empresas_creadas'].iloc[-1]:,} empresas creadas en {ultimo_anio} (año parcial, hasta noviembre). "
    "El crecimiento se concentra en las ultimas tres decadas, por la digitalizacion del registro mercantil; "
    "antes de 1970 casi no hay registros digitalizados."
    + (f" El salto de canceladas en {ultimo_anio} es una depuracion masiva de registros inactivos en fechas "
       "puntuales de la camara de comercio, no cierres distribuidos en el año."
       if mostrar_canceladas else "")
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

st.caption(
    "Datos leidos en vivo de datos_empresas.gold.* via SQL Warehouse de Databricks. "
    "Consulta con cache de 10 minutos (st.cache_data)."
)
