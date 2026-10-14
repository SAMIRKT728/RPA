import os
import logging
from pyspark.sql import SparkSession
from config import config

logger = logging.getLogger("RPA.SparkSession")

JAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jars")
LOCAL_JDBC_JAR = os.path.join(JAR_DIR, "mssql-jdbc-12.6.1.jre11.jar")
MAVEN_COORDINATE = "com.microsoft.sqlserver:mssql-jdbc:12.6.1.jre11"


def get_spark_session() -> SparkSession:
    """
    Crea o reutiliza la sesión de PySpark configurada para conectar a SQL Server.
    Prioriza el JAR local de mssql-jdbc si existe, de lo contrario lo descarga de Maven.
    """
    builder = (
        SparkSession.builder
        .appName(config.SPARK_APP_NAME)
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config("spark.sql.session.timeZone", "America/Bogota")
    )

    if os.path.exists(LOCAL_JDBC_JAR):
        logger.info(f"Cargando JDBC Driver local: {LOCAL_JDBC_JAR}")
        builder = builder.config("spark.jars", LOCAL_JDBC_JAR) \
                         .config("spark.driver.extraClassPath", LOCAL_JDBC_JAR)
    else:
        logger.info(f"Configurando JDBC Driver vía Maven: {MAVEN_COORDINATE}")
        builder = builder.config("spark.jars.packages", MAVEN_COORDINATE)

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
