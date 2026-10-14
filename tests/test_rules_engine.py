"""
tests/test_rules_engine.py
Test unitario formal para verificar las reglas de cálculo contra el caso de prueba:
FUENTES MAESTRE LIZETH CAROLINA (1065616718).
"""

import unittest
from datetime import date
from core.rules_engine import evaluate_single_course
from core.metrics_calculator import aggregate_collaborator_metrics
from models.dto import CourseStatus


class TestRulesEngineGoldenCase(unittest.TestCase):
    def setUp(self):
        self.corte = date(2026, 8, 31)
        self.ventana = 90
        
        # Definición de cursos evaluados para Lizeth Carolina
        self.courses_data = [
            ("C01", "BLS", "SI", True, date(2025, 10, 29), date(2027, 10, 29)),
            ("C02", "ACLS", "NA", False, None, None),
            ("C03", "GESTION DEL DUELO", "SI", True, date(2024, 11, 8), date(2026, 11, 8)),
            ("C04", "ATENCION A LAS VICTIMAS DE ATAQUES QUIMICOS", "SI", True, date(2024, 11, 8), date(2026, 11, 8)),
            ("C05", "ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL", "SI", True, date(2024, 11, 8), date(2026, 11, 8)),
            ("C06", "HUMANIZACION", "NO", True, date(2023, 8, 15), date(2025, 8, 14)),
            ("C07", "GESTION OPERATIVA DE LA DONACION", "NA", False, None, None),
            ("C08", "DENGUE", "SI", True, date(2025, 10, 29), date(2027, 10, 29)),
            ("C09", "POCT", "NO", True, None, None),
            ("C10", "PALS", "NO", False, None, None),
            ("C11", "NALS", "NA", False, None, None),
            ("C12", "AIEPI", "SI", False, date(2008, 9, 21), date(2010, 9, 21)),
            ("C13", "MANEJO DEL DOLOR Y CUIDADOS PALIATIVOS", "NA", False, None, None),
            ("C14", "INMUNOLOGIA DE TRANSPLANTES", "NA", False, None, None),
            ("C15", "GESTION PRE-TRANSFUCIONAL", "NA", False, None, None),
            ("C16", "ADMINISTRACION DE MEDICAMENTOS", "NO", True, None, None),
            ("C17", "TOMA DE MUESTRAS", "NO", True, None, None),
            ("C18", "CADENA DE FRIO", "NO", False, None, None),
            ("C19", "ATENCION DEL PACIENTE EN DIALISIS RENAL - DIALISIS", "NO", False, None, None),
            ("C20", "ASESORIA PRE TEST POST TEST HIV", "NO", False, None, None),
            ("C21", "OVEM - COVE", "NA", False, None, None),
            ("C22", "DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO", "NO", False, None, None),
            ("C23", "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO", "NA", False, None, None),
            ("C24", "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO", "NA", False, None, None),
            ("C25", "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO", "NO", False, None, None),
            ("C26", "DIPLOMADO ONCO - HEMATOLOGIA PEDIATRICA", "NO", False, None, None),
            ("C27", "DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO", "NO", False, None, None),
            ("C28", "DIPLOMADO URGENCIAS", "NA", False, None, None)
        ]

    def test_lizeth_carolina_evaluations(self):
        evaluations = []
        for cid, cname, marca, is_obl, f_real, f_venc in self.courses_data:
            ev = evaluate_single_course(
                curso_id=cid,
                curso_plantilla=cname,
                marca_raw=marca,
                is_obligatory_by_matrix=is_obl,
                fecha_real=f_real,
                fecha_venc=f_venc,
                fecha_corte=self.corte,
                ventana_dias=self.ventana
            )
            evaluations.append(ev)

        # 1. Verificar estados individuales clave
        self.assertEqual(evaluations[0].estado_detallado, CourseStatus.VIGENTE)       # BLS
        self.assertEqual(evaluations[1].estado_detallado, CourseStatus.NO_APLICA)      # ACLS
        self.assertEqual(evaluations[2].estado_detallado, CourseStatus.POR_VENCER)    # DUELO
        self.assertEqual(evaluations[3].estado_detallado, CourseStatus.POR_VENCER)    # ATAQUES QUIMICOS
        self.assertEqual(evaluations[4].estado_detallado, CourseStatus.POR_VENCER)    # VIOLENCIA SEXUAL
        self.assertEqual(evaluations[5].estado_detallado, CourseStatus.VENCIDO)       # HUMANIZACION
        self.assertEqual(evaluations[7].estado_detallado, CourseStatus.VIGENTE)       # DENGUE
        self.assertEqual(evaluations[8].estado_detallado, CourseStatus.NO_REALIZADO)  # POCT
        self.assertEqual(evaluations[11].estado_detallado, CourseStatus.NO_APLICA)    # AIEPI (no aplica a aux hosp)
        self.assertEqual(evaluations[15].estado_detallado, CourseStatus.NO_REALIZADO) # ADM MEDICAMENTOS
        self.assertEqual(evaluations[16].estado_detallado, CourseStatus.NO_REALIZADO) # TOMA DE MUESTRAS

        # 2. Consolidar resumen
        summary = aggregate_collaborator_metrics(
            evaluations=evaluations,
            mes_analisis="2026-08",
            fecha_corte=self.corte,
            sede="ALTA",
            cedula="1065616718",
            nombre="FUENTES MAESTRE LIZETH CAROLINA",
            cargo_normalizado="AUXILIAR DE ENFERMERIA",
            cod_servicio="0045",
            nombre_servicio="HOSPITALIZACION SEXTO PISO B",
            jefe_inmediato="GARCIA PEÑARANDA LUZ DARY",
            multisede="NO"
        )

        # 3. Validar métricas agregadas exactas
        self.assertEqual(summary.obligatorios, 9)
        self.assertEqual(summary.vigentes, 2)
        self.assertEqual(summary.por_vencer, 3)
        self.assertEqual(summary.cumplidos, 5)
        self.assertEqual(summary.vencidos, 1)
        self.assertEqual(summary.no_realizados, 3)
        self.assertEqual(summary.sin_registro, 0)
        self.assertEqual(summary.pct_cumplimiento, 55.6)
        self.assertEqual(summary.alertas, "POR_VENCER (3)")
        self.assertEqual(
            summary.cursos_pendientes,
            "HUMANIZACION; POCT; ADMINISTRACION DE MEDICAMENTOS; TOMA DE MUESTRAS"
        )


if __name__ == "__main__":
    unittest.main()
