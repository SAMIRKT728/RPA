"""
core/metrics_calculator.py
Calculador y Agregador de Métricas por Colaborador.
Principio: Alta Cohesión. Solo tiene la responsabilidad de consolidar las evaluaciones
de cursos en indicadores KPI, alertas y listas de cursos pendientes.
"""

from datetime import date
from typing import List
from models.dto import CourseEvaluation, CourseStatus, CollaboratorSummary


def aggregate_collaborator_metrics(
    evaluations: List[CourseEvaluation],
    mes_analisis: str,
    fecha_corte: date,
    sede: str,
    cedula: str,
    nombre: str,
    cargo_normalizado: str,
    cod_servicio: str,
    nombre_servicio: str,
    jefe_inmediato: str,
    multisede: str = "NO"
) -> CollaboratorSummary:
    """
    Consolida las evaluaciones individuales de cursos en un resumen con KPIs.
    """
    obligatorios = 0
    vigentes = 0
    por_vencer = 0
    cumple_sin_fecha = 0
    vencidos = 0
    no_realizados = 0
    sin_registro = 0
    pendientes_list: List[str] = []

    for ev in evaluations:
        if ev.cuenta_indicador == 0:
            continue
        
        obligatorios += 1
        
        if ev.estado_detallado == CourseStatus.VIGENTE:
            vigentes += 1
            if ev.venc_efectivo is None:
                cumple_sin_fecha += 1
        elif ev.estado_detallado == CourseStatus.POR_VENCER:
            por_vencer += 1
        elif ev.estado_detallado == CourseStatus.VENCIDO:
            vencidos += 1
            pendientes_list.append(ev.curso_plantilla)
        elif ev.estado_detallado == CourseStatus.NO_REALIZADO:
            no_realizados += 1
            pendientes_list.append(ev.curso_plantilla)
        elif ev.estado_detallado == CourseStatus.SIN_REGISTRO:
            sin_registro += 1
            pendientes_list.append(ev.curso_plantilla)

    cumplidos = vigentes + por_vencer
    pct = round((cumplidos / obligatorios * 100.0), 1) if obligatorios > 0 else 0.0
    
    alerta_str = f"POR_VENCER ({por_vencer})" if por_vencer > 0 else ""
    cursos_pendientes_str = "; ".join(pendientes_list)

    return CollaboratorSummary(
        mes_analisis=mes_analisis,
        fecha_corte=fecha_corte,
        sede=sede,
        cedula=cedula,
        nombre=nombre,
        cargo_normalizado=cargo_normalizado,
        cod_servicio=cod_servicio,
        nombre_servicio=nombre_servicio,
        jefe_inmediato=jefe_inmediato,
        multisede=multisede,
        obligatorios=obligatorios,
        vigentes=vigentes,
        por_vencer=por_vencer,
        cumple_sin_fecha=cumple_sin_fecha,
        vencidos=vencidos,
        no_realizados=no_realizados,
        sin_registro=sin_registro,
        cumplidos=cumplidos,
        pct_cumplimiento=pct,
        alertas=alerta_str,
        cursos_pendientes=cursos_pendientes_str
    )
