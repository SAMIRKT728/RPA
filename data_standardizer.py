"""
data_standardizer.py
Módulo centralizado para la estandarización, homologación de esquemas y limpieza
automática de datos entre las matrices de Excel (Google Drive) y Microsoft SQL Server.
"""

import re
import hashlib
import logging
from datetime import datetime
from typing import Optional, Set, Dict, Any, List
import pandas as pd

logger = logging.getLogger("RPA.DataStandardizer")

# ==============================================================================
# 1. CATÁLOGO ESTÁNDAR DE TIPOS DE DATOS (SQL SERVER)
# ==============================================================================

# Columnas Core de Identificación y Organización
STANDARD_CORE_TYPES: Dict[str, str] = {
    "_mes_analisis": "VARCHAR(10)",
    "CEDULA": "NVARCHAR(12)",
    "NOMBRE DEL EMPLEADO": "NVARCHAR(200)",
    "CODIGO": "NVARCHAR(50)",
    "ESTADO": "NVARCHAR(50)",
    "CARGO": "NVARCHAR(150)",
    "COD_SERVICIO": "VARCHAR(10)",
    "SERVICIO": "NVARCHAR(150)",
    "JEFE INMEDIATO": "NVARCHAR(200)",
    
    # Columnas de Control e Idempotencia del RPA
    "_hash_registro": "CHAR(64)",
    "_fecha_carga": "DATETIME",
    "_archivo_origen": "NVARCHAR(255)"
}

# Longitudes máximas para recorte seguro de cadenas
MAX_LENGTH_BY_COLUMN: Dict[str, int] = {
    "_mes_analisis": 10,
    "CEDULA": 12,
    "NOMBRE DEL EMPLEADO": 200,
    "CODIGO": 50,
    "ESTADO": 50,
    "CARGO": 150,
    "COD_SERVICIO": 10,
    "SERVICIO": 150,
    "JEFE INMEDIATO": 200,
    "_archivo_origen": 255
}

# Catálogo de Cursos Conocidos (Marcas SI / NO / Vacío)
STANDARD_COURSES: Set[str] = {
    "BLS",
    "ACLS",
    "PALS",
    "NALS",
    "AIEPI",
    "POCT",
    "DENGUE",
    "HUMANIZACION",
    "GESTION DEL DUELO",
    "ATENCION A LAS VICTIMAS DE ATAQUES QUIMICOS",
    "ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL",
    "GESTION OPERATIVA DE LA DONACION",
    "MANEJO DEL DOLOR Y CUIDADOS PALIATIVOS",
    "INMUNOLOGÍA DE TRANSPLANTES",
    "GESTIÓN PRE-TRANSFUCIONAL",
    "ADMINISTRACIÓN DE MEDICAMENTOS",
    "TOMA DE MUESTRAS",
    "CADENA DE FRIO",
    "ATENCIÓN DEL PACIENTE EN DIÁLISIS RENAL - DIALISIS",
    "ASESORIA PRE TEST POST TEST HIV",
    "OVEM - COVE",
    "DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO",
    "DIPLOMADO ONCO - HEMATOLOGÍA PEDIATRICA",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO",
    "DIPLOMADO URGENCIAS",
    "CURSO DE SEGURIDAD DEL PACIENTE",
    "DIPLOMADO EN NEFROLOGÍA"
}

# ==============================================================================
# 2. DETECCIÓN DINÁMICA DE TIPOS PARA NUEVAS COLUMNAS
# ==============================================================================

def sanitize_column_name(col_name: str) -> str:
    """Limpia el nombre de columna eliminando corchetes, puntos y normalizando espacios."""
    c = str(col_name).strip().replace("[", "").replace("]", "").replace(".", "_")
    return re.sub(r"\s+", " ", c)


def is_date_column(col_name: str) -> bool:
    """Determina si un nombre de columna corresponde a un campo de fecha."""
    name_clean = col_name.strip().upper()
    date_keywords = ["FECHA", "FEC", "DATE", "REALIZACION", "VENCIMIENTO"]
    return any(k in name_clean for k in date_keywords)


def is_course_column(col_name: str) -> bool:
    """Determina si la columna corresponde a un curso o certificación."""
    name_upper = col_name.strip().upper()
    if name_upper in STANDARD_COURSES:
        return True
    course_keywords = ["DIPLOMADO", "CURSO", "TALLER", "CERTIFICACION", "CAPACITACION", "INDUCCION"]
    return any(k in name_upper for k in course_keywords)


