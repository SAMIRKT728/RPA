import argparse
import logging
import os
import sys
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional
from config import config, resolve_db_and_table
from google_drive_client import list_files_in_drive, list_subfolders, download_file_to_bytes
from spark_session import get_spark_session
from db_loader import load_dataframe_idempotent, get_mssql_connection

# Configurar logging
os.makedirs("logs", exist_ok=True)
log_filename = datetime.now().strftime("logs/rpa_%Y%m%d_%H%M%S.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, encoding="utf-8")
    ]
)
logger = logging.getLogger("RPA.Main")


def extract_dates_from_filename(filename: str):
    """
    Detecta automáticamente el mes en español desde el nombre del archivo
    (ej: 'MATRIZ 3100 - SAN JUAN AGOSTO.xlsx' -> '2026-08-31', '2026-08').
    """
    import calendar
    import re

    meses = {
        'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4,
        'MAYO': 5, 'JUNIO': 6, 'JULIO': 7, 'AGOSTO': 8,
        'SEPTIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11, 'DICIEMBRE': 12
    }
    upper_name = filename.upper()

    # Buscar año de 4 dígitos en el nombre del archivo si existe (ej. 2026); por defecto año actual
    year_match = re.search(r'\b(20\d{2})\b', upper_name)
    current_year = int(year_match.group(1)) if year_match else datetime.now().year

    for mes_nombre, mes_num in meses.items():
        if mes_nombre in upper_name:
            last_day = calendar.monthrange(current_year, mes_num)[1]
            corte = f"{current_year}-{mes_num:02d}-{last_day:02d}"
            mes_str = f"{current_year}-{mes_num:02d}"
            return corte, mes_str
    return None, None


def resolve_target_batches(target_folder: str, pattern: str = "MATRIZ 3100", mes: Optional[str] = None):
    """
    Determina si la carpeta en Google Drive contiene archivos directos o subcarpetas de meses (ej. 2026/Agosto, 2026/Septiembre).
    Retorna una lista de lotes listos para procesar.
    """
    # 1. Comprobar si hay archivos directos en target_folder
    direct_files = list_files_in_drive(folder_id=target_folder, pattern=pattern)
    if direct_files:
        logger.info(f"Se encontraron {len(direct_files)} archivos directamente en la carpeta raíz.")
        return [{
            "name": "Directo",
            "folder_id": target_folder,
            "files": direct_files,
            "fecha_corte": None,
            "mes_analisis": None
        }]

    # 2. Si no hay archivos directos, inspeccionar si target_folder contiene subcarpetas de meses
    subfolders = list_subfolders(target_folder)
    if not subfolders:
        logger.warning(f"No se encontraron archivos ni subcarpetas en Google Drive dentro de '{target_folder}'.")
        return []

    available_names = [sf.get("name", "") for sf in subfolders]
    logger.info(f"Se detectaron {len(subfolders)} subcarpetas en Google Drive: {available_names}")

    def get_subfolder_sort_key(sf: dict) -> str:
        sf_name = sf.get("name", "")
        _, mes_str = extract_dates_from_filename(sf_name)
        if mes_str:
            return mes_str
        return sf.get("modifiedTime") or sf.get("createdTime") or ""

    selected_subfolders = []
    mes_filter = mes.strip().lower() if mes else None

    if mes_filter and mes_filter not in ("todos", "all"):
        for sf in subfolders:
            sf_name = sf.get("name", "").strip().lower()
            if mes_filter in sf_name or sf_name in mes_filter:
                selected_subfolders.append(sf)
        if not selected_subfolders:
            logger.warning(f"No se encontró ninguna subcarpeta que coincida con el mes '{mes}'. Subcarpetas disponibles: {available_names}")
            return []
    elif mes_filter in ("todos", "all"):
        # Ordenar cronológicamente (más antiguo al más reciente) para procesar en orden
        selected_subfolders = sorted(subfolders, key=get_subfolder_sort_key)
    else:
        # Si no se pasó --mes, seleccionar automáticamente la subcarpeta del mes más reciente
        subfolders_sorted = sorted(subfolders, key=get_subfolder_sort_key, reverse=True)
        most_recent = subfolders_sorted[0]
        selected_subfolders = [most_recent]
        logger.info(f"No se especificó --mes. Seleccionando automáticamente el mes más reciente: '{most_recent.get('name')}'. Subcarpetas disponibles: {available_names}")
        logger.info("-> Para procesar un mes específico use: --mes <nombre> o para todos: --mes todos")

    batches = []
    for sf in selected_subfolders:
        sf_name = sf.get("name", "")
        sf_id = sf.get("id")
        logger.info(f"Consultando archivos en la subcarpeta '{sf_name}'...")
        files = list_files_in_drive(folder_id=sf_id, pattern=pattern)
        if not files:
            logger.warning(f"La subcarpeta '{sf_name}' no contiene archivos que coincidan con '{pattern}'.")
            continue

        corte, mes_str = extract_dates_from_filename(sf_name)
        batches.append({
            "name": sf_name,
            "folder_id": sf_id,
            "files": files,
            "fecha_corte": corte,
            "mes_analisis": mes_str
        })

    return batches


