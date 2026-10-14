"""
core/rules_engine.py
Motor de Reglas de Negocio para la Matriz de Cursos Norma 3100.
Principio: Alta Cohesión. Solo tiene la responsabilidad de evaluar y clasificar
el estado normativo y temporal de un curso individual.
Cero dependencias de base de datos o almacenamiento externo.
"""

from datetime import date, timedelta
from typing import Optional
from models.dto import CourseEvaluation, CourseStatus


# Cursos que habitualmente manejan 60 meses (5 años) de vigencia
DIPLOMADOS_60_MESES = {
    "DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO",
    "DIPLOMADO ONCO - HEMATOLOGIA PEDIATRICA",
    "DIPLOMADO ONCO - HEMATOLOGÍA PEDIATRICA",
    "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO",
    "DIPLOMADO URGENCIAS",
    "DIPLOMADO EN NEFROLOGÍA",
}


def get_course_vigencia_meses(course_name: str) -> int:
    """Retorna los meses de vigencia estándar del curso (60 para diplomados, 24 para cursos)."""
    norm = course_name.strip().upper()
    return 60 if norm in DIPLOMADOS_60_MESES else 24


def evaluate_single_course(
    curso_id: str,
    curso_plantilla: str,
    marca_raw: Optional[str],
    is_obligatory_by_matrix: bool,
    fecha_real: Optional[date],
    fecha_venc: Optional[date],
    fecha_corte: date,
    ventana_dias: int = 90,
    celda_origen: str = ""
) -> CourseEvaluation:
    """
    Evalúa el estado estricto de un curso individual según las reglas normativas:
    
    1. Si no es obligatorio por norma/cargo/servicio -> NO APLICA (cuenta = 0).
    2. Si es obligatorio:
       - Marca SI y vencimiento > corte + ventana -> VIGENTE (suma).
       - Marca SI y corte <= vencimiento <= corte + ventana -> POR VENCER (suma, alerta).
       - Marca NO con fecha registrada, o SI con vencimiento < corte -> VENCIDO (resta).
       - Marca NO sin fechas registradas -> NO REALIZADO (resta).
       - Exigido por norma pero la clínica no registra nada -> SIN REGISTRO (resta).
    """
    # Normalizar marca
    m = (marca_raw or "").strip().upper()
    vigencia_meses = get_course_vigencia_meses(curso_plantilla)
    
    # 1. Caso NO APLICA
    if not is_obligatory_by_matrix or m in ("-", "NA", "N/A", "NO APLICA", "NO_APLICA"):
        # Si la matriz explícitamente dice que no aplica al cargo
        if not is_obligatory_by_matrix:
            return CourseEvaluation(
                curso_id=curso_id,
                curso_plantilla=curso_plantilla,
                marca_origen=m if m else "NA",
                fecha_real_origen=fecha_real,
                fecha_venc_origen=fecha_venc,
                lectura="OK",
                obligatorio="NO",
                vigencia_meses=vigencia_meses,
                venc_efectivo=fecha_venc,
                real_efectiva=fecha_real,
                estado_detallado=CourseStatus.NO_APLICA,
                marca="N/A",
                dias_para_vencer=None,
                cuenta_indicador=0
            )

    # 2. Es Obligatorio
    obligatorio_str = "SI"
    cuenta_indicador = 1
    dias_para_vencer: Optional[int] = None
    if fecha_venc is not None:
        dias_para_vencer = (fecha_venc - fecha_corte).days

    # Caso Marca SI
    if m in ("SI", "S"):
        marca = "SI"
        if fecha_venc is not None:
            if fecha_venc < fecha_corte:
                estado = CourseStatus.VENCIDO
            elif fecha_venc <= (fecha_corte + timedelta(days=ventana_dias)):
                estado = CourseStatus.POR_VENCER
            else:
                estado = CourseStatus.VIGENTE
        else:
            # Marcado como hecho aunque falte fecha
            estado = CourseStatus.VIGENTE

    # Caso Marca NO
    elif m in ("NO", "N"):
        marca = "NO"
        if fecha_real is not None or fecha_venc is not None:
            estado = CourseStatus.VENCIDO
        else:
            estado = CourseStatus.NO_REALIZADO

    # Caso SIN REGISTRO (la norma lo exige pero no hay marca ni fecha)
    else:
        marca = "NO"
        estado = CourseStatus.SIN_REGISTRO

    return CourseEvaluation(
        curso_id=curso_id,
        curso_plantilla=curso_plantilla,
        marca_origen=m,
        fecha_real_origen=fecha_real,
        fecha_venc_origen=fecha_venc,
        lectura="OK",
        obligatorio=obligatorio_str,
        vigencia_meses=vigencia_meses,
        venc_efectivo=fecha_venc,
        real_efectiva=fecha_real,
        estado_detallado=estado,
        marca=marca,
        dias_para_vencer=dias_para_vencer,
        cuenta_indicador=cuenta_indicador
    )