def get_standard_sql_type(col_name: str) -> str:
    """
    Retorna el tipo de dato SQL Server óptimo y estandarizado para cualquier columna.
    Soporta dinámicamente nuevas columnas evitando rigurosamente NVARCHAR(MAX).
    """
    clean_name = col_name.strip().upper()

    # 1. Coincidencia exacta en catálogo Core
    if clean_name in STANDARD_CORE_TYPES:
        return STANDARD_CORE_TYPES[clean_name]

    # 2. Fechas de Realización / Vencimiento
    if is_date_column(clean_name):
        return "DATETIME2"

    # 3. Cursos (SI_V / NO_R / SIN_REGISTRO_N / etc.)
    if is_course_column(clean_name):
        return "VARCHAR(20)"

    # 4. Reglas semánticas por palabra clave
    if "CEDULA" in clean_name or "DOCUMENTO" in clean_name:
        return "NVARCHAR(12)"
    if "NOMBRE" in clean_name or "JEFE" in clean_name:
        return "NVARCHAR(200)"
    if "CARGO" in clean_name or "PUESTO" in clean_name:
        return "NVARCHAR(150)"
    if "CENTRO" in clean_name and "COSTO" in clean_name:
        return "NVARCHAR(100)"

    # 5. Fallback para columnas nuevas no categorizadas (acotado, nunca MAX)
    return "NVARCHAR(200)"


# ==============================================================================
# 3. FUNCIONES DE LIMPIEZA ATÓMICA DE VALORES Y EXTRACCIÓN DE ESTILOS
# ==============================================================================

def select_best_worksheet(wb) -> Any:
    """
    Selecciona inteligentemente la hoja que contiene la matriz 3100 principal.
    Prioriza hojas con columnas de cursos y personal, descartando hojas de indicadores o portadas.
    """
    best_sheet = None
    max_score = -1

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        first_row = next(ws.iter_rows(values_only=True), None)
        if not first_row:
            continue
        headers_upper = [str(c).upper() for c in first_row if c is not None]
        score = sum(1 for h in headers_upper if any(k in h for k in ("BLS", "ACLS", "PALS", "NALS", "CURSO", "DIPLOMADO")))
        if any("CEDULA" in h or "DOCUMENTO" in h or "EMPLEADO" in h for h in headers_upper):
            score += 10
        if sheet_name.strip().upper() in ("3100", "AG", "MATRIZ", "CURSOS 3100", "ASISTENCIALES"):
            score += 5
        if "INDICADOR" in sheet_name.strip().upper() or "PORCENTAJE" in sheet_name.strip().upper():
            score -= 10

        if score > max_score:
            max_score = score
            best_sheet = ws

    return best_sheet if best_sheet is not None else wb.active


def read_excel_with_styles(buffer_or_path: Any, filename: str = "") -> pd.DataFrame:
    """
    Lee un archivo Excel extrayendo directamente los valores de las celdas de la matriz principal,
    omitiendo cualquier validación o interpretación de colores y estilos visuales.
    """
    import openpyxl
    wb = openpyxl.load_workbook(buffer_or_path, data_only=True, read_only=True)
    ws = select_best_worksheet(wb)
    
    rows_iter = ws.iter_rows(values_only=True)
    first_row = next(rows_iter, None)
    if not first_row:
        wb.close()
        return pd.DataFrame()

    headers = [str(c).strip() if c is not None else "" for c in first_row]
    # Recortar columnas vacías al final (evita miles de columnas espurias por formato extendido)
    while headers and not headers[-1]:
        headers.pop()
    num_cols = len(headers)

    data = []
    for r in rows_iter:
        if any(c is not None and str(c).strip() != "" for c in r[:num_cols]):
            data.append(r[:num_cols])
    wb.close()

    if filename:
        logger.info(f"Hoja seleccionada para '{filename}': '{ws.title}' ({len(data)} filas, {num_cols} columnas).")

    return pd.DataFrame(data, columns=headers)


def clean_cedula_value(val: Any) -> Optional[str]:
    """
    Normaliza el campo CÉDULA:
    - Remueve '.0' si vino como número flotante de Excel (ej. 1065900742.0 -> 1065900742)
    - Remueve espacios en blanco
    - Limita a máximo 12 caracteres
    - Retorna None si es nulo, vacío, 'nan' o '0'
    """
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip()
    if val_str.endswith(".0"):
        val_str = val_str[:-2].strip()
    if val_str.lower() in ("", "nan", "none", "null", "0", "-"):
        return None
    return val_str[:12]