def get_default_previous_month_dates():
    """Calcula automáticamente el último día y el formato YYYY-MM del mes anterior."""
    today = datetime.now().date()
    first_day_curr_month = date(today.year, today.month, 1)
    last_day_prev_month = first_day_curr_month - timedelta(days=1)
    return last_day_prev_month.strftime("%Y-%m-%d"), last_day_prev_month.strftime("%Y-%m")


def execute_dashboard_stored_procedures(fecha_corte_str: str = None, mes_analisis_str: str = None, ventana_dias: int = 90):
    """
    Ejecuta directamente los procedimientos almacenados en SQL Server para poblar
    BGD_DASHBOARD_CURSOS_3100 y BGD_RESUMEN_MES_3100 de forma nativa, veloz y optimizada.
    """
    if not fecha_corte_str or not mes_analisis_str:
        def_corte, def_mes = get_default_previous_month_dates()
        fecha_corte_str = fecha_corte_str or def_corte
        mes_analisis_str = mes_analisis_str or def_mes

    logger.info("======================================================")
    logger.info("Ejecutando procedimientos almacenados en el motor SQL Server...")
    logger.info(f" -> Fecha de Corte : {fecha_corte_str}")
    logger.info(f" -> Mes de Análisis: {mes_analisis_str}")
    logger.info(f" -> Ventana de Días: {ventana_dias}")

    # Asegurar que las tablas de persistencia existan
    from data_access.db_repository import DbRepository
    DbRepository(database="DGEMPRES01").init_tables_and_indexes()

    conn = get_mssql_connection("DGEMPRES01")
    cur = conn.cursor()

    try:
        # 1. Poblar Dashboard
        logger.info("Llamando a dbo.SP_POBLAR_BGD_DASHBOARD_CURSOS_3100...")
        cur.execute(
            "EXEC dbo.SP_POBLAR_BGD_DASHBOARD_CURSOS_3100 @FechaCorte=%s, @VentanaDias=%d, @MesAnalisis=%s",
            (fecha_corte_str, ventana_dias, mes_analisis_str)
        )
        logger.info("dbo.SP_POBLAR_BGD_DASHBOARD_CURSOS_3100 finalizado exitosamente.")

        # 2. Poblar Resumen Mes
        logger.info("Llamando a dbo.SP_POBLAR_BGD_RESUMEN_MES_3100...")
        cur.execute(
            "EXEC dbo.SP_POBLAR_BGD_RESUMEN_MES_3100 @FechaCorte=%s",
            (fecha_corte_str,)
        )
        logger.info("dbo.SP_POBLAR_BGD_RESUMEN_MES_3100 finalizado exitosamente.")
        logger.info("======================================================")
    finally:
        conn.close()


