import os
import re
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass


@dataclass
class Config:
    # SQL Server
    SQL_SERVER: str = os.getenv("SQL_SERVER", "localhost")
    SQL_PORT: int = int(os.getenv("SQL_PORT", "1433"))
    SQL_USER: str = os.getenv("SQL_USER", "")
    SQL_PASSWORD: str = os.getenv("SQL_PASSWORD", "")
    SQL_ENCRYPT: bool = os.getenv("SQL_ENCRYPT", "false").lower() in ("true", "1", "yes")
    SQL_TRUST_CERT: bool = os.getenv("SQL_TRUST_CERT", "true").lower() in ("true", "1", "yes")

    # Google Auth (OAuth2)
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REFRESH_TOKEN: Optional[str] = os.getenv("GOOGLE_REFRESH_TOKEN")

    # Google Auth (Service Account)
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[str] = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

    # Google Drive Folder
    GOOGLE_DRIVE_FOLDER_ID: Optional[str] = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    # Spark & Naming
    TABLE_PREFIX: str = os.getenv("TABLE_PREFIX", "BGD_MATRIZ_3100_")
    DATE_INDEX_COLUMN: str = os.getenv("DATE_INDEX_COLUMN", "fecha")
    SPARK_APP_NAME: str = os.getenv("SPARK_APP_NAME", "RPA_Drive_To_SQLServer")


# Mapeo con iniciales cortas:
# alta -> A (DGEMPRES01) -> BGD_MATRIZ_3100_A
# centro -> C (DGEMPRES01) -> BGD_MATRIZ_3100_C
# aguachica -> AG (DGEMPRES30) -> BGD_MATRIZ_3100_AG
# san juan -> SJ (DGEMPRES70) -> BGD_MATRIZ_3100_SJ
# valle -> V (DGEMPRES80) -> BGD_MATRIZ_3100_V
SEDE_MAPPINGS: Dict[str, Tuple[str, str]] = {
    "alta": ("DGEMPRES01", "A"),
    "centro": ("DGEMPRES01", "C"),
    "aguachica": ("DGEMPRES30", "AG"),
    "san juan": ("DGEMPRES70", "SJ"),
    "sanjuan": ("DGEMPRES70", "SJ"),
    "valle": ("DGEMPRES80", "V"),
}


def resolve_db_and_table(filename: str, prefix: str = "BGD_MATRIZ_3100_") -> Optional[Tuple[str, str, str]]:
    """
    Dado el nombre del archivo (ej. 'MATRIZ 3100- ALTA AGOSTO (1).xlsx'),
    retorna una tupla: (database_name, table_name, sede_identificada).
    Tablas generadas con inicial corta: BGD_MATRIZ_3100_A, BGD_MATRIZ_3100_C, etc.
    """
    clean_name = filename.lower()
    
    for key, (db_name, sede_suffix) in SEDE_MAPPINGS.items():
        pattern = r"\b" + re.escape(key) + r"\b"
        if re.search(pattern, clean_name) or key in clean_name:
            pref = config.TABLE_PREFIX or prefix
            table_name = f"{pref}{sede_suffix}".upper()
            return db_name, table_name, sede_suffix
            
    return None


config = Config()
