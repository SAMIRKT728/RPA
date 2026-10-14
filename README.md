# RPA - Google Drive a SQL Server con PySpark

Automatización para extraer hojas de cálculo (Google Sheets / Excel `.xlsx`) desde Google Drive a través de las APIs de Google Workspace, transformar los datos con **PySpark** y sincronizarlos de forma continua e idempotente en Microsoft SQL Server (`DGEMPRES01`, `DGEMPRES30`, `DGEMPRES70`, `DGEMPRES80`).

---

## 🚀 Características Principales

1. **Conexión Google Workspace / Drive**:
   - Soporte para autenticación **OAuth2** (usando `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, 100% compatible con `estudios-errados`) o **Service Account** (`service_account.json`).
   - Descarga directa de archivos binarios `.xlsx` y exportación automática si son hojas nativas de Google Sheets.
2. **Mapeo Automático a Bases de Datos**:
   - `MATRIZ 3100- ALTA` $\rightarrow$ `DGEMPRES01` (Tabla: `BGD_MATRIZ_3100`)
   - `MATRIZ 3100 - CENTRO` $\rightarrow$ `DGEMPRES01` (Tabla: `BGD_MATRIZ_3100`)
   - `MATRIZ 3100 - AGUACHICA` $\rightarrow$ `DGEMPRES30` (Tabla: `BGD_MATRIZ_3100`)
   - `MATRIZ 3100 - SAN JUAN` $\rightarrow$ `DGEMPRES70` (Tabla: `BGD_MATRIZ_3100`)
   - `MATRIZ 3100 - VALLE` $\rightarrow$ `DGEMPRES80` (Tabla: `BGD_MATRIZ_3100`)
3. **Creación Dinámica de Tablas e Indexación por Fecha**:
   - Crea la tabla con los tipos de datos exactos si no existe.
   - Si la tabla ya existe, no la sobreescribe ni daña estructuras existentes.
   - Crea automáticamente un índice no agrupado sobre la columna de fecha (`fecha`).
4. **Idempotencia y Tolerancia a Fallos (Sin Duplicados)**:
   - Cada registro genera un hash criptográfico SHA-256 (`_hash_registro`).
   - Se carga a través de una tabla staging (`STG_...`) y se inserta con condición `WHERE NOT EXISTS`.
   - Si la conexión se interrumpe al 30% o 70%, al reanudar solo insertará los registros faltantes sin duplicar ni generar error.
5. **Seguridad Absoluta**:
   - No ejecuta sentencias `DROP` o `TRUNCATE` sobre tablas preexistentes.

---

## 📁 Estructura del Proyecto

```
/home/samirramirez/RPA/
├── .env                      # Variables de entorno locales
├── .env.example              # Plantilla documentada
├── requirements.txt          # Dependencias Python
├── config.py                 # Configuración y resolución de sedes/bases de datos
├── google_drive_client.py    # Integración con Google Drive API
├── spark_session.py          # Factoría PySpark con JDBC SQL Server
├── db_loader.py              # Creación de tablas, índices y carga idempotente
├── main.py                   # Script orquestador principal
├── jars/                     # Driver JDBC oficial de Microsoft (mssql-jdbc)
│   └── mssql-jdbc-12.6.1.jre11.jar
├── tests/                    # Pruebas unitarias
│   └── test_mappings.py
└── logs/                     # Logs de ejecución con fecha y hora
```

---

## ⚙️ Configuración (.env)

Edita el archivo `.env` con las credenciales correspondientes:

```ini
# SQL Server
SQL_SERVER=192.168.1.10
SQL_PORT=1433
SQL_USER=sa
SQL_PASSWORD=tu_password
SQL_ENCRYPT=false
SQL_TRUST_CERT=true

# Google OAuth2 (copiar desde estudios-errados si corresponde)
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REFRESH_TOKEN=xxx

# Carpeta en Google Drive (opcional, o busca por patrón)
GOOGLE_DRIVE_FOLDER_ID=

# Nombre de la tabla unificada en cada base de datos
TABLE_NAME=BGD_MATRIZ_3100
DATE_INDEX_COLUMN=fecha
```

---

## 🛠️ Ejecución

### Modo Simulación (Dry-Run):
Permite validar la búsqueda en Drive y mapeo de bases de datos sin modificar nada en SQL Server:
```bash
.venv/bin/python main.py --dry-run
```

### Ejecución Normal:
```bash
.venv/bin/python main.py
```

### Probar con un archivo local:
```bash
.venv/bin/python main.py --local-file "/ruta/a/MATRIZ 3100- ALTA AGOSTO (1).xlsx"
```

---

## 🧪 Pruebas

Ejecutar las pruebas unitarias:
```bash
.venv/bin/python -m unittest discover tests
```