def process_excel_buffer_with_spark(spark, buffer, filename: str, database: str, table_name: str, dry_run: bool = False, mes_analisis: Optional[str] = None):
    """
    Lee un buffer Excel (.xlsx), aplica la estandarización y limpieza integral de datos
    (Cédulas sin decimales, Cursos SI/NO/vacío, Fechas en DATETIME2, Textos acotados),
    lo transfiere a PySpark y ejecuta la carga idempotente a SQL Server.
    """
    logger.info(f"Leyendo contenido de '{filename}' (sin validación de colores)...")
    from data_standardizer import read_excel_with_styles, clean_and_standardize_dataframe
    df_raw = read_excel_with_styles(buffer, filename)
    df_pandas = clean_and_standardize_dataframe(df_raw, filename, mes_analisis=mes_analisis)

    row_count = len(df_pandas)
    logger.info(f"Archivo '{filename}' estandarizado: {row_count} filas únicas y {len(df_pandas.columns)} columnas.")

    if row_count == 0:
        logger.warning(f"El archivo '{filename}' no contiene registros válidos con empleado o cédula. Omitiendo.")
        return 0

    if dry_run:
        logger.info(f"[DRY-RUN] Destino previsto: Base de datos='{database}', Tabla='{table_name}'. No se escribirán datos.")
        return row_count

    # Convertir a Spark DataFrame asegurando tipos StringType consistentes (evita void/NullType)
    logger.info("Transformando a DataFrame de PySpark...")
    df_spark_prep = df_pandas.fillna("").astype(str).replace({"nan": "", "None": "", "<NA>": ""})
    spark_df = spark.createDataFrame(df_spark_prep)

    # Ejecutar carga idempotente y sincronización de esquema
    inserted = load_dataframe_idempotent(spark, spark_df, database, table_name, filename)
    return inserted


