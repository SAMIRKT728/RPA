"""
data_access/db_repository.py
Repositorio de Acceso a Base de Datos (SQL Server).
Principio: Alta Cohesión. Solo tiene la responsabilidad de ejecutar DDL,
crear tablas optimizadas con índices por FECHA_CORTE y persistir lotes de registros.
Bajo Acoplamiento: No conoce lógica de reglas de negocio, solo recibe DTOs/tuplas preparadas.
"""

import logging
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, date
import pymssql
from config import config
from models.dto import CourseEvaluation, CollaboratorSummary

logger = logging.getLogger("RPA.DbRepository")


class DbRepository:
    def __init__(self, database: str = "DGEMPRES01"):
        self.database = database
        self.server = config.SQL_SERVER
        self.port = config.SQL_PORT
        self.user = config.SQL_USER
        self.password = config.SQL_PASSWORD

    def _get_connection(self, autocommit: bool = True):
        return pymssql.connect(
            server=self.server,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            autocommit=autocommit
        )

    def init_tables_and_indexes(self):
        """
        Crea las tablas de persistencia si no existen, garantizando índices
        agrupados y secundarios indexados por FECHA_CORTE.
        """
        conn = self._get_connection(autocommit=True)
        cursor = conn.cursor()
        
        # 1. Tabla de Dataset Dashboard (Granular: Persona x Curso)
        cursor.execute("""
        IF OBJECT_ID('dbo.BGD_DASHBOARD_CURSOS_3100', 'U') IS NOT NULL
        BEGIN
            -- Si existe con la estructura previa (con CELDA_ORIGEN o MARCA_PLANTILLA), recrear
            IF COL_LENGTH('dbo.BGD_DASHBOARD_CURSOS_3100', 'CELDA_ORIGEN') IS NOT NULL 
               OR COL_LENGTH('dbo.BGD_DASHBOARD_CURSOS_3100', 'MARCA_PLANTILLA') IS NOT NULL
            BEGIN
                DROP TABLE dbo.BGD_DASHBOARD_CURSOS_3100;
            END
            ELSE
            BEGIN
                ALTER TABLE dbo.BGD_DASHBOARD_CURSOS_3100 ALTER COLUMN NOMBRE NVARCHAR(200) NULL;
            END
        END

        IF OBJECT_ID('dbo.BGD_DASHBOARD_CURSOS_3100', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.BGD_DASHBOARD_CURSOS_3100 (
                ID BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                MES_ANALISIS VARCHAR(10) NOT NULL,
                FECHA_CORTE DATE NOT NULL,
                SEDE VARCHAR(50) NOT NULL,
                CEDULA NVARCHAR(12) NOT NULL,
                NOMBRE NVARCHAR(200) NULL,
                CODIGO NVARCHAR(50) NULL,
                ESTADO NVARCHAR(50) NULL,
                CARGO_NORMALIZADO NVARCHAR(150) NULL,
                COD_SERVICIO VARCHAR(20) NULL,
                NOMBRE_SERVICIO NVARCHAR(150) NULL,
                JEFE_INMEDIATO NVARCHAR(200) NULL,
                MULTISEDE VARCHAR(5) DEFAULT 'NO',
                CURSO_ID VARCHAR(10) NOT NULL,
                CURSO_PLANTILLA NVARCHAR(150) NOT NULL,
                MARCA_ORIGEN VARCHAR(20) NULL,
                FECHA_REAL_ORIGEN DATE NULL,
                FECHA_VENC_ORIGEN DATE NULL,
                LECTURA VARCHAR(20) DEFAULT 'OK',
                OBLIGATORIO VARCHAR(2) NOT NULL,
                VIGENCIA_MESES INT NOT NULL,
                VENC_EFECTIVO DATE NULL,
                REAL_EFECTIVA DATE NULL,
                ESTADO_DETALLADO VARCHAR(30) NOT NULL,
                MARCA VARCHAR(10) NOT NULL,
                DIAS_PARA_VENCER INT NULL,
                CUENTA_INDICADOR INT NOT NULL,
                ALERTA VARCHAR(50) NULL,
                OBSERVACION NVARCHAR(250) NULL,
                SUBSANADO_CONTROL_CALIDAD INT NULL,
                _fecha_calculo DATETIME2 DEFAULT SYSUTCDATETIME()
            );

            CREATE NONCLUSTERED INDEX IX_BGD_DASHBOARD_CORTE_SEDE 
            ON dbo.BGD_DASHBOARD_CURSOS_3100 (FECHA_CORTE, SEDE, CEDULA, CURSO_ID);

            CREATE NONCLUSTERED INDEX IX_BGD_DASHBOARD_ESTADO 
            ON dbo.BGD_DASHBOARD_CURSOS_3100 (FECHA_CORTE, ESTADO_DETALLADO);

            CREATE NONCLUSTERED INDEX IX_BGD_DASHBOARD_CURSO 
            ON dbo.BGD_DASHBOARD_CURSOS_3100 (FECHA_CORTE, CURSO_PLANTILLA);
        END
        """)

        # 2. Tabla de Resumen de Mes (Consolidado por Colaborador)
        cursor.execute("""
        IF OBJECT_ID('dbo.BGD_RESUMEN_MES_3100', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.BGD_RESUMEN_MES_3100 (
                ID BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                MES_ANALISIS VARCHAR(10) NOT NULL,
                FECHA_CORTE DATE NOT NULL,
                SEDE VARCHAR(50) NOT NULL,
                CEDULA NVARCHAR(12) NOT NULL,
                NOMBRE NVARCHAR(200) NOT NULL,
                CODIGO NVARCHAR(50) NULL,
                ESTADO NVARCHAR(50) NULL,
                CARGO_NORMALIZADO NVARCHAR(150) NULL,
                COD_SERVICIO VARCHAR(20) NULL,
                NOMBRE_SERVICIO NVARCHAR(150) NULL,
                JEFE_INMEDIATO NVARCHAR(200) NULL,
                MULTISEDE VARCHAR(5) DEFAULT 'NO',
                OBLIGATORIOS INT NOT NULL,
                VIGENTES INT NOT NULL,
                POR_VENCER INT NOT NULL,
                CUMPLE_SIN_FECHA INT NOT NULL,
                VENCIDOS INT NOT NULL,
                NO_REALIZADOS INT NOT NULL,
                SIN_REGISTRO INT NOT NULL,
                CUMPLIDOS INT NOT NULL,
                PCT_CUMPLIMIENTO DECIMAL(5, 2) NOT NULL,
                ALERTAS VARCHAR(250) NULL,
                CURSOS_PENDIENTES NVARCHAR(MAX) NULL,
                _fecha_calculo DATETIME2 DEFAULT SYSUTCDATETIME()
            );

            CREATE NONCLUSTERED INDEX IX_BGD_RESUMEN_MES_CORTE 
            ON dbo.BGD_RESUMEN_MES_3100 (FECHA_CORTE, SEDE, CEDULA);

            CREATE NONCLUSTERED INDEX IX_BGD_RESUMEN_JEFE 
            ON dbo.BGD_RESUMEN_MES_3100 (FECHA_CORTE, JEFE_INMEDIATO, PCT_CUMPLIMIENTO);
        END
        """)

        # 3. Tabla de Catálogo de Jefes Unificados MX100
        cursor.execute("""
        IF OBJECT_ID('dbo.BGD_JEFES_UNIFICADOS_MX100', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.BGD_JEFES_UNIFICADOS_MX100 (
                NombreUnificado NVARCHAR(250) NOT NULL PRIMARY KEY,
                Variantes NVARCHAR(MAX) NOT NULL,
                CantidadVariantes INT NOT NULL,
                _fecha_calculo DATETIME2 DEFAULT SYSUTCDATETIME()
            );

            CREATE NONCLUSTERED INDEX IX_BGD_JEFES_UNIFICADOS_CANTIDAD
            ON dbo.BGD_JEFES_UNIFICADOS_MX100 (CantidadVariantes DESC);
        END
        """)

        # 4. Tabla de Auditoría y Ajustes de Control de Calidad
        cursor.execute("""
        IF OBJECT_ID('dbo.BGD_CONTROL_CALIDAD_3100', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.BGD_CONTROL_CALIDAD_3100 (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                CEDULA NVARCHAR(12) NOT NULL,
                CURSO_ID VARCHAR(10) NOT NULL,
                CURSO_PLANTILLA NVARCHAR(150) NOT NULL,
                FECHA_REAL DATE NOT NULL,
                FECHA_VENC DATE NOT NULL,
                MOTIVO VARCHAR(100) NOT NULL,
                USUARIO_MODIFICA NVARCHAR(100) DEFAULT SYSTEM_USER,
                OBSERVACIONES NVARCHAR(500) NULL,
                _fecha_creacion DATETIME2 DEFAULT SYSUTCDATETIME(),
                _activo BIT DEFAULT 1,
                CONSTRAINT UQ_CONTROL_CALIDAD UNIQUE (CEDULA, CURSO_ID)
            );
        END
        """)

        conn.close()
        logger.info("Tablas e índices inicializados correctamente en %s.", self.database)

    def clean_records_for_corte(self, fecha_corte: date):
        """Elimina cálculos previos para la misma fecha de corte para idempotencia."""
        conn = self._get_connection(autocommit=True)
        cursor = conn.cursor()
        corte_str = fecha_corte.strftime("%Y-%m-%d")
        cursor.execute("DELETE FROM dbo.BGD_DASHBOARD_CURSOS_3100 WHERE FECHA_CORTE = %s", (corte_str,))
        cursor.execute("DELETE FROM dbo.BGD_RESUMEN_MES_3100 WHERE FECHA_CORTE = %s", (corte_str,))
        conn.close()

    def insert_dashboard_batch(self, rows: List[Tuple]):
        """Inserta un lote de registros granulares en BGD_DASHBOARD_CURSOS_3100."""
        if not rows:
            return
        conn = self._get_connection(autocommit=True)
        cursor = conn.cursor()
        sql = """
        INSERT INTO dbo.BGD_DASHBOARD_CURSOS_3100 (
            MES_ANALISIS, FECHA_CORTE, SEDE, CEDULA, NOMBRE,
            CARGO_NORMALIZADO, COD_SERVICIO, NOMBRE_SERVICIO, JEFE_INMEDIATO, MULTISEDE,
            CURSO_ID, CURSO_PLANTILLA, MARCA_ORIGEN, FECHA_REAL_ORIGEN, FECHA_VENC_ORIGEN,
            LECTURA, OBLIGATORIO, VIGENCIA_MESES, VENC_EFECTIVO,
            REAL_EFECTIVA, ESTADO_DETALLADO, MARCA,
            DIAS_PARA_VENCER, CUENTA_INDICADOR
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s
        )
        """
        cursor.executemany(sql, rows)
        conn.close()

    def insert_resumen_mes_batch(self, rows: List[Tuple]):
        """Inserta un lote de resúmenes consolidados en BGD_RESUMEN_MES_3100."""
        if not rows:
            return
        conn = self._get_connection(autocommit=True)
        cursor = conn.cursor()
        sql = """
        INSERT INTO dbo.BGD_RESUMEN_MES_3100 (
            MES_ANALISIS, FECHA_CORTE, SEDE, CEDULA, NOMBRE,
            CARGO_NORMALIZADO, COD_SERVICIO, NOMBRE_SERVICIO, JEFE_INMEDIATO, MULTISEDE,
            OBLIGATORIOS, VIGENTES, POR_VENCER, CUMPLE_SIN_FECHA, VENCIDOS,
            NO_REALIZADOS, SIN_REGISTRO, CUMPLIDOS, PCT_CUMPLIMIENTO, ALERTAS,
            CURSOS_PENDIENTES
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s
        )
        """
        cursor.executemany(sql, rows)
        conn.close()
