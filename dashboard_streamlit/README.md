# Dashboard Streamlit - Capa Gold (datos_empresas)

Dos formas de conectar esta app a Databricks. El codigo de `app.py` es el
mismo en ambos casos.

## Opcion A - Databricks App (recomendado para la sustentacion)

Databricks tiene soporte nativo para apps de Streamlit (Databricks Apps):
corren dentro del workspace, con autenticacion automatica contra Unity
Catalog -no hay que manejar ningun token a mano-.

Pasos (en la UI de Databricks):

1. **Compute > Apps > Create app**, elegir plantilla **Streamlit**.
2. Subir los archivos `app.py` y `requirements.txt` de esta carpeta (o
   apuntar la app a esta carpeta del Git folder si ya clonaste el repo en
   el Workspace).
3. En la pestana **Resources** del app, agregar un recurso tipo
   **SQL Warehouse** y seleccionar el warehouse que ya usamos para todo el
   proyecto. Databricks Apps inyecta automaticamente las variables de
   entorno `DATABRICKS_HOST` y las credenciales del warehouse seleccionado
   -no hace falta `DATABRICKS_TOKEN` en este modo-.
4. **Deploy**. Databricks instala `requirements.txt` y corre la app.
5. Para que la app pueda leer el catalogo `datos_empresas`, el service
   principal de la app necesita `USE CATALOG`, `USE SCHEMA` y `SELECT`
   sobre `datos_empresas.gold.*` (ver notebook de gobernanza: el mismo
   patron de `GRANT` que usamos ahi, pero otorgado al service principal de
   la app en vez de a un grupo de usuarios).

Esta es la forma mas facil de mostrar el dashboard en la sustentacion: se
abre con una URL del propio workspace, sin instalar nada en tu maquina.

## Opcion B - Standalone (correr en tu propia maquina)

Util para desarrollar y probar antes de subir a Databricks Apps.

```bash
pip install -r requirements.txt

# Variables de entorno (powershell):
$env:DATABRICKS_TOKEN = "tu_personal_access_token"
$env:DATABRICKS_HOST = "dbc-7478df09-02e1.cloud.databricks.com"
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/1245027be3dc085e"

streamlit run app.py
```

Abre `http://localhost:8501`. El `DATABRICKS_TOKEN` ya lo tenes configurado
como variable de entorno de usuario en Windows desde que conectamos el MCP
de Databricks a esta sesion -si corres esto en otra maquina, necesitas
generar un token nuevo en Databricks (User Settings > Developer > Access
tokens) y el `http_path` de tu SQL Warehouse (Compute > tu warehouse >
Connection details).

## Por que esta arquitectura

- Las consultas pesadas (agregaciones sobre 2,6 millones de empresas y 250
  mil contratos) corren **en el SQL Warehouse de Databricks**, nunca traen
  los datos crudos a la maquina donde corre Streamlit -el mismo principio
  de "agregar en Spark/SQL, graficar en pandas" que se ve en el notebook de
  analisis descriptivo del profe.
- `st.cache_data(ttl=600)` evita repetir la misma consulta cada vez que
  alguien interactua con la app (cache de 10 minutos).
- `st.cache_resource` mantiene una sola conexion abierta al warehouse en
  vez de reconectar en cada rerun de Streamlit.
