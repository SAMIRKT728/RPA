"""
pipeline/matrix_calculator_service.py
Servicio Orquestador de Cálculo y Persistencia de la Matriz 3100.
Principio: Bajo Acoplamiento y Alta Cohesión.
Coordina:
1. Lectura de datos fuente de colaboradores.
2. Motor de reglas (core.rules_engine) para clasificar cada curso.
3. Agregador de métricas (core.metrics_calculator) para consolidar KPIs.
4. Repositorio (data_access.db_repository) para persistir e indexar en SQL Server.
"""

import os
import sys
import json
import re
import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rules_engine import evaluate_single_course
from core.metrics_calculator import aggregate_collaborator_metrics
from data_access.db_repository import DbRepository
from models.dto import CourseEvaluation, CollaboratorSummary, CourseStatus

logger = logging.getLogger("RPA.MatrixCalculatorService")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def epoch_days_to_date(days: Optional[int]) -> Optional[date]:
    """Convierte días epoch (días desde 1970-01-01) a objeto date."""
    if days is None:
        return None
    return date(1970, 1, 1) + timedelta(days=days)


class MatrixCalculatorService:
    def __init__(self, html_source_path: str = "dashboard_matriz_cursos_3100 (7).html", database: str = "DGEMPRES01"):
        self.html_source_path = html_source_path
        self.repo = DbRepository(database=database)

    def load_source_data(self) -> Dict[str, Any]:
        """Extrae el catálogo de cursos, metadatos y filas de colaboradores del archivo fuente."""
        with open(self.html_source_path, "r", encoding="utf-8") as f:
            html = f.read()

        match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.DOTALL)
        if not match:
            raise ValueError(f"No se encontró el bloque <script id='data'> en {self.html_source_path}")

        return json.loads(match.group(1))

    def load_service_code_mapping(self) -> Dict[Tuple[str, str], str]:
        """Extrae el código de servicio (4 dígitos) desde CENTRO DE COSTO en las 5 tablas."""
        from config import config
        import pymssql
        dbs = [
            ("DGEMPRES01", "BGD_MATRIZ_3100_A", "ALTA"),
            ("DGEMPRES01", "BGD_MATRIZ_3100_C", "CENTRO"),
            ("DGEMPRES30", "BGD_MATRIZ_3100_AG", "AGUACHICA"),
            ("DGEMPRES70", "BGD_MATRIZ_3100_SJ", "SAN JUAN"),
            ("DGEMPRES80", "BGD_MATRIZ_3100_V", "VALLE")
        ]
        mapping: Dict[Tuple[str, str], str] = {}
        for db, tbl, sede in dbs:
            try:
                conn = pymssql.connect(
                    server=config.SQL_SERVER, port=config.SQL_PORT,
                    user=config.SQL_USER, password=config.SQL_PASSWORD,
                    database=db
                )
                cur = conn.cursor(as_dict=True)
                cur.execute(f"SELECT CEDULA, [CENTRO DE COSTO] FROM {tbl}")
                for row in cur.fetchall():
                    ced = str(row["CEDULA"] or "").strip()
                    cc = str(row["CENTRO DE COSTO"] or "")
                    m = re.search(r"\b(\d{3,4})\b", cc)
                    if m:
                        mapping[(sede, ced)] = m.group(1).zfill(4)
                conn.close()
            except Exception as e:
                logger.warning("No se pudo cargar CENTRO DE COSTO de %s.%s: %s", db, tbl, e)
        return mapping

    def run_calculation_and_load(
        self,
        fecha_corte: Optional[date] = None,
        ventana_dias: int = 90,
        mes_analisis: Optional[str] = None
    ):
        """
        Ejecuta el cálculo completo para todos los colaboradores y sedes
        y persiste los resultados indexados en SQL Server.
        """
        data = self.load_source_data()
        courses: List[str] = data["courses"]
        sedes: List[str] = data["sede"]
        cargos: List[str] = data["cargo"]
        servs: List[str] = data["serv"]
        jefes: List[str] = data["jefe"]
        rows: List[List] = data["rows"]

        # Cargar catálogo de códigos de servicio
        cod_map = self.load_service_code_mapping()
        logger.info("Mapeados %d códigos de servicio desde CENTRO DE COSTO.", len(cod_map))

        # Fecha de corte por defecto según el archivo si no se especifica
        if fecha_corte is None:
            corte_epoch = data.get("corte", 20696)
            fecha_corte = epoch_days_to_date(corte_epoch)

        if mes_analisis is None:
            mes_analisis = fecha_corte.strftime("%Y-%m")

        logger.info("Iniciando cálculo para fecha de corte: %s, ventana: %d días, mes: %s", fecha_corte, ventana_dias, mes_analisis)
        logger.info("Total registros a procesar: %d colaboradores x %d cursos = %d evaluaciones.", len(rows), len(courses), len(rows) * len(courses))

        # Inicializar tablas e índices en SQL Server
        self.repo.init_tables_and_indexes()
        # Limpieza previa para idempotencia
        self.repo.clean_records_for_corte(fecha_corte)

        dashboard_rows: List[Tuple] = []
        resumen_rows: List[Tuple] = []

        total_cumplidos = 0
        total_obligatorios = 0

        for r in rows:
            sede_name = sedes[r[0]]
            cedula = str(r[1]).strip()
            nombre = str(r[2]).strip()
            cargo_name = cargos[r[3]]
            serv_name = servs[r[4]]
            jefe_name = jefes[r[5]] if r[5] < len(jefes) else "SIN DATO"
            marks_str = str(r[6])
            dates_dict = r[7]

            cod_servicio = cod_map.get((sede_name, cedula), "")

            evaluations: List[CourseEvaluation] = []

            for idx, cname in enumerate(courses):
                cid = f"C{idx+1:02d}"
                ch = marks_str[idx] if idx < len(marks_str) else "-"
                is_obl = (ch in ("S", "N"))
                
                d_pair = dates_dict.get(str(idx))
                f_real = epoch_days_to_date(d_pair[0]) if d_pair and len(d_pair) > 0 else None
                f_venc = epoch_days_to_date(d_pair[1]) if d_pair and len(d_pair) > 1 else None

                ev = evaluate_single_course(
                    curso_id=cid,
                    curso_plantilla=cname,
                    marca_raw="SI" if ch == "S" else ("NO" if ch == "N" else "NA"),
                    is_obligatory_by_matrix=is_obl,
                    fecha_real=f_real,
                    fecha_venc=f_venc,
                    fecha_corte=fecha_corte,
                    ventana_dias=ventana_dias
                )
                evaluations.append(ev)

                # Registro para la tabla BGD_DASHBOARD_CURSOS_3100
                dashboard_rows.append((
                    mes_analisis,
                    fecha_corte.strftime("%Y-%m-%d"),
                    sede_name,
                    cedula,
                    nombre,
                    cargo_name,
                    cod_servicio,
                    serv_name,
                    jefe_name,
                    "NO", # MULTISEDE
                    ev.curso_id,
                    ev.curso_plantilla,
                    ev.marca_origen,
                    ev.fecha_real_origen.strftime("%Y-%m-%d") if ev.fecha_real_origen else None,
                    ev.fecha_venc_origen.strftime("%Y-%m-%d") if ev.fecha_venc_origen else None,
                    ev.lectura,
                    ev.obligatorio,
                    ev.vigencia_meses,
                    ev.venc_efectivo.strftime("%Y-%m-%d") if ev.venc_efectivo else None,
                    ev.real_efectiva.strftime("%Y-%m-%d") if ev.real_efectiva else None,
                    ev.estado_detallado.value,
                    ev.marca,
                    ev.dias_para_vencer,
                    ev.cuenta_indicador
                ))

            # Resumen del colaborador
            summary = aggregate_collaborator_metrics(
                evaluations=evaluations,
                mes_analisis=mes_analisis,
                fecha_corte=fecha_corte,
                sede=sede_name,
                cedula=cedula,
                nombre=nombre,
                cargo_normalizado=cargo_name,
                cod_servicio=cod_servicio,
                nombre_servicio=serv_name,
                jefe_inmediato=jefe_name,
                multisede="NO"
            )

            total_cumplidos += summary.cumplidos
            total_obligatorios += summary.obligatorios

            resumen_rows.append((
                summary.mes_analisis,
                summary.fecha_corte.strftime("%Y-%m-%d"),
                summary.sede,
                summary.cedula,
                summary.nombre,
                summary.cargo_normalizado,
                summary.cod_servicio,
                summary.nombre_servicio,
                summary.jefe_inmediato,
                summary.multisede,
                summary.obligatorios,
                summary.vigentes,
                summary.por_vencer,
                summary.cumple_sin_fecha,
                summary.vencidos,
                summary.no_realizados,
                summary.sin_registro,
                summary.cumplidos,
                summary.pct_cumplimiento,
                summary.alertas,
                summary.cursos_pendientes
            ))

        # Inserción en lotes optimizados
        batch_size = 5000
        logger.info("Persistiendo %d registros en BGD_DASHBOARD_CURSOS_3100...", len(dashboard_rows))
        for i in range(0, len(dashboard_rows), batch_size):
            chunk = dashboard_rows[i:i + batch_size]
            self.repo.insert_dashboard_batch(chunk)

        logger.info("Persistiendo %d registros en BGD_RESUMEN_MES_3100...", len(resumen_rows))
        for i in range(0, len(resumen_rows), batch_size):
            chunk = resumen_rows[i:i + batch_size]
            self.repo.insert_resumen_mes_batch(chunk)

        overall_pct = (total_cumplidos / total_obligatorios * 100.0) if total_obligatorios > 0 else 0.0
        logger.info("Procesamiento finalizado con éxito.")
        logger.info("Métricas Globales: %d colaboradores | %d cursos obligatorios | %d cumplidos | Cumplimiento General: %.2f%%",
                    len(resumen_rows), total_obligatorios, total_cumplidos, overall_pct)


if __name__ == "__main__":
    service = MatrixCalculatorService()
    # Ejecutamos con la fecha de corte 2026-08-31
    service.run_calculation_and_load(fecha_corte=date(2026, 8, 31), ventana_dias=90, mes_analisis="2026-08")
