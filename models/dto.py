"""
models/dto.py
Objetos de Transferencia de Datos (DTO) y Enums.
Garantiza Bajo Acoplamiento definiendo contratos claros e inmutables entre capas.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, List, Dict, Any


class CourseStatus(str, Enum):
    VIGENTE = "VIGENTE"
    POR_VENCER = "POR VENCER"
    VENCIDO = "VENCIDO"
    NO_REALIZADO = "NO REALIZADO"
    NO_APLICA = "NO APLICA"
    SIN_REGISTRO = "SIN REGISTRO"


@dataclass(frozen=True)
class CourseEvaluation:
    """Resultado de evaluar un único curso frente a una fecha de corte."""
    curso_id: str
    curso_plantilla: str
    marca_origen: str
    fecha_real_origen: Optional[date]
    fecha_venc_origen: Optional[date]
    lectura: str
    obligatorio: str                # 'SI' o 'NO'
    vigencia_meses: int
    venc_efectivo: Optional[date]
    real_efectiva: Optional[date]
    estado_detallado: CourseStatus
    marca: str                      # 'SI', 'NO', 'N/A'
    dias_para_vencer: Optional[int]
    cuenta_indicador: int           # 1 si cuenta en obligatorios, 0 si no


@dataclass(frozen=True)
class CollaboratorSummary:
    """Resumen mensual consolidado de cumplimiento por colaborador."""
    mes_analisis: str
    fecha_corte: date
    sede: str
    cedula: str
    nombre: str
    cargo_normalizado: str
    cod_servicio: str
    nombre_servicio: str
    jefe_inmediato: str
    multisede: str
    obligatorios: int
    vigentes: int
    por_vencer: int
    cumple_sin_fecha: int
    vencidos: int
    no_realizados: int
    sin_registro: int
    cumplidos: int
    pct_cumplimiento: float
    alertas: str
    cursos_pendientes: str
