# Pipeline ETL end-to-end: `datos_empresas` (Bronze → Silver / DQL → Gold)

Pipeline en Databricks con arquitectura medallón sobre cuatro fuentes de datos abiertos de Colombia ya cargadas en Bronze (TP1):

| Fuente | Qué es | Tabla Bronze (entrada) |
|---|---|---|
| **RUES** | Registro mercantil de empresas | `bronze.de_semiestructurado_registromercantil_api` |
| **SECOP II** | Contratos públicos | `bronze.de_semiestructurado_secop_contratos_api` |
| **CIIU** | Catálogo de actividades económicas | `bronze.de_semiestructurado_actividadeseconomicas_api` |
| **TRM** | Tasa de cambio COP/USD | `bronze.de_semiestructurado_tasacambio_api` |

Las tablas principales son **RUES** y **SECOP**. CIIU y TRM son tablas de apoyo: CIIU clasifica a las empresas y TRM convierte los contratos a dólares.

---

## 1. Notebooks

| # | Notebook | Capa | Qué hace |
|---|---|---|---|
| 00 | `00_Utilidades_Pipeline` | — | Nombres de tablas, funciones de calidad, escritura `MERGE` idempotente y auditoría. Los demás notebooks lo cargan con `%run`. |
| 01 | `01_Configuracion_Pipeline` | — | Crea los esquemas `silver`, `dql`, `gold` y `auditoria`, y verifica que Bronze exista. |
| 02 | `02_Silver_CIIU` | Silver + DQL | Catálogo CIIU depurado. |
| 03 | `03_Silver_RUES` | Silver + DQL | Empresas validadas (usa el catálogo CIIU de Silver). |
| 04 | `04_Silver_SECOP` | Silver + DQL | Contratos validados y tipados. |
| 05 | `05_Silver_TRM` | Silver + DQL | TRM diaria validada. |
| 06 | `06_Gold_Dim_Empresas` | Gold | Dimensión de empresas con su actividad económica. |
| 07 | `07_Gold_Fact_Contratos` | Gold | Hechos de contratos con valor en dólares e indicadores. |
| 08 | `08_Gold_Agg_Indicadores_Mes` | Gold | Serie mensual: empresas creadas y canceladas, contratación y TRM. |
| 09 | `09_Auditoria_Ejecucion` | Auditoría | Valida que no haya duplicados y que Bronze = Silver + DQL; registra la ejecución. |
| 10 | `10_Orquestador_Pipeline` | Orquestación | Ejecuta todo el flujo desde un notebook (`dbutils.notebook.run`). |
| 11 | `11_Prueba_Idempotencia` | Evidencia | Ejecuta el pipeline varias veces y demuestra la idempotencia. |
| 12 | `12_Analisis_Preguntas_Negocio` | Análisis | Las 15 preguntas de negocio respondidas sobre Gold, con gráfico y tabla. Para la exposición. |
| — | `job_pipeline_datos_empresas.json` | Orquestación | Definición del Job de Databricks (orquestación principal). |

Los notebooks `00` a `05` y `09` a `12`, el `README.md` y el Job viven en esta carpeta (`Trabajo Practico 2 - Capa Silver/`). Los notebooks `06`, `07` y `08` (Gold) viven en la carpeta hermana `Trabajo Practico 2 - Capa Gold/` y cargan las utilidades compartidas con `%run "../Trabajo Practico 2 - Capa Silver/00_Utilidades_Pipeline"`.

## 2. Convención de nombres

Se sigue la convención que ya existe en el catálogo:

| Capa | Patrón | Tablas |
|---|---|---|
| `bronze` | `de_semiestructurado_<fuente>_api` | Las 4 de la tabla de arriba (TP1). |
| `silver` | `de_<fuente>` | `de_registromercantil`, `de_secop_contratos`, `de_actividadeseconomicas`, `de_tasacambio` |
| `dql` | `de_<fuente>_dql` | `de_registromercantil_dql`, `de_secop_contratos_dql`, `de_actividadeseconomicas_dql`, `de_tasacambio_dql` |
| `gold` | `de_dim_*` / `de_fact_*` / `de_agg_*` | `de_dim_empresas`, `de_fact_contratos`, `de_agg_indicadores_mes` |
| `auditoria` | `de_pipeline_*` | `de_pipeline_ejecuciones` |

Todas las tablas están en el catálogo `datos_empresas`.

## 3. Flujo y dependencias

```
01_Configuracion_Pipeline
        │
        ├──► 02_Silver_CIIU ──► 03_Silver_RUES ──► 06_Gold_Dim_Empresas ──┐
        ├──► 04_Silver_SECOP ─────────────────────────────────────────────┼──► 07_Gold_Fact_Contratos ──► 08_Gold_Agg_Indicadores_Mes ──► 09_Auditoria_Ejecucion
        └──► 05_Silver_TRM ───────────────────────────────────────────────┘
```

* CIIU, SECOP y TRM se procesan **en paralelo**.
* RUES espera a CIIU porque valida cada empresa contra el catálogo CIIU ya depurado.
* Gold solo lee Silver (o Gold), **nunca Bronze**.
* La auditoría es la última tarea. Si encuentra duplicados o un descuadre, falla y el Job queda en rojo.

## 4. Reglas de calidad (DQL)

Cada tabla Silver tiene al menos 3 reglas. La justificación detallada de cada una está en su notebook. Los conteos esperados se calcularon sobre el Bronze actual.

