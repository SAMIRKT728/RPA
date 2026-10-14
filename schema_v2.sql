USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Script: schema_v2.sql
-- Descripción: Garantiza la existencia física e índices de todas las tablas
--              de la nueva arquitectura normalizada en SQL Server.
-- ==========================================================================================

-- 1. Catálogo de Servicios
IF OBJECT_ID('dbo.BGD_MTZ3100_SERVICIOS', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.BGD_MTZ3100_SERVICIOS (
        COD_SERVICIO VARCHAR(10) NOT NULL PRIMARY KEY,
        NOMBRE_SERVICIO NVARCHAR(150) NOT NULL,
        CATEGORIA NVARCHAR(100) NULL,
        ESTADO VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
        [FECHA CARGA] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END;

-- 2. Colaboradores por Sede
IF OBJECT_ID('dbo.BGD_MTZ_COL', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.BGD_MTZ_COL (
        CEDULA NVARCHAR(12) NOT NULL,
        SEDE VARCHAR(50) NOT NULL,
        NOMBRE_COLABORADOR NVARCHAR(200) NOT NULL,
        CODIGO NVARCHAR(50) NULL,
        ESTADO NVARCHAR(50) NULL,
        CARGO NVARCHAR(150) NOT NULL,
        COD_SERVICIO VARCHAR(10) NOT NULL,
        [JEFE INMEDIATO] NVARCHAR(200) NOT NULL,
        [FECHA CARGA] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_BGD_MTZ_COL PRIMARY KEY (CEDULA, SEDE)
    );

    CREATE NONCLUSTERED INDEX IX_BGD_MTZ_COL_JEFE 
    ON dbo.BGD_MTZ_COL (SEDE, [JEFE INMEDIATO]);
END;

-- 3. Jefes Inmediatos (BDG_MTZ_JEFE)
IF OBJECT_ID('dbo.BDG_MTZ_JEFE', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.BDG_MTZ_JEFE (
        CEDULA NVARCHAR(12) NULL,
        [NOMBRE DEL JEFE] NVARCHAR(200) NOT NULL,
        SEDE VARCHAR(50) NOT NULL,
        [FECHA CARGA] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );

    CREATE NONCLUSTERED INDEX IX_BDG_MTZ_JEFE_SEDE 
    ON dbo.BDG_MTZ_JEFE (SEDE, [NOMBRE DEL JEFE]);
END;

PRINT 'Tablas e índices de la nueva arquitectura verificados exitosamente.';
GO