def run_rpa(folder_id: str = None, pattern: str = "MATRIZ 3100", local_file: str = None, dry_run: bool = False, fecha_corte: str = None, mes_analisis: str = None, mes: str = None):
    """Orquesta el ciclo completo de la RPA."""
    logger.info("======================================================")
    logger.info("INICIANDO PROCESO RPA - DRIVE A SQL SERVER CON PYSPARK")
    logger.info("======================================================")

    # 1. Iniciar sesión de PySpark
    logger.info("Inicializando sesión de PySpark...")
    spark = get_spark_session()
    logger.info("Sesión de PySpark iniciada correctamente.")

    try:
        # Caso A: Procesar un archivo local para pruebas o contingencia
        if local_file:
            filename = os.path.basename(local_file)
            mapping = resolve_db_and_table(filename, config.TABLE_PREFIX)
            if not mapping:
                logger.error(f"No se pudo determinar la base de datos destino para el archivo: '{filename}'.")
                return

            database, table_name, sede = mapping
            logger.info(f"Archivo: '{filename}' -> Sede: {sede} -> BD: {database} -> Tabla: {table_name}")

            with open(local_file, "rb") as f:
                import io
                buf = io.BytesIO(f.read())
                process_excel_buffer_with_spark(spark, buf, filename, database, table_name, dry_run, mes_analisis=mes_analisis)
            return

        # Caso B: Procesar desde Google Drive (con soporte de subcarpetas por mes)
        target_folder = folder_id or config.GOOGLE_DRIVE_FOLDER_ID
        logger.info(f"Buscando archivos en Google Drive (Filtro: '{pattern}', Carpeta: {target_folder or 'Raíz'})...")
        
        batches = resolve_target_batches(target_folder, pattern=pattern, mes=mes)
        if not batches:
            logger.warning(f"No se encontraron lotes de archivos para procesar en Google Drive.")
            return

        grand_total_inserted = 0
        grand_total_files = 0

        for batch in batches:
            batch_name = batch["name"]
            files = batch["files"]
            target_corte = fecha_corte or batch.get("fecha_corte")
            target_mes = mes_analisis or batch.get("mes_analisis")

            logger.info("======================================================")
            logger.info(f"PROCESANDO LOTE: '{batch_name}' ({len(files)} archivos)")
            logger.info("======================================================")

            processed_count = 0
            total_inserted = 0

            for file_meta in files:
                filename = file_meta.get("name", "")
                file_id = file_meta.get("id")
                mime_type = file_meta.get("mimeType", "")

                mapping = resolve_db_and_table(filename, config.TABLE_PREFIX)
                if not mapping:
                    logger.warning(f"Archivo '{filename}' no coincide con ninguna sede conocida (alta, centro, aguachica, san juan, valle). Omitiendo.")
                    continue

                database, table_name, sede = mapping
                logger.info("------------------------------------------------------")
                logger.info(f"Procesando: '{filename}'")
                logger.info(f" -> Sede: {sede} | Base de Datos: {database} | Tabla: {table_name}")

                # Detección automática por nombre de archivo si no se infirió de la carpeta
                if not target_corte or not target_mes:
                    inferred_corte, inferred_mes = extract_dates_from_filename(filename)
                    if inferred_corte:
                        target_corte = target_corte or inferred_corte
                        target_mes = target_mes or inferred_mes
                        logger.info(f"Detección automática por archivo '{filename}': Fecha Corte = {target_corte}, Mes = {target_mes}")

                # Descargar archivo a memoria
                buffer = download_file_to_bytes(file_id, mime_type)

                # Procesar con PySpark y subir a SQL Server
                inserted = process_excel_buffer_with_spark(spark, buffer, filename, database, table_name, dry_run, mes_analisis=target_mes)
                total_inserted += inserted
                processed_count += 1

            grand_total_inserted += total_inserted
            grand_total_files += processed_count

            logger.info("======================================================")
            logger.info(f"RESUMEN LOTE '{batch_name}': {processed_count} archivos procesados. Total nuevos registros insertados: {total_inserted}")
            logger.info("======================================================")

            # Actualizar tabla de Jefes Unificados mediante el procedimiento almacenado si existe
            if not dry_run and processed_count > 0:
                try:
                    conn_jefes = get_mssql_connection("DGEMPRES01")
                    cur_jefes = conn_jefes.cursor()
                    cur_jefes.execute("SELECT OBJECT_ID('dbo.sp_ObtenerJefesUnificados_MX100', 'P')")
                    sp_row = cur_jefes.fetchone()
                    if sp_row and sp_row[0]:
                        logger.info("Actualizando catálogo de jefes unificados (sp_ObtenerJefesUnificados_MX100)...")
                        cur_jefes.execute("EXEC dbo.sp_ObtenerJefesUnificados_MX100")
                        logger.info("Catálogo de jefes unificados actualizado exitosamente en DGEMPRES01.dbo.BGD_JEFES_UNIFICADOS_MX100.")
                    else:
                        logger.info("Procedimiento dbo.sp_ObtenerJefesUnificados_MX100 no está disponible aún. Omitiendo actualización de jefes.")
                    conn_jefes.close()
                except Exception as ex_sp:
                    logger.warning(f"Aviso al actualizar catálogo de jefes unificados: {str(ex_sp)}")

                # Ejecutar Stored Procedures de cálculo normativo (Dashboard y Resumen Mes)
                try:
                    execute_dashboard_stored_procedures(
                        fecha_corte_str=target_corte,
                        mes_analisis_str=target_mes
                    )
                except Exception as ex_calc:
                    logger.error(f"Error al ejecutar stored procedures de cálculo normativo: {str(ex_calc)}")

        logger.info("======================================================")
        logger.info(f"RESUMEN TOTAL RPA: {grand_total_files} archivos procesados. Total nuevos registros insertados: {grand_total_inserted}")
        logger.info("======================================================")

    except Exception as e:
        logger.exception(f"Error crítico durante la ejecución de la RPA: {str(e)}")
        raise
    finally:
        logger.info("Deteniendo sesión de PySpark...")
        spark.stop()
        logger.info("Sesión de PySpark finalizada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RPA PySpark Google Drive a SQL Server")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta en modo simulación sin escribir en la base de datos")
    parser.add_argument("--folder-id", type=str, default=None, help="ID de la carpeta en Google Drive")
    parser.add_argument("--pattern", type=str, default="MATRIZ 3100", help="Patrón de búsqueda de archivos")
    parser.add_argument("--local-file", type=str, default=None, help="Ruta de un archivo Excel local para prueba")
    parser.add_argument("--fecha-corte", type=str, default=None, help="Fecha de corte en formato YYYY-MM-DD (por defecto último día mes anterior)")
    parser.add_argument("--mes-analisis", type=str, default=None, help="Mes de análisis en formato YYYY-MM (por defecto mes anterior)")
    parser.add_argument("--mes", type=str, default=None, help="Mes o subcarpeta a procesar en Google Drive (ej. 'Agosto', 'Septiembre', o 'todos')")
    parser.add_argument("--recalc", action="store_true", help="Ejecuta únicamente los Stored Procedures de Dashboard y Resumen Mes sin recargar Drive")

    args = parser.parse_args()

    if args.recalc:
        logger.info("Modo --recalc activado.")
        execute_dashboard_stored_procedures(
            fecha_corte_str=args.fecha_corte,
            mes_analisis_str=args.mes_analisis
        )
    else:
        run_rpa(
            folder_id=args.folder_id,
            pattern=args.pattern,
            local_file=args.local_file,
            dry_run=args.dry_run,
            fecha_corte=args.fecha_corte,
            mes_analisis=args.mes_analisis,
            mes=args.mes
        )

