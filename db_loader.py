import logging
import hashlib
from typing import List, Optional, Tuple
import pandas as pd
import pymssql
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StringType, IntegerType, LongType, FloatType, DoubleType,
    DateType, TimestampType, BooleanType, DataType
)
from config import config

logger = logging.getLogger("RPA.DbLoader")


def _format_sql_value(val):
    if val is None or pd.isna(val) or str(val).strip() in ('', 'None', 'nan', '<NA>'):
        return 'NULL'
    cleaned = str(val).replace("'", "''")
    return f"'{cleaned}'"


def _fast_batch_insert(cur, table_name: str, columns: List[str], rows: List[Tuple], batch_size: int = 1000):
    """
    Inserta masivamente registros en SQL Server usando bloques multi-fila VALUES en lugar de
    ejecutar sentencias individuales con executemany. Reduce el tiempo de red drásticamente.
    """
    if not rows:
        return
    cols_str = ", ".join([f"[{c}]" for c in columns])
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        values_list = []
        for r in chunk:
            row_vals = ", ".join([_format_sql_value(v) for v in r])
            values_list.append(f"({row_vals})")
        cur.execute(f"INSERT INTO {table_name} ({cols_str}) VALUES {','.join(values_list)};")


def get_mssql_connection(database: str):
    """Crea una conexión directa a SQL Server para operaciones DDL e índices."""
    return pymssql.connect(
        server=config.SQL_SERVER,
        port=config.SQL_PORT,
        user=config.SQL_USER,
        password=config.SQL_PASSWORD,
        database=database,
        autocommit=True
    )


def spark_type_to_sql_type(dt: DataType) -> str:
    """Mapea tipos de datos de Spark SQL a tipos de datos compatibles de Microsoft SQL Server."""
    if isinstance(dt, (DateType,)):
        return "DATE"
    elif isinstance(dt, (TimestampType,)):
        return "DATETIME2"
    elif isinstance(dt, (IntegerType,)):
        return "INT"
    elif isinstance(dt, (LongType,)):
        return "BIGINT"
    elif isinstance(dt, (FloatType,)):
        return "REAL"
    elif isinstance(dt, (DoubleType,)):
        return "FLOAT"
    elif isinstance(dt, (BooleanType,)):
        return "BIT"
    else:
        return "NVARCHAR(MAX)"


def sanitize_column_name(col_name: str) -> str:
    """Limpia el nombre de columna para evitar caracteres problemáticos manteniendo legibilidad."""
from data_standardizer import synchronize_table_schema, get_standard_sql_type, sanitize_column_name


def ensure_table_and_indexes(database: str, table_name: str, spark_df: DataFrame, preferred_date_col: Optional[str] = None):
    """
    Sincroniza y homologa el esquema y los índices de la tabla destino con los estándares del RPA:
    - Crea la tabla de cero si no existe (con tipos estandarizados, PK e índices).
    - Si existe, agrega nuevas columnas dinámicas y homologa columnas existentes con tipos legados.
    - Garantiza índices en todas las columnas de 'FECHA DE REALIZACION' e índice único por hash.
    """
    conn = get_mssql_connection(database)
    cursor = conn.cursor()
    try:
        incoming_cols = [f.name for f in spark_df.schema.fields]
        synchronize_table_schema(cursor, database, table_name, incoming_cols)
    finally:
        cursor.close()
        conn.close()


def add_audit_and_hash_columns(df: DataFrame, filename: str) -> DataFrame:
    """
    Agrega al DataFrame de Spark:
    - _archivo_origen: Nombre del archivo procesado
    - _hash_registro: Hash SHA-256 de todas las columnas de negocio (para control de duplicados)
    """
    if "_hash_registro" in df.columns and "_archivo_origen" in df.columns:
        return df

    business_cols = [c for c in df.columns if not c.startswith("_")]
    
    # Concatenar columnas escapadas con backticks para evitar que '.' se interprete como struct
    concat_expr = F.concat_ws("||", *[F.coalesce(F.col(f"`{c}`").cast(StringType()), F.lit("NULL")) for c in business_cols])
    
    df_with_hash = df.withColumn("_archivo_origen", F.lit(filename)) \
                     .withColumn("_hash_registro", F.sha2(concat_expr, 256))
                     
    return df_with_hash


