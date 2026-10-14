"""
seed_catalogos_v2.py
Puebla los catalogos obligatorios de la nueva arquitectura:
1. dbo.BGD_MTZ3100_CATCURSO (28 cursos oficiales de la Res. 3100 con sus vigencias)
2. dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD (Matriz de obligatoriedad desde INDICE_OBLIGATORIEDAD.xlsx)
"""

import os
import sys
import pandas as pd
import pymssql
from config import config

COURSES_CATALOG = [
    ("BLS", "C01", 1, 24, 1, "TODOS"),
    ("ACLS", "C02", 2, 24, 1, "TODOS"),
    ("GESTION DEL DUELO", "C03", 3, 24, 1, "TODOS"),
    ("ATENCION A LAS VICTIMAS DE ATAQUES QUIMICOS", "C04", 4, 24, 1, "TODOS"),
    ("ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL", "C05", 5, 24, 1, "TODOS"),
    ("HUMANIZACION", "C06", 6, 24, 1, "TODOS"),
    ("GESTION OPERATIVA DE LA DONACION", "C07", 7, 24, 1, "TODOS"),
    ("DENGUE", "C08", 8, 24, 1, "TODOS"),
    ("POCT", "C09", 9, 24, 1, "TODOS"),
    ("PALS", "C10", 10, 24, 1, "0048;0049;0050;0089;0094;0103;0113"),
    ("NALS", "C11", 11, 24, 1, "0059;0088"),
    ("AIEPI", "C12", 12, 24, 1, "0048;0049;0050;0059;0089;0094;0103;0113"),
    ("MANEJO DEL DOLOR Y CUIDADOS PALIATIVOS", "C13", 13, 24, 1, "TODOS"),
    ("INMUNOLOGIA DE TRANSPLANTES", "C14", 14, 24, 1, "TODOS"),
    ("GESTION PRE-TRANSFUCIONAL", "C15", 15, 24, 1, "TODOS"),
    ("ADMINISTRACION DE MEDICAMENTOS", "C16", 16, 24, 1, "TODOS"),
    ("TOMA DE MUESTRAS", "C17", 17, 24, 1, "TODOS"),
    ("CADENA DE FRIO", "C18", 18, 24, 1, "0055;0056;0072;0100"),
    ("ATENCION DEL PACIENTE EN DIALISIS RENAL - DIALISIS", "C19", 19, 24, 1, "0076;0079"),
    ("ASESORIA PRE TEST POST TEST HIV", "C20", 20, 24, 1, "TODOS"),
    ("OVEM - COVE", "C21", 21, 24, 1, "TODOS"),
    ("DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO", "C22", 22, 60, 1, "0062"),
    ("DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO", "C23", 23, 60, 1, "0059;0088"),
    ("DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO", "C24", 24, 60, 1, "0080;0081;0082;0084;0085;0086;0106"),
    ("DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO", "C25", 25, 60, 1, "0048;0049;0050;0089;0094;0103;0113"),
    ("DIPLOMADO ONCO - HEMATOLOGIA PEDIATRICA", "C26", 26, 60, 1, "0113"),
    ("DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO", "C27", 27, 60, 1, "0090"),
    ("DIPLOMADO URGENCIAS", "C28", 28, 60, 1, "0091;0092;0093;0094;0095;0096;0097;0099;0103;0107;0108"),
]


def seed_catalogos(database: str = None):
    target_db = database or config.SQL_DATABASE or "DGEMPRES99"
    print(f"Conectando a {config.SQL_SERVER} ({target_db})...")

    conn = pymssql.connect(
        server=config.SQL_SERVER,
        port=config.SQL_PORT,
        user=config.SQL_USER,
        password=config.SQL_PASSWORD.strip(),
        database=target_db,
        autocommit=True
    )
    cur = conn.cursor()

    # 1. Poblar BGD_MTZ3100_CATCURSO
    print("Poblando dbo.BGD_MTZ3100_CATCURSO...")
    for c in COURSES_CATALOG:
        cur.execute("""
        IF NOT EXISTS (SELECT 1 FROM dbo.BGD_MTZ3100_CATCURSO WHERE CURSO_NOMBRE = %s)
        BEGIN
            INSERT INTO dbo.BGD_MTZ3100_CATCURSO (
                CURSO_NOMBRE, ID_CURSO, ORDEN, VIGENCIA_MESES, ACTIVO, 
                SERVICIOS_DEFECTO, FECHA_CREACION, USUARIO_CREACION
            ) VALUES (%s, %s, %d, %d, %d, %s, SYSUTCDATETIME(), 'SYSTEM_RPA');
        END
        ELSE
        BEGIN
            UPDATE dbo.BGD_MTZ3100_CATCURSO
            SET ID_CURSO = %s, ORDEN = %d, VIGENCIA_MESES = %d, ACTIVO = %d,
                SERVICIOS_DEFECTO = %s, FECHA_ACTUALIZACION = SYSUTCDATETIME()
            WHERE CURSO_NOMBRE = %s;
        END
        """, (c[0], c[0], c[1], c[2], c[3], c[4], c[5], c[1], c[2], c[3], c[4], c[5], c[0]))

    cur.execute("SELECT COUNT(*) FROM dbo.BGD_MTZ3100_CATCURSO")
    print(f"Total cursos en BGD_MTZ3100_CATCURSO: {cur.fetchone()[0]}")

    # 2. Poblar BGD_MTZ_INDICE_OBLIGATORIEDAD desde Excel
    excel_path = "INDICE_OBLIGATORIEDAD.xlsx"
    if os.path.exists(excel_path):
        print(f"Leyendo '{excel_path}'...")
        df = pd.read_excel(excel_path)
        print(f"Cargando {len(df)} registros en dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD...")
        
        for _, row in df.iterrows():
            cargo = str(row["CARGO"]).strip()
            curso = str(row["CURSO_PLANTILLA"]).strip()
            servicios = str(row["CODIGOS_SERVICIO"]).strip()
            estado = str(row["ESTADO"]).strip()

            cur.execute("""
            IF NOT EXISTS (
                SELECT 1 FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD 
                WHERE CARGO = %s AND COD_CURSO = %s
            )
            BEGIN
                INSERT INTO dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD (
                    CARGO, COD_CURSO, CODIGOS_SERVICIO, ESTADO, FECHA_CARGA
                ) VALUES (%s, %s, %s, %s, SYSUTCDATETIME());
            END
            ELSE
            BEGIN
                UPDATE dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD
                SET CODIGOS_SERVICIO = %s, ESTADO = %s, FECHA_CARGA = SYSUTCDATETIME()
                WHERE CARGO = %s AND COD_CURSO = %s;
            END
            """, (cargo, curso, cargo, curso, servicios, estado, servicios, estado, cargo, curso))

        cur.execute("SELECT COUNT(*) FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD")
        print(f"Total registros en BGD_MTZ_INDICE_OBLIGATORIEDAD: {cur.fetchone()[0]}")

    conn.close()
    print("Catalogos inicializados exitosamente.")


if __name__ == "__main__":
    seed_catalogos()