| Tabla | Reglas | Esperado con el Bronze actual |
|---|---|---|
| RUES | `campo_obligatorio_vacio`, `identificacion_invalida`, `fecha_matricula_invalida`, `fecha_cancelacion_anterior_a_matricula`, `ciiu_no_existe_en_catalogo` (correspondencia), `duplicado_version_anterior` (unicidad) | 33.324 → **30.226 Silver + 3.098 DQL** |
| SECOP | `campo_obligatorio_vacio`, `valor_contrato_invalido`, `fechas_inconsistentes`, `valor_pagado_invalido`, `duplicado_version_anterior` | 63.770 → **63.110 Silver + 660 DQL** |
| CIIU | `codigo_ciiu_invalido`, `descripcion_vacia`, `duplicado_version_anterior` | 499 → 499 Silver + 0 DQL |
| TRM | `valor_trm_fuera_de_rango`, `vigencia_invalida`, `unidad_invalida`, `duplicado_version_anterior` | 235 → 235 Silver + 0 DQL |

Cada registro rechazado se guarda en DQL con:

* La **fila original de Bronze** sin transformar, para poder analizarla y corregirla.
* `_motivo_rechazo`, con **todas** las reglas que incumple separadas por `; `, y `_num_reglas_incumplidas`.
* `_id_registro_bronze` (trazabilidad hasta Bronze) y `_fecha_rechazo`.

Las reglas se aplican **durante** el procesamiento hacia Silver: un registro rechazado nunca llega a Silver ni a Gold.

## 5. Idempotencia

**Estrategia:** `MERGE` por llave de negocio con detección de cambios, en Silver, DQL y Gold.

| Cláusula | Efecto |
|---|---|
| `WHEN MATCHED AND _hash_registro distinto → UPDATE` | Solo se reescribe una fila si su contenido cambió. |
| `WHEN NOT MATCHED → INSERT` | Llaves nuevas. |
| `WHEN NOT MATCHED BY SOURCE → DELETE` | Llaves que ya no salen en el resultado; por ejemplo, un registro que pasó a ser rechazado. |

**Por qué MERGE y no sobrescritura:** Bronze se carga de forma incremental (append), así que la misma empresa o contrato llega varias veces con versiones nuevas. El MERGE por llave aplica cada actualización sobre la fila existente, sin duplicarla, y solo toca lo que cambió. Por eso `_processed_at` y `_fecha_rechazo` conservan la fecha original cuando nada cambia.

**Evidencia** (`11_Prueba_Idempotencia`):

* **A.** Dos corridas seguidas: mismas filas, mismo checksum y **0 insertadas / 0 actualizadas / 0 eliminadas** en la segunda.
* **B.** DQL no acumula: la segunda corrida no inserta ni reescribe rechazos.
* **C.** Una versión nueva de una empresa en Bronze produce **1 actualizada y 0 insertadas** en Silver, y la versión vieja pasa a DQL. Al retirarla, todo vuelve exactamente al estado inicial.

Cada corrida queda registrada en `datos_empresas.auditoria.de_pipeline_ejecuciones`.

## 6. Cómo ejecutarlo en Databricks

1. **Traer los notebooks al workspace.** Lo más simple es crear un *Git folder* (Workspace → Create → Git folder) con este repositorio. Otra opción es importar la carpeta.
2. **Primera ejecución:** abrir `10_Orquestador_Pipeline` y darle *Run all*. Crea los esquemas y todas las tablas.
3. **Crear el Job:** Workflows → Jobs → Create Job → menú `⋮` → *Edit as JSON* (o *View JSON* → *Edit*). Pegar el contenido de `job_pipeline_datos_empresas.json` y reemplazar `<su-correo>` en las rutas por la ruta real de la carpeta en el workspace. Sin un clúster definido, el Job usa cómputo serverless.
4. **Imagen del pipeline:** abrir el Job → pestaña *Tasks* y capturar el grafo. Después de una corrida, la vista de la ejecución muestra las tareas en verde.
5. **Evidencia de idempotencia:** ejecutar `11_Prueba_Idempotencia` (tarda varios minutos porque corre el pipeline 4 veces), o ejecutar el Job dos veces y consultar:

```sql
SELECT id_ejecucion, capa, tabla, filas_tabla, filas_insertadas, filas_actualizadas, filas_eliminadas, checksum
FROM datos_empresas.auditoria.de_pipeline_ejecuciones
ORDER BY tabla, fecha_validacion;
```

## 7. Hallazgos de los datos que conviene explicar

* **2.089 empresas (6 %) tienen un CIIU que no está en el catálogo.** 1.522 tienen `9999` (sin actividad) y el resto son códigos reales que le faltan al catálogo, como `7112` o `8899`. Por eso la regla de correspondencia las rechaza y DQL muestra exactamente qué códigos hay que agregar.
* **1.903 empresas tienen la identificación en ceros** (`0000000000000`). Sin documento no se pueden enlazar con contratos.
* **Solo unos 300 contratos tienen un proveedor registrado en RUES.** El 83 % de los proveedores de SECOP son personas naturales con cédula (contratistas de prestación de servicios), y el RUES cargado es una muestra de unas 33 mil empresas. `proveedor_registrado_rues` lo deja medido.
* **La TRM cubre solo del 2025-09-19 al 2026-09-19.** Los contratos firmados antes quedan con `valor_contrato_usd = NULL`, y el análisis TRM vs. cancelaciones tiene unos 12 meses, así que es exploratorio.