def load_dataframe_idempotent(spark: SparkSession, df: DataFrame, database: str, table_name: str, filename: str):
    """
    Carga los datos en SQL Server de manera completamente idempotente y tolerante a fallos:
    1. Escribe el lote en una tabla staging temporal única: [dbo].[STG_{table_name}]
    2. Ejecuta un INSERT controlado con WHERE NOT EXISTS basado en [_hash_registro]
    3. Si el proceso falla a medio camino, al reejecutar continuará sin duplicar ni dar error.
    4. Elimina la tabla staging.
    """
    clean_table = sanitize_column_name(table_name)
    staging_table = f"STG_{clean_table}"
    
    # Asegurar que el DataFrame tiene las columnas de auditoría y hash
    df_prepared = add_audit_and_hash_columns(df, filename)
    
    # Verificar y preparar la tabla final e índices en SQL Server
    ensure_table_and_indexes(database, clean_table, df_prepared, config.DATE_INDEX_COLUMN)

    # Configuración JDBC para Spark
    jdbc_url = (
        f"jdbc:sqlserver://{config.SQL_SERVER}:{config.SQL_PORT};"
        f"databaseName={database};"
        f"encrypt={str(config.SQL_ENCRYPT).lower()};"
        f"trustServerCertificate={str(config.SQL_TRUST_CERT).lower()};"
    )
    
    jdbc_props = {
        "user": config.SQL_USER,
        "password": config.SQL_PASSWORD,
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver"
    }

    logger.info(f"[{database}] Escribiendo {df_prepared.count()} registros en tabla staging [dbo].[{staging_table}]...")
    
    # 1. Escribir a staging table (reemplazando cualquier staging huérfana anterior)
    (
        df_prepared.write
        .mode("overwrite")
        .jdbc(url=jdbc_url, table=f"dbo.[{staging_table}]", properties=jdbc_props)
    )
    logger.info(f"[{database}] Datos cargados en staging [dbo].[{staging_table}].")

    # 2. Inserción idempotente a la tabla destino final mediante SQL Server
    conn = get_mssql_connection(database)
    cursor = conn.cursor()

    try:
        # Obtener columnas comunes y tipos de datos entre staging y destino (case-insensitive)
        cursor.execute(f"""
            SELECT c.name, t.name as type_name
            FROM sys.columns c
            INNER JOIN sys.tables tbl ON c.object_id = tbl.object_id
            INNER JOIN sys.types t ON c.user_type_id = t.user_type_id
            WHERE tbl.name = '{clean_table}' 
              AND c.name NOT IN ('_fecha_carga')
        """)
        target_cols = {row[0].strip().lower(): (row[0], row[1].lower()) for row in cursor.fetchall()}

        cursor.execute(f"""
            SELECT c.name, t.name as type_name
            FROM sys.columns c
            INNER JOIN sys.tables tbl ON c.object_id = tbl.object_id
            INNER JOIN sys.types t ON c.user_type_id = t.user_type_id
            WHERE tbl.name = '{staging_table}'
        """)
        stg_cols = {row[0].strip().lower(): (row[0], row[1].lower()) for row in cursor.fetchall()}

        common_keys = [k for k in target_cols if k in stg_cols]
        cols_formatted = ", ".join([f"[{target_cols[k][0]}]" for k in common_keys])

        select_exprs = []
        for k in common_keys:
            target_name, t_type = target_cols[k]
            stg_name, s_type = stg_cols[k]
            if t_type in ('datetime2', 'datetime', 'date') and s_type not in ('datetime2', 'datetime', 'date'):
                select_exprs.append(f"TRY_CONVERT({t_type.upper()}, NULLIF(s.[{stg_name}], ''))")
            elif t_type in ('int', 'bigint', 'float', 'real') and s_type not in ('int', 'bigint', 'float', 'real'):
                select_exprs.append(f"TRY_CONVERT({t_type.upper()}, NULLIF(s.[{stg_name}], ''))")
            else:
                select_exprs.append(f"NULLIF(s.[{stg_name}], '')")

        # Eliminar registros previos de las cédulas que se van a insertar en el mes para permitir actualización inteligente
        merge_sql = f"""
        DELETE t
        FROM [dbo].[{clean_table}] t
        INNER JOIN [dbo].[{staging_table}] s
            ON t.[_mes_analisis] = s.[_mes_analisis]
           AND t.[CEDULA] COLLATE DATABASE_DEFAULT = s.[CEDULA] COLLATE DATABASE_DEFAULT;

        WITH DeduplicatedStaging AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY [_mes_analisis], [CEDULA] ORDER BY [_hash_registro]) AS _rn
            FROM [dbo].[{staging_table}]
        )
        INSERT INTO [dbo].[{clean_table}] ({cols_formatted}, [_fecha_carga])
        SELECT {', '.join(select_exprs)}, GETDATE()
        FROM DeduplicatedStaging s
        WHERE s._rn = 1;
        """

        logger.info(f"[{database}] Ejecutando sincronización idempotente hacia [dbo].[{clean_table}]...")
        cursor.execute(merge_sql)
        inserted_rows = cursor.rowcount
        logger.info(f"[{database}] Sincronización completada. Registros procesados/actualizados: {inserted_rows}")

        # 3. Limpiar tabla staging
        cursor.execute(f"DROP TABLE [dbo].[{staging_table}]")
        logger.info(f"[{database}] Tabla staging [dbo].[{staging_table}] limpiada.")

        return inserted_rows

    finally:
        cursor.close()
        conn.close()