def clean_course_value(val: Any) -> Optional[str]:
    """
    Normaliza el valor de un curso directamente por su contenido textual, sin colores:
    - 'SI': Cumplido / Realizado
    - 'NO': No realizado / Pendiente
    - 'N/A': No aplica
    - 'SIN REGISTRO': Exigido sin registro
    - None: Vacío
    """
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip().upper()
    if val_str in ("SI", "SÍ", "S", "1", "1.0", "TRUE", "SI_V", "S_V"):
        return "SI"
    elif val_str in ("NO", "N", "0", "0.0", "FALSE", "NO_R", "N_R"):
        return "NO"
    elif val_str in ("SIN_REGISTRO_N", "SR_N", "SIN REGISTRO", "SIN_REGISTRO"):
        return "SIN REGISTRO"
    elif val_str in ("NA_G", "N/A_G", "N/A", "NA", "NO APLICA", "-"):
        return "N/A"
    return val_str[:20]


def clean_date_value(val: Any) -> Optional[str]:
    """
    Normaliza campos de fecha para SQL Server DATETIME2:
    - Maneja números seriales de Excel (ej. 44521.0 -> 2021-11-18)
    - Maneja cadenas con formatos de fecha habituales (DD/MM/YYYY, YYYY-MM-DD)
    - Maneja objetos datetime / Timestamp nativos
    - Retorna formato ISO 'YYYY-MM-DD HH:MM:SS' o None si es inválido
    """
    if pd.isna(val) or val is None:
        return None

    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d %H:%M:%S")

    val_str = str(val).strip()
    if val_str.lower() in ("", "nan", "none", "null", "n/a", "no aplica", "-", "0", "0.0"):
        return None

    # Caso 1: Serial numérico de Excel (típico entre los años 1982 y 2064: 30000 - 65000)
    try:
        f_val = float(val)
        if 20000 <= f_val <= 65000:
            dt = pd.to_datetime(f_val, unit="D", origin="1899-12-30")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        pass

    # Caso 2: Cadena de texto interpretable como fecha
    try:
        dt = pd.to_datetime(val_str, errors="coerce", format="mixed")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return None


def clean_cargo_value(val: Any) -> Optional[str]:
    """Limpia y estandariza el cargo removiendo sufijos de sede (AC, MC, AG, VL, SJ)."""
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip().upper()
    val_str = re.sub(r"\b(AC|MC|AG|VL|SJ)\b", "", val_str)
    val_str = re.sub(r"\s+", " ", val_str).strip()
    return val_str[:150] if val_str else None


