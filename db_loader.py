import logging
import hashlib
from typing import List, Optional, Tuple
import pymssql
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StringType, IntegerType, LongType, FloatType, DoubleType,
    DateType, TimestampType, BooleanType, DataType
)
from config import config

logger = logging.getLogger("RPA.DbLoader")


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

        merge_sql = f"""
        WITH DeduplicatedStaging AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY [_mes_analisis], [CEDULA] ORDER BY [_hash_registro]) AS _rn
            FROM [dbo].[{staging_table}]
        )
        INSERT INTO [dbo].[{clean_table}] ({cols_formatted}, [_fecha_carga])
        SELECT {', '.join(select_exprs)}, GETDATE()
        FROM DeduplicatedStaging s
        WHERE s._rn = 1
          AND NOT EXISTS (
              SELECT 1 FROM [dbo].[{clean_table}] t
              WHERE t.[_mes_analisis] = s.[_mes_analisis]
                AND t.[CEDULA] = s.[CEDULA]
          );
        """

        logger.info(f"[{database}] Ejecutando sincronización idempotente hacia [dbo].[{clean_table}]...")
        cursor.execute(merge_sql)
        inserted_rows = cursor.rowcount
        logger.info(f"[{database}] Sincronización completada. Nuevos registros insertados: {inserted_rows}")

        # 3. Limpiar tabla staging
        cursor.execute(f"DROP TABLE [dbo].[{staging_table}]")
        logger.info(f"[{database}] Tabla staging [dbo].[{staging_table}] limpiada.")

        return inserted_rows

    finally:
        cursor.close()
        conn.close()