def load_new_architecture_dataset(
    df_colab, 
    df_serv, 
    df_raw_courses, 
    database: str
):
    """
    Carga los datos del archivo Excel directamente en las tablas normalizadas de la nueva arquitectura:
    1. dbo.BGD_MTZ_COL (Colaboradores por Sede y Cédula)
    2. dbo.BGD_MTZ3100_SERVICIOS (Catálogo de Servicios)
    3. dbo.BGD_MTZ_CURSOS_RAW (Cursos despivoteados con marcas y fechas originales)
    """
    conn = get_mssql_connection(database)
    cur = conn.cursor()

    try:
        # 1. Asegurar tablas básicas si no existen
        import os, re
        schema_path = os.path.join(os.path.dirname(__file__), "schema_v2.sql")
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            for b in re.split(r'^\s*GO\s*$', schema_sql, flags=re.MULTILINE | re.IGNORECASE):
                clean_lines = [l for l in b.splitlines() if not l.strip().upper().startswith('USE ')]
                cb = '\n'.join(clean_lines).strip()
                if cb:
                    cur.execute(cb)

        # Asegurar catálogo de cursos e índice de obligatoriedad si están vacíos
        cur.execute("SELECT COUNT(*) FROM dbo.BGD_MTZ3100_CATCURSO")
        if cur.fetchone()[0] == 0:
            logger.info(f"[{database}] Catálogo de cursos vacío. Restaurando automáticamente catálogos normativos...")
            from seed_catalogos_v2 import seed_catalogos
            seed_catalogos(database=database)

        # 2. Upsert Servicios en dbo.BGD_MTZ3100_SERVICIOS (primero para satisfacer FK)
        if not df_serv.empty:
            logger.info(f"[{database}] Sincronizando {len(df_serv)} servicios en dbo.BGD_MTZ3100_SERVICIOS...")
            serv_tuples = [(row["COD_SERVICIO"], row["NOMBRE_SERVICIO"]) for _, row in df_serv.iterrows()]
            cur.execute("""
                CREATE TABLE #TmpServ (COD_SERVICIO VARCHAR(10), NOMBRE_SERVICIO NVARCHAR(150));
            """)
            _fast_batch_insert(cur, "#TmpServ", ["COD_SERVICIO", "NOMBRE_SERVICIO"], serv_tuples)
            cur.execute("""
                MERGE dbo.BGD_MTZ3100_SERVICIOS AS t
                USING #TmpServ AS s
                ON (t.COD_SERVICIO COLLATE DATABASE_DEFAULT = s.COD_SERVICIO COLLATE DATABASE_DEFAULT)
                WHEN MATCHED THEN
                    UPDATE SET 
                        t.NOMBRE_SERVICIO = s.NOMBRE_SERVICIO,
                        t.[FECHA CARGA] = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (COD_SERVICIO, NOMBRE_SERVICIO, CATEGORIA, ESTADO, [FECHA CARGA])
                    VALUES (s.COD_SERVICIO, s.NOMBRE_SERVICIO, 'GENERAL', 'ACTIVO', SYSUTCDATETIME());
                DROP TABLE #TmpServ;
            """)

        # 3. Upsert Colaboradores en dbo.BGD_MTZ_COL
        if not df_colab.empty:
            logger.info(f"[{database}] Sincronizando {len(df_colab)} colaboradores en dbo.BGD_MTZ_COL...")
            colab_tuples = [
                (
                    row["CEDULA"], row["SEDE"], row["NOMBRE_COLABORADOR"],
                    row["CODIGO"], row["ESTADO"], row["CARGO"],
                    row["COD_SERVICIO"], row["JEFE INMEDIATO"]
                )
                for _, row in df_colab.iterrows()
            ]
            cur.execute("""
                CREATE TABLE #TmpColab (
                    CEDULA NVARCHAR(12), SEDE VARCHAR(50), NOMBRE_COLABORADOR NVARCHAR(200),
                    CODIGO NVARCHAR(50), ESTADO NVARCHAR(50), CARGO NVARCHAR(150),
                    COD_SERVICIO VARCHAR(10), JEFE_INMEDIATO NVARCHAR(200)
                );
            """)
            _fast_batch_insert(
                cur, "#TmpColab",
                ["CEDULA", "SEDE", "NOMBRE_COLABORADOR", "CODIGO", "ESTADO", "CARGO", "COD_SERVICIO", "JEFE_INMEDIATO"],
                colab_tuples
            )

            # Auto-provisionar cualquier servicio presente en colaboradores que no estuviera en el catálogo para no violar FK
            cur.execute("""
                INSERT INTO dbo.BGD_MTZ3100_SERVICIOS (COD_SERVICIO, NOMBRE_SERVICIO, CATEGORIA, ESTADO, [FECHA CARGA])
                SELECT DISTINCT s.COD_SERVICIO, 'SERVICIO ' + s.COD_SERVICIO, 'GENERAL', 'ACTIVO', SYSUTCDATETIME()
                FROM #TmpColab s
                WHERE s.COD_SERVICIO IS NOT NULL AND RTRIM(LTRIM(s.COD_SERVICIO)) <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM dbo.BGD_MTZ3100_SERVICIOS serv
                      WHERE serv.COD_SERVICIO COLLATE DATABASE_DEFAULT = s.COD_SERVICIO COLLATE DATABASE_DEFAULT
                  );
            """)
            
            cur.execute("""
                MERGE dbo.BGD_MTZ_COL AS t
                USING #TmpColab AS s
                ON (t.CEDULA COLLATE DATABASE_DEFAULT = s.CEDULA COLLATE DATABASE_DEFAULT 
                    AND t.SEDE COLLATE DATABASE_DEFAULT = s.SEDE COLLATE DATABASE_DEFAULT)
                WHEN MATCHED THEN
                    UPDATE SET 
                        t.NOMBRE_COLABORADOR = s.NOMBRE_COLABORADOR,
                        t.CODIGO = s.CODIGO,
                        t.ESTADO = s.ESTADO,
                        t.CARGO = s.CARGO,
                        t.COD_SERVICIO = s.COD_SERVICIO,
                        t.[JEFE INMEDIATO] = s.JEFE_INMEDIATO,
                        t.[FECHA CARGA] = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (CEDULA, SEDE, NOMBRE_COLABORADOR, CODIGO, ESTADO, CARGO, COD_SERVICIO, [JEFE INMEDIATO], [FECHA CARGA])
                    VALUES (s.CEDULA, s.SEDE, s.NOMBRE_COLABORADOR, s.CODIGO, s.ESTADO, s.CARGO, s.COD_SERVICIO, s.JEFE_INMEDIATO, SYSUTCDATETIME());
                DROP TABLE #TmpColab;
            """)

        # 4. Inserción directa de cursos obligatorios en dbo.BGD_MTZ3100_DASH (sin tabla intermedia RAW)
        if not df_raw_courses.empty:
            logger.info(f"[{database}] Procesando {len(df_raw_courses)} cursos e insertando directamente en dbo.BGD_MTZ3100_DASH...")
            raw_tuples = [
                (
                    row["MES_ANALISIS"], row["SEDE"], row["CEDULA"],
                    row["CURSO_ID"], row["CURSO_NOMBRE"], row["MARCA_ORIGEN"],
                    row["FECHA_REAL_ORIGEN"], row["FECHA_VENC_ORIGEN"],
                    row["LECTURA"], row["_archivo_origen"]
                )
                for _, row in df_raw_courses.iterrows()
            ]
            cur.execute("""
                CREATE TABLE #TmpCursosRaw (
                    MES_ANALISIS VARCHAR(10), SEDE VARCHAR(50), CEDULA NVARCHAR(12),
                    CURSO_ID VARCHAR(10), CURSO_NOMBRE NVARCHAR(150), MARCA_ORIGEN VARCHAR(20),
                    FECHA_REAL_ORIGEN DATE, FECHA_VENC_ORIGEN DATE, LECTURA VARCHAR(20),
                    _archivo_origen NVARCHAR(255)
                );
            """)
            
            _fast_batch_insert(
                cur, "#TmpCursosRaw",
                [
                    "MES_ANALISIS", "SEDE", "CEDULA", "CURSO_ID", "CURSO_NOMBRE",
                    "MARCA_ORIGEN", "FECHA_REAL_ORIGEN", "FECHA_VENC_ORIGEN",
                    "LECTURA", "_archivo_origen"
                ],
                raw_tuples,
                batch_size=1000
            )

            cur.execute("CREATE CLUSTERED INDEX CIX_TmpCursosRaw ON #TmpCursosRaw (CEDULA, CURSO_ID);")

            cur.execute("""
                ;WITH EvaluacionBase AS (
                    SELECT 
                        r.MES_ANALISIS,
                        r.SEDE,
                        r.CEDULA,
                        c.NOMBRE_COLABORADOR,
                        c.COD_SERVICIO,
                        serv.NOMBRE_SERVICIO,
                        c.CARGO,
                        r.CURSO_ID,
                        cat.CURSO_NOMBRE AS CAT_CURSO_NOMBRE,
                        r.MARCA_ORIGEN,
                        r.FECHA_REAL_ORIGEN,
                        r.FECHA_VENC_ORIGEN,
                        ISNULL(r.LECTURA, 'OK') AS LECTURA,
                        cat.VIGENCIA_MESES,
                        aud.ID AS ID_AUDITORIA,
                        aud.MOTIVO AS MOTIVO_AUDITORIA,
                        dt.VENC_EFECTIVO,
                        dt.REAL_EFECTIVA,
                        obl.ES_OBLIGATORIO,
                        fc.FECHA_CORTE
                    FROM #TmpCursosRaw r
                    INNER JOIN dbo.BGD_MTZ_COL c
                        ON c.CEDULA COLLATE DATABASE_DEFAULT = r.CEDULA COLLATE DATABASE_DEFAULT
                       AND c.SEDE COLLATE DATABASE_DEFAULT = r.SEDE COLLATE DATABASE_DEFAULT
                    LEFT JOIN dbo.BGD_MTZ3100_SERVICIOS serv
                        ON serv.COD_SERVICIO COLLATE DATABASE_DEFAULT = c.COD_SERVICIO COLLATE DATABASE_DEFAULT
                    INNER JOIN dbo.BGD_MTZ3100_CATCURSO cat
                        ON cat.ID_CURSO COLLATE DATABASE_DEFAULT = r.CURSO_ID COLLATE DATABASE_DEFAULT
                    CROSS APPLY (
                        SELECT EOMONTH(CONVERT(DATE, r.MES_ANALISIS + '-01')) AS FECHA_CORTE
                    ) fc
                    LEFT JOIN dbo.BGD_MTZ3100_AUDITORIA aud
                        ON aud.CEDULA_COLABORADOR COLLATE DATABASE_DEFAULT = r.CEDULA COLLATE DATABASE_DEFAULT
                       AND aud.CURSO_ID COLLATE DATABASE_DEFAULT = r.CURSO_ID COLLATE DATABASE_DEFAULT
                       AND aud._activo = 1
                    LEFT JOIN dbo.BGD_MTZ_ALIAS_CARGOS al
                        ON al.CARGO_EN_MATRIZ COLLATE Modern_Spanish_CI_AI = c.CARGO COLLATE Modern_Spanish_CI_AI
                    CROSS APPLY (
                        SELECT 
                            COALESCE(NULLIF(al.CARGO_EN_INDICE, ''), c.CARGO) AS CARGO_NORMATIVO,
                            ISNULL(al.EXCLUIDO, 0) AS CARGO_EXCLUIDO
                    ) h
                    CROSS APPLY (
                        SELECT 
                            CASE 
                                -- Si el cargo está marcado como EXCLUIDO en la tabla de alias (ej. Psicología, Nutrición)
                                WHEN h.CARGO_EXCLUIDO = 1 THEN 0

                                -- Si el cargo figura en la matriz de obligatoriedad
                                WHEN EXISTS (
                                    SELECT 1 
                                    FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD ind
                                    WHERE ind.ESTADO = 'ACTIVO'
                                      AND (
                                          ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                                          OR ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO + ' AC' COLLATE Modern_Spanish_CI_AI
                                      )
                                ) THEN
                                    CASE 
                                        WHEN EXISTS (
                                            SELECT 1 
                                            FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD ind
                                            WHERE ind.ESTADO = 'ACTIVO'
                                              AND (
                                                  ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                                                  OR ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO + ' AC' COLLATE Modern_Spanish_CI_AI
                                              )
                                              AND (
                                                  ind.COD_CURSO COLLATE Modern_Spanish_CI_AI = cat.CURSO_NOMBRE COLLATE Modern_Spanish_CI_AI
                                                  OR ind.COD_CURSO COLLATE Modern_Spanish_CI_AI = r.CURSO_NOMBRE COLLATE Modern_Spanish_CI_AI
                                              )
                                              AND (
                                                  ind.CODIGOS_SERVICIO = 'TODOS'
                                                  OR (
                                                      c.COD_SERVICIO IS NOT NULL AND c.COD_SERVICIO <> ''
                                                      AND (
                                                          ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + c.COD_SERVICIO + ';%'
                                                          OR (TRY_CAST(c.COD_SERVICIO AS INT) IS NOT NULL 
                                                              AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + RIGHT('0000' + CAST(TRY_CAST(c.COD_SERVICIO AS INT) AS VARCHAR(10)), 4) + ';%')
                                                          OR (TRY_CAST(c.COD_SERVICIO AS INT) IS NOT NULL 
                                                              AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + CAST(TRY_CAST(c.COD_SERVICIO AS INT) AS VARCHAR(10)) + ';%')
                                                      )
                                                  )
                                              )
                                        ) THEN 1
                                        ELSE 0
                                    END
                                ELSE
                                    CASE 
                                        WHEN r.MARCA_ORIGEN IN ('SI', 'NO') THEN 1
                                        ELSE 0
                                    END
                            END AS ES_OBLIGATORIO
                    ) obl
                    CROSS APPLY (
                        SELECT 
                            COALESCE(aud.FECHA_VENC_NEW, r.FECHA_VENC_ORIGEN, 
                                     CASE WHEN cat.VIGENCIA_MESES > 0 AND COALESCE(aud.FECHA_REAL_NEW, r.FECHA_REAL_ORIGEN) IS NOT NULL 
                                          THEN DATEADD(month, cat.VIGENCIA_MESES, COALESCE(aud.FECHA_REAL_NEW, r.FECHA_REAL_ORIGEN)) 
                                          ELSE NULL END
                            ) AS VENC_EFECTIVO,
                            COALESCE(aud.FECHA_REAL_NEW, r.FECHA_REAL_ORIGEN) AS REAL_EFECTIVA
                    ) dt
                ),
                EvaluacionSituaciones AS (
                    SELECT 
                        eb.*,
                        CASE 
                            WHEN eb.ES_OBLIGATORIO = 0 THEN 1
                            WHEN eb.ID_AUDITORIA IS NOT NULL THEN
                                CASE 
                                    WHEN eb.VENC_EFECTIVO < eb.FECHA_CORTE THEN 5
                                    WHEN eb.VENC_EFECTIVO < DATEADD(day, 90, eb.FECHA_CORTE) THEN 3
                                    ELSE 2
                                END
                            WHEN eb.LECTURA = 'SIN_COLUMNA' THEN 9
                            WHEN eb.VENC_EFECTIVO IS NULL AND eb.REAL_EFECTIVA IS NULL THEN 
                                CASE 
                                    WHEN eb.MARCA_ORIGEN IN ('SI', 'S') THEN 6
                                    WHEN eb.MARCA_ORIGEN IN ('N/A', 'NA') THEN 8
                                    ELSE 7
                                END
                            WHEN eb.VENC_EFECTIVO < eb.FECHA_CORTE THEN 
                                CASE 
                                    WHEN eb.MARCA_ORIGEN IN ('SI', 'S') THEN 4
                                    ELSE 5
                                END
                            ELSE 
                                CASE 
                                    WHEN eb.MARCA_ORIGEN IN ('NO', 'N') THEN 10
                                    WHEN eb.VENC_EFECTIVO < DATEADD(day, 90, eb.FECHA_CORTE) THEN 3
                                    ELSE 2
                                END
                        END AS SITUACION_NUM
                    FROM EvaluacionBase eb
                ),
                FiltradosObligatorios AS (
                    SELECT 
                        MES_ANALISIS,
                        CEDULA,
                        NOMBRE_COLABORADOR,
                        COD_SERVICIO,
                        NOMBRE_SERVICIO,
                        SEDE,
                        CURSO_ID,
                        CAT_CURSO_NOMBRE AS CURSO_NOMBRE,
                        MARCA_ORIGEN,
                        FECHA_REAL_ORIGEN,
                        FECHA_VENC_ORIGEN,
                        LECTURA,
                        'SI' AS OBLIGATORIO,
                        VIGENCIA_MESES,
                        VENC_EFECTIVO,
                        REAL_EFECTIVA,
                        CASE 
                            WHEN SITUACION_NUM IN (2, 10) THEN 'VIGENTE'
                            WHEN SITUACION_NUM = 3 THEN 'POR VENCER'
                            WHEN SITUACION_NUM IN (4, 5) THEN 'VENCIDO'
                            WHEN SITUACION_NUM = 6 THEN 'CUMPLE SIN FECHA'
                            WHEN SITUACION_NUM IN (7, 8) THEN 'NO REALIZADO'
                            WHEN SITUACION_NUM = 9 THEN 'SIN COLUMNA EN SEDE'
                            ELSE 'NO APLICA'
                        END AS ESTADO_DETALLADO,
                        CASE 
                            WHEN SITUACION_NUM IN (2, 3, 6, 10) THEN 'SI'
                            ELSE 'NO'
                        END AS MARCA,
                        CASE 
                            WHEN VENC_EFECTIVO IS NOT NULL THEN DATEDIFF(day, FECHA_CORTE, VENC_EFECTIVO)
                            ELSE NULL
                        END AS DIAS_PARA_VENCER,
                        CASE 
                            WHEN SITUACION_NUM IN (2, 3, 6, 10) THEN 1
                            ELSE 0
                        END AS CUENTA_INDICADOR,
                        CASE 
                            WHEN ID_AUDITORIA IS NOT NULL THEN 'SUBSANADO_AUDITORIA'
                            WHEN SITUACION_NUM = 3 THEN 'ALERTA_POR_VENCER'
                            WHEN SITUACION_NUM = 4 THEN 'MARCA_DESACTUALIZADA'
                            WHEN SITUACION_NUM = 6 THEN 'FALTA_FECHA'
                            WHEN SITUACION_NUM = 8 THEN 'DISCREPANCIA_APLICABILIDAD'
                            WHEN SITUACION_NUM = 9 THEN 'SIN_COLUMNA'
                            WHEN SITUACION_NUM = 10 THEN 'MARCA_DESACTUALIZADA'
                            ELSE NULL
                        END AS ALERTA,
                        CASE 
                            WHEN ID_AUDITORIA IS NOT NULL THEN CONCAT('Subsanado en Auditoría: ', MOTIVO_AUDITORIA)
                            WHEN SITUACION_NUM = 3 THEN 'Suma al indicador pero se lista para gestión preventiva'
                            WHEN SITUACION_NUM = 4 THEN 'La sede tenía SI pero el curso ya venció'
                            WHEN SITUACION_NUM = 6 THEN 'Suma al indicador pero requiere solicitud de soporte a la sede'
                            WHEN SITUACION_NUM = 8 THEN 'La sede indicó N/A pero la norma lo exige'
                            WHEN SITUACION_NUM = 9 THEN 'La sede no registra este curso; no puede evaluarse cumplimiento'
                            WHEN SITUACION_NUM = 10 THEN 'La sede marcó NO pero la fecha registrada indica vigencia'
                            ELSE NULL
                        END AS OBSERVACION,
                        ID_AUDITORIA AS SUBSANADO_CONTROL_CALIDAD,
                        SYSUTCDATETIME() AS FECHA_CALCULO
                    FROM EvaluacionSituaciones
                    WHERE SITUACION_NUM <> 1 -- Solo cursos obligatorios
                )
                MERGE dbo.BGD_MTZ3100_DASH AS t
                USING FiltradosObligatorios AS s
                ON (t.MES_ANALISIS = s.MES_ANALISIS 
                    AND t.SEDE COLLATE DATABASE_DEFAULT = s.SEDE COLLATE DATABASE_DEFAULT
                    AND t.CEDULA COLLATE DATABASE_DEFAULT = s.CEDULA COLLATE DATABASE_DEFAULT
                    AND t.CURSO_ID COLLATE DATABASE_DEFAULT = s.CURSO_ID COLLATE DATABASE_DEFAULT)
                WHEN MATCHED THEN
                    UPDATE SET 
                        t.NOMBRE_COLABORADOR = s.NOMBRE_COLABORADOR,
                        t.COD_SERVICIO = s.COD_SERVICIO,
                        t.NOMBRE_SERVICIO = s.NOMBRE_SERVICIO,
                        t.CURSO_NOMBRE = s.CURSO_NOMBRE,
                        t.MARCA_ORIGEN = s.MARCA_ORIGEN,
                        t.FECHA_REAL_ORIGEN = s.FECHA_REAL_ORIGEN,
                        t.FECHA_VENC_ORIGEN = s.FECHA_VENC_ORIGEN,
                        t.LECTURA = s.LECTURA,
                        t.OBLIGATORIO = s.OBLIGATORIO,
                        t.VIGENCIA_MESES = s.VIGENCIA_MESES,
                        t.VENC_EFECTIVO = s.VENC_EFECTIVO,
                        t.REAL_EFECTIVA = s.REAL_EFECTIVA,
                        t.ESTADO_DETALLADO = s.ESTADO_DETALLADO,
                        t.MARCA = s.MARCA,
                        t.DIAS_PARA_VENCER = s.DIAS_PARA_VENCER,
                        t.CUENTA_INDICADOR = s.CUENTA_INDICADOR,
                        t.ALERTA = s.ALERTA,
                        t.OBSERVACION = s.OBSERVACION,
                        t.SUBSANADO_CONTROL_CALIDAD = s.SUBSANADO_CONTROL_CALIDAD,
                        t.FECHA_CALCULO = s.FECHA_CALCULO
                WHEN NOT MATCHED THEN
                    INSERT (
                        MES_ANALISIS, CEDULA, NOMBRE_COLABORADOR, COD_SERVICIO, NOMBRE_SERVICIO, SEDE, MULTISEDE,
                        CURSO_ID, CURSO_NOMBRE, MARCA_ORIGEN, FECHA_REAL_ORIGEN, FECHA_VENC_ORIGEN,
                        LECTURA, OBLIGATORIO, VIGENCIA_MESES, VENC_EFECTIVO, REAL_EFECTIVA,
                        ESTADO_DETALLADO, MARCA, DIAS_PARA_VENCER, CUENTA_INDICADOR,
                        ALERTA, OBSERVACION, SUBSANADO_CONTROL_CALIDAD, FECHA_CALCULO
                    ) VALUES (
                        s.MES_ANALISIS, s.CEDULA, s.NOMBRE_COLABORADOR, s.COD_SERVICIO, s.NOMBRE_SERVICIO, s.SEDE, 'NO',
                        s.CURSO_ID, s.CURSO_NOMBRE, s.MARCA_ORIGEN, s.FECHA_REAL_ORIGEN, s.FECHA_VENC_ORIGEN,
                        s.LECTURA, s.OBLIGATORIO, s.VIGENCIA_MESES, s.VENC_EFECTIVO, s.REAL_EFECTIVA,
                        s.ESTADO_DETALLADO, s.MARCA, s.DIAS_PARA_VENCER, s.CUENTA_INDICADOR,
                        s.ALERTA, s.OBSERVACION, s.SUBSANADO_CONTROL_CALIDAD, s.FECHA_CALCULO
                    );

                -- Actualizar Multisede
                ;WITH MultisedeCheck AS (
                    SELECT CEDULA FROM dbo.BGD_MTZ_COL GROUP BY CEDULA HAVING COUNT(DISTINCT SEDE) > 1
                )
                UPDATE d
                SET d.MULTISEDE = 'SI'
                FROM dbo.BGD_MTZ3100_DASH d
                INNER JOIN MultisedeCheck m
                    ON m.CEDULA COLLATE DATABASE_DEFAULT = d.CEDULA COLLATE DATABASE_DEFAULT;

                DROP TABLE #TmpCursosRaw;
            """)
            logger.info(f"[{database}] Sincronización directa en dbo.BGD_MTZ3100_DASH finalizada exitosamente.")

    finally:
        cur.close()
        conn.close()