def parse_centro_costo(val: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Separa el código del servicio y nombre del servicio desde la columna Centro de Costo.
    Ej: 'AG 0044 - AG-HOSPITALIZACION SEXTO PISO A' -> ('0044', 'HOSPITALIZACION SEXTO PISO A')
    """
    if pd.isna(val) or val is None:
        return None, None
    val_str = str(val).strip()
    # Patrón 1: [SEDE] [CODIGO] - [SEDE]-[NOMBRE]
    m = re.match(r"^(?:[A-Z]{2,4}\s+)?(\d{3,5})\s*-\s*(?:[A-Z]{2,4}-)?(.*)$", val_str, re.IGNORECASE)
    if m:
        cod = m.group(1).strip().zfill(4)
        serv = re.sub(r"\s+", " ", m.group(2)).strip().upper()
        return cod[:10], serv[:150]
    # Patrón 2: [SEDE] [CODIGO] [NOMBRE]
    m2 = re.match(r"^(?:[A-Z]{2,4}\s+)?(\d{3,5})\s+(.*)$", val_str, re.IGNORECASE)
    if m2:
        cod = m2.group(1).strip().zfill(4)
        serv = re.sub(r"\s+", " ", m2.group(2)).strip().upper()
        return cod[:10], serv[:150]
    return None, val_str[:150]


def clean_text_value(val: Any, max_len: int = 200) -> Optional[str]:
    """Limpia textos generales removiendo espacios redundantes y recortando a longitud segura."""
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip()
    if val_str.lower() in ("", "nan", "none", "null"):
        return None
    val_str = re.sub(r"\s+", " ", val_str)
    return val_str[:max_len]


# ==============================================================================
# 4. PROCESAMIENTO Y ESTANDARIZACIÓN COMPLETA DEL DATAFRAME
# ==============================================================================

def clean_and_standardize_dataframe(df_raw: pd.DataFrame, filename: str, mes_analisis: Optional[str] = None) -> pd.DataFrame:
    """
    Aplica la estandarización integral de esquema y contenido:
    1. Normaliza y des-duplica nombres de columnas.
    2. Convierte Cédula a NVARCHAR(12) sin decimales.
    3. Separa CENTRO DE COSTO en COD_SERVICIO y SERVICIO, descartando CENTRO DE COSTO.
    4. Garantiza existencia de CODIGO y ESTADO.
    5. Normaliza Cursos a 'SI', 'NO' o None (celda vacía).
    6. Convierte Fechas de Realización y Vencimiento a formato ISO para DATETIME2.
    7. Recorta y limpia textos (Nombre, Cargo sin sufijos de sede, Jefe Inmediato).
    8. Descarta filas residuales vacías.
    9. Genera hash SHA-256 de auditoría y deduplica filas idénticas.
    10. Reordena columnas con _mes_analisis como primera columna.
    """
    df = df_raw.copy()

    # 0. Reparar columna CÉDULA si vino con un valor numérico en el encabezado (ej. '1005' en Aguachica)
    headers = list(df.columns)
    has_cedula = any("CEDULA" in str(h).upper() for h in headers)
    if not has_cedula:
        for idx, h in enumerate(headers):
            h_str = str(h).strip()
            # Si el header es numérico o es la primera columna antes de 'NOMBRE DEL EMPLEADO'
            if h_str.isdigit() or (idx + 1 < len(headers) and "NOMBRE" in str(headers[idx + 1]).upper()):
                logger.info(f"Columna '{h}' identificada y homologada automáticamente como 'CEDULA'.")
                headers[idx] = "CEDULA"
                break
        df.columns = headers

    # 1. Normalizar nombres de columnas a mayúsculas limpias y homologar variaciones
    clean_cols = []
    seen = {}
    for c in df.columns:
        c_clean = sanitize_column_name(c).strip().upper()
        # Homologar variantes frecuentes menores de nombres de columnas
        if c_clean == "CENTRO DE COSTOS":
            c_clean = "CENTRO DE COSTO"
        elif c_clean == "ADMINISTRACION DE MEDICAMENTOS":
            c_clean = "ADMINISTRACIÓN DE MEDICAMENTOS"
        elif c_clean == "VIOLENCIA SEXUAL":
            c_clean = "ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL"

        if c_clean in seen:
            seen[c_clean] += 1
            c_clean = f"{c_clean}_{seen[c_clean]}"
        else:
            seen[c_clean] = 0
        clean_cols.append(c_clean)
    df.columns = clean_cols

    # 2. Descartar filas completamente vacías en el archivo original
    df = df.dropna(how="all")

    # Identificar columnas clave
    ced_col = next((c for c in df.columns if "CEDULA" in c.upper()), None)
    emp_col = next((c for c in df.columns if "NOMBRE" in c.upper() and "EMPLEADO" in c.upper()), None)

    # 3. Estandarizar columna CÉDULA
    if ced_col:
        df[ced_col] = df[ced_col].apply(clean_cedula_value)

    # 3.1 Separar CENTRO DE COSTO en COD_SERVICIO y SERVICIO, eliminando CENTRO DE COSTO
    cc_col = next((c for c in df.columns if "CENTRO" in c.upper() and "COSTO" in c.upper()), None)
    if cc_col:
        cods = []
        servs = []
        for val in df[cc_col]:
            cod, serv = parse_centro_costo(val)
            cods.append(cod)
            servs.append(serv)
        df["COD_SERVICIO"] = cods
        df["SERVICIO"] = servs
        df = df.drop(columns=[cc_col])
    else:
        if "COD_SERVICIO" not in df.columns:
            df["COD_SERVICIO"] = None
        if "SERVICIO" not in df.columns:
            df["SERVICIO"] = None

    # 3.2 Garantizar existencia de CODIGO y ESTADO en todas las sedes (con NULL si no vienen)
    if "CODIGO" not in df.columns:
        df["CODIGO"] = None
    if "ESTADO" not in df.columns:
        df["ESTADO"] = None

    # 4. Estandarizar cada columna según su tipo semántico
    for col in df.columns:
        if col.startswith("_"):
            continue

        col_upper = col.upper()

        if col == ced_col:
            continue  # Ya procesada arriba

        elif col == emp_col or "NOMBRE" in col_upper or "JEFE" in col_upper:
            max_l = MAX_LENGTH_BY_COLUMN.get("JEFE INMEDIATO", 200) if "JEFE" in col_upper else 200
            df[col] = df[col].apply(lambda v: clean_text_value(v, max_l))

        elif "CARGO" in col_upper:
            df[col] = df[col].apply(clean_cargo_value)

        elif col_upper in ("COD_SERVICIO",):
            df[col] = df[col].apply(lambda v: clean_text_value(v, 10))

        elif col_upper in ("SERVICIO",):
            df[col] = df[col].apply(lambda v: clean_text_value(v, 150))

        elif col_upper in ("CODIGO", "ESTADO"):
            df[col] = df[col].apply(lambda v: clean_text_value(v, 50))

        elif is_date_column(col):
            df[col] = df[col].apply(clean_date_value)

        elif is_course_column(col):
            df[col] = df[col].apply(clean_course_value)

        else:
            df[col] = df[col].apply(lambda v: clean_text_value(v, 200))

    # 5. Filtrar filas válidas: debe tener al menos Cédula o Nombre del Empleado
    cond_emp = df[emp_col].notna() if emp_col else pd.Series(False, index=df.index)
    cond_ced = df[ced_col].notna() if ced_col else pd.Series(False, index=df.index)
    valid_mask = cond_emp | cond_ced
    dropped_blanks = len(df) - valid_mask.sum()
    if dropped_blanks > 0:
        logger.info(f"Omitidas {dropped_blanks} filas sin identificación válida en '{filename}'.")
        df = df[valid_mask].copy()

    # Asignar mes de análisis al registro
    if not mes_analisis:
        meses = {
            'ENERO': '01', 'FEBRERO': '02', 'MARZO': '03', 'ABRIL': '04',
            'MAYO': '05', 'JUNIO': '06', 'JULIO': '07', 'AGOSTO': '08',
            'SEPTIEMBRE': '09', 'OCTUBRE': '10', 'NOVIEMBRE': '11', 'DICIEMBRE': '12'
        }
        upper_f = filename.upper()
        found_mes = None
        for m_name, m_num in meses.items():
            if m_name in upper_f:
                found_mes = m_num
                break
        year_match = re.search(r'\b(20\d{2})\b', upper_f)
        year_val = year_match.group(1) if year_match else str(datetime.now().year)
        mes_analisis = f"{year_val}-{found_mes}" if found_mes else datetime.now().strftime("%Y-%m")
    df["_mes_analisis"] = mes_analisis

    # 6. Calcular hash SHA-256 de auditoría sobre columnas de negocio estandarizadas
    business_cols = [c for c in df.columns if not c.startswith("_")]
    row_strings = df[business_cols].fillna("").astype(str).agg("||".join, axis=1)
    df["_archivo_origen"] = filename
    df["_hash_registro"] = [hashlib.sha256(s.encode("utf-8")).hexdigest() for s in row_strings]

    # 7. Deduplicación interna de filas 100% idénticas
    initial_count = len(df)
    df = df.drop_duplicates(subset=["_hash_registro"])
    if len(df) < initial_count:
        logger.info(f"Omitidas {initial_count - len(df)} filas duplicadas internas en '{filename}'.")

    # 8. Deduplicación inteligente por CÉDULA dentro de la misma sede:
    # Si un colaborador aparece más de una vez en el archivo, se conserva el registro
    # con la fecha de realización de cursos más reciente y más completa.
    if ced_col and ced_col in df.columns:
        dup_mask = df[ced_col].notna() & df.duplicated(subset=[ced_col], keep=False)
        if dup_mask.any():
            date_cols = [c for c in df.columns if is_date_column(c) and "REALIZA" in c]
            temp_dates = df[date_cols].apply(pd.to_datetime, errors="coerce")
            df["_max_fecha_real"] = temp_dates.max(axis=1)
            df["_cnt_fechas_real"] = temp_dates.notna().sum(axis=1)

            # Ordenar por:
            # 1. Fecha de realización más reciente (descendente)
            # 2. Cantidad de cursos con fechas registradas (descendente)
            df = df.sort_values(
                by=[ced_col, "_max_fecha_real", "_cnt_fechas_real"],
                ascending=[True, False, False],
                na_position="last"
            )

            dup_cedulas = df.loc[dup_mask, ced_col].unique()
            for d_ced in dup_cedulas:
                d_rows = df[df[ced_col] == d_ced]
                best_date = d_rows.iloc[0]["_max_fecha_real"]
                logger.info(
                    f"Cédula {d_ced} duplicada en '{filename}': se conservó el registro más actualizado "
                    f"(Fecha más reciente: {best_date}) y se descartaron {len(d_rows) - 1} registros obsoletos."
                )

            df = df.drop_duplicates(subset=[ced_col], keep="first")
            df = df.drop(columns=["_max_fecha_real", "_cnt_fechas_real"])

    # 9. Reordenar columnas para esquema estándar:
    # 1. _mes_analisis
    # 2. Datos demográficos: CEDULA, NOMBRE DEL EMPLEADO, CODIGO, ESTADO, CARGO, COD_SERVICIO, SERVICIO, JEFE INMEDIATO
    # 3. Columnas de cursos y fechas
    # 4. Columnas de auditoría: _hash_registro, _fecha_carga (si existe), _archivo_origen
    lead_cols = [
        "_mes_analisis", "CEDULA", "NOMBRE DEL EMPLEADO", "CODIGO", "ESTADO",
        "CARGO", "COD_SERVICIO", "SERVICIO", "JEFE INMEDIATO"
    ]
    audit_cols = ["_hash_registro", "_fecha_carga", "_archivo_origen"]

    existing_lead = [c for c in lead_cols if c in df.columns]
    existing_audit = [c for c in audit_cols if c in df.columns]
    middle_cols = [c for c in df.columns if c not in existing_lead and c not in existing_audit]

    final_order = existing_lead + middle_cols + existing_audit
    df = df[final_order]

    return df


# ==============================================================================
# 5. SINCRONIZACIÓN Y HOMOLOGACIÓN DE ESQUEMA EN SQL SERVER
# ==============================================================================

def synchronize_table_schema(cursor, database: str, table_name: str, incoming_columns: List[str]):
    """
    Sincroniza y homologa el esquema físico de una tabla en SQL Server:
    - Si la tabla no existe: la crea con tipos estandarizados, PK identity e índices.
    - Si la tabla ya existe:
        1. Agrega cualquier columna nueva que no exista con su tipo estándar (soporte dinámico).
        2. Homologa columnas existentes con tipos legados (p. ej. FLOAT en Cédula o NVARCHAR(MAX) en Nombres).
        3. Garantiza índices no agrupados sobre todas las columnas de 'FECHA DE REALIZACION'.
        4. Garantiza índice único sobre '_hash_registro'.
    """
    clean_table = sanitize_column_name(table_name)
    logger.info(f"[{database}] Sincronizando esquema para [dbo].[{clean_table}]...")

    cursor.execute(f"SELECT OBJECT_ID('dbo.[{clean_table}]', 'U')")
    row = cursor.fetchone()
    table_exists = row[0] is not None

    if not table_exists:
        logger.info(f"[{database}] Creando tabla estandarizada [dbo].[{clean_table}]...")
        cols_ddl = [
            "[_mes_analisis] VARCHAR(10) NOT NULL",
            "[CEDULA] NVARCHAR(12) NOT NULL"
        ]

        for col in incoming_columns:
            if col in ("_mes_analisis", "CEDULA") or col.startswith("_"):
                continue
            std_type = get_standard_sql_type(col)
            cols_ddl.append(f"[{col}] {std_type} NULL")

        cols_ddl.append("[_hash_registro] CHAR(64) NOT NULL")
        cols_ddl.append("[_fecha_carga] DATETIME DEFAULT GETDATE()")
        cols_ddl.append("[_archivo_origen] NVARCHAR(255) NULL")
        cols_ddl.append(f"CONSTRAINT [PK_{clean_table}] PRIMARY KEY ([_mes_analisis], [CEDULA])")

        create_sql = f"CREATE TABLE [dbo].[{clean_table}] (\n    {', '.join(cols_ddl)}\n);"
        cursor.execute(create_sql)
        logger.info(f"[{database}] Tabla [dbo].[{clean_table}] creada exitosamente con PK ([_mes_analisis], [CEDULA]).")

        # Índice único de hash
        cursor.execute(f"""
            CREATE UNIQUE NONCLUSTERED INDEX [UQ_{clean_table}_hash]
            ON [dbo].[{clean_table}] ([_hash_registro])
            WITH (IGNORE_DUP_KEY = ON);
        """)
        logger.info(f"[{database}] Índice único [UQ_{clean_table}_hash] creado.")

    else:
        # Obtener columnas existentes en la tabla con tipos y tamaños (mapeo case-insensitive)
        cursor.execute(f"""
            SELECT c.name, t.name as type_name, c.max_length
            FROM sys.columns c
            JOIN sys.types t ON c.user_type_id = t.user_type_id
            WHERE c.object_id = OBJECT_ID('dbo.[{clean_table}]')
        """)
        # Mapeo: nombre_normalizado -> (nombre_real_en_bd, tipo, max_length)
        existing_cols_ci = {r[0].strip().lower(): (r[0], r[1].lower(), r[2]) for r in cursor.fetchall()}

        # 1. Agregar nuevas columnas si no existen (comparación case-insensitive)
        for col in incoming_columns:
            if col.startswith("_"):
                continue
            col_key = col.strip().lower()
            if col_key not in existing_cols_ci:
                std_type = get_standard_sql_type(col)
                logger.info(f"[{database}] Agregando nueva columna dinámica [{col}] {std_type} a [dbo].[{clean_table}]...")
                cursor.execute(f"ALTER TABLE [dbo].[{clean_table}] ADD [{col}] {std_type} NULL")
                existing_cols_ci[col_key] = (col, std_type.split("(")[0].lower(), None)

        # 2. Homologar tipos legados (p. ej. FLOAT o NVARCHAR(MAX)) hacia tipos estándar
        for col in incoming_columns:
            if col.startswith("_"):
                continue
            col_key = col.strip().lower()
            if col_key not in existing_cols_ci:
                continue

            real_col_name, curr_type, curr_len = existing_cols_ci[col_key]
            std_type = get_standard_sql_type(real_col_name)
            std_base = std_type.split("(")[0].lower()

            needs_alter = False
            if curr_type != std_base:
                needs_alter = True
            elif curr_type in ("nvarchar", "varchar") and curr_len == -1:  # Era MAX
                needs_alter = True

            if needs_alter:
                try:
                    # Dropear índices que dependan de la columna antes de alterarla
                    cursor.execute(f"""
                        SELECT i.name
                        FROM sys.indexes i
                        JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
                        WHERE i.object_id = OBJECT_ID('dbo.[{clean_table}]')
                          AND c.name = '{real_col_name}'
                          AND i.is_primary_key = 0
                    """)
                    indexes_to_drop = [r[0] for r in cursor.fetchall()]
                    for idx_name in indexes_to_drop:
                        cursor.execute(f"DROP INDEX [{idx_name}] ON [dbo].[{clean_table}]")

                    logger.info(f"[{database}] Homologando columna [{real_col_name}] de '{curr_type}' a '{std_type}'...")
                    if curr_type == "float" and std_base in ("datetime2", "datetime", "date"):
                        # SQL Server no permite float directo a datetime2, se pasa temporalmente por nvarchar
                        cursor.execute(f"ALTER TABLE [dbo].[{clean_table}] ALTER COLUMN [{real_col_name}] NVARCHAR(50) NULL")
                    cursor.execute(f"ALTER TABLE [dbo].[{clean_table}] ALTER COLUMN [{real_col_name}] {std_type} NULL")
                except Exception as ex_alt:
                    logger.warning(f"[{database}] No se pudo alterar columna [{real_col_name}] a {std_type}: {ex_alt}")

    # 3. Garantizar índices de fecha sobre todas las 'FECHA DE REALIZACION'
    for col in incoming_columns:
        if is_date_column(col) and "REALIZACION" in col.upper():
            safe_col_tag = col.replace(" ", "_")
            idx_name = f"IX_{clean_table}_{safe_col_tag}"[:128]
            cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes 
                WHERE name = '{idx_name}' 
                  AND object_id = OBJECT_ID('dbo.[{clean_table}]')
            )
            BEGIN
                CREATE NONCLUSTERED INDEX [{idx_name}] 
                ON [dbo].[{clean_table}] ([{col}] ASC);
            END
            """)
