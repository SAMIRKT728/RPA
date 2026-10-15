USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2
-- Base de Datos: DGEMPRES99 (o base configurada)
-- Descripción  : Agregación consolidada a nivel de colaborador en dbo.BGD_MTZ3100_RESUMEN.
--                1. Toma la fecha de corte seleccionada (o la última evaluada en BGD_MTZ3100_DASH).
--                2. Consolida conteos: OBLIGATORIOS, VIGENTES, POR VENCER, CUMPLE SIN FECHA,
--                   VENCIDOS, NO REALIZADOS, SIN REGISTRO y CUMPLIDOS.
--                3. Calcula el porcentaje de cumplimiento: (CUMPLIDOS / OBLIGATORIOS) * 100.
--                4. Concatena alertas de gestión y lista los cursos pendientes de realizar o renovar.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2
    @FechaCorte DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Si no se especifica fecha de corte, toma la última fecha disponible desde DASH
    DECLARE @MesAnalisis VARCHAR(10);
    IF @FechaCorte IS NULL
    BEGIN
        SELECT TOP 1 @MesAnalisis = MES_ANALISIS 
        FROM dbo.BGD_MTZ3100_DASH 
        ORDER BY MES_ANALISIS DESC;

        IF @MesAnalisis IS NOT NULL
            SET @FechaCorte = EOMONTH(CAST(@MesAnalisis + '-01' AS DATE));
        ELSE
            SET @FechaCorte = EOMONTH(DATEADD(month, -1, GETDATE()));
    END;

    IF @MesAnalisis IS NULL
        SET @MesAnalisis = FORMAT(@FechaCorte, 'yyyy-MM');

    PRINT '=======================================================';
    PRINT 'Iniciando dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2';
    PRINT 'Fecha de Corte : ' + CONVERT(VARCHAR(10), @FechaCorte, 120);
    PRINT 'Mes de Análisis: ' + @MesAnalisis;
    PRINT '=======================================================';

    -- 2. Limpieza previa de la fecha de corte para idempotencia
    DELETE FROM dbo.BGD_MTZ3100_RESUMEN
    WHERE FECHA_CORTE = @FechaCorte OR MES_ANALISIS = @MesAnalisis;

    -- 3. Agregación e inserción directa en dbo.BGD_MTZ3100_RESUMEN
    INSERT INTO dbo.BGD_MTZ3100_RESUMEN (
        MES_ANALISIS,
        FECHA_CORTE,
        SEDE,
        CEDULA,
        NOMBRE_COLABORADOR,
        COD_SERVICIO,
        NOMBRE_SERVICIO,
        MULTISEDE,
        OBLIGATORIOS,
        VIGENTES,
        POR_VENCER,
        CUMPLE_SIN_FECHA,
        VENCIDOS,
        NO_REALIZADOS,
        SIN_REGISTRO,
        CUMPLIDOS,
        PCT_CUMPLIMIENTO,
        ALERTAS,
        CURSOS_PENDIENTES,
        FECHA_CALCULO
    )
    SELECT 
        d.MES_ANALISIS,
        @FechaCorte AS FECHA_CORTE,
        d.SEDE,
        d.CEDULA,
        d.NOMBRE_COLABORADOR,
        c.COD_SERVICIO,
        s.NOMBRE_SERVICIO,
        d.MULTISEDE,
        
        -- Conteo de Métricas Normativas
        SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS OBLIGATORIOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'VIGENTE' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VIGENTES,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS POR_VENCER,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'CUMPLE SIN FECHA' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS CUMPLE_SIN_FECHA,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'VENCIDO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VENCIDOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'NO REALIZADO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS NO_REALIZADOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO IN ('SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS SIN_REGISTRO,
        
        -- Cumplidos = Vigentes + Por Vencer + Cumple Sin Fecha (= CUENTA_INDICADOR)
        SUM(d.CUENTA_INDICADOR) AS CUMPLIDOS,
        
        -- % Cumplimiento = (Cumplidos / Obligatorios) * 100
        CASE 
            WHEN SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) > 0 
            THEN CAST(ROUND(SUM(d.CUENTA_INDICADOR) * 100.0 / SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END), 2) AS DECIMAL(5, 2))
            ELSE 0.00 
        END AS PCT_CUMPLIMIENTO,
        
        -- Alertas Consolidadas
        NULLIF(
            LTRIM(RTRIM(
                CONCAT(
                    CASE WHEN SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' THEN 1 ELSE 0 END) > 0 
                         THEN 'POR_VENCER (' + CAST(SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.SUBSANADO_CONTROL_CALIDAD IS NOT NULL THEN 1 ELSE 0 END) > 0 
                         THEN 'SUBSANADO_AUDITORIA (' + CAST(SUM(CASE WHEN d.SUBSANADO_CONTROL_CALIDAD IS NOT NULL THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'MARCA_DESACTUALIZADA' THEN 1 ELSE 0 END) > 0 
                         THEN 'MARCA_DESACTUALIZADA (' + CAST(SUM(CASE WHEN d.ALERTA = 'MARCA_DESACTUALIZADA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'FALTA_FECHA' THEN 1 ELSE 0 END) > 0 
                         THEN 'FALTA_FECHA (' + CAST(SUM(CASE WHEN d.ALERTA = 'FALTA_FECHA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'DISCREPANCIA_APLICABILIDAD' THEN 1 ELSE 0 END) > 0 
                         THEN 'DISCREPANCIA (' + CAST(SUM(CASE WHEN d.ALERTA = 'DISCREPANCIA_APLICABILIDAD' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'SIN_COLUMNA' THEN 1 ELSE 0 END) > 0 
                         THEN 'SIN_COLUMNA (' + CAST(SUM(CASE WHEN d.ALERTA = 'SIN_COLUMNA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END
                )
            )),
            ''
        ) AS ALERTAS,
        
        -- Cursos pendientes obligatorios concatenados
        ISNULL(
            STRING_AGG(
                CASE 
                    WHEN d.ESTADO_DETALLADO IN ('VENCIDO', 'NO REALIZADO', 'SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' 
                    THEN d.CURSO_NOMBRE 
                END, 
                '; '
            ) WITHIN GROUP (ORDER BY d.CURSO_ID),
            ''
        ) AS CURSOS_PENDIENTES,
        
        SYSUTCDATETIME() AS FECHA_CALCULO
    FROM dbo.BGD_MTZ3100_DASH d
    LEFT JOIN dbo.BGD_MTZ_COL c
        ON c.CEDULA COLLATE DATABASE_DEFAULT = d.CEDULA COLLATE DATABASE_DEFAULT
       AND c.SEDE COLLATE DATABASE_DEFAULT = d.SEDE COLLATE DATABASE_DEFAULT
    LEFT JOIN dbo.BGD_MTZ3100_SERVICIOS s
        ON s.COD_SERVICIO COLLATE DATABASE_DEFAULT = c.COD_SERVICIO COLLATE DATABASE_DEFAULT
    WHERE d.MES_ANALISIS = @MesAnalisis
    GROUP BY 
        d.MES_ANALISIS,
        d.SEDE,
        d.CEDULA,
        d.NOMBRE_COLABORADOR,
        c.COD_SERVICIO,
        s.NOMBRE_SERVICIO,
        d.MULTISEDE;

    DECLARE @FilasInsertadas INT = @@ROWCOUNT;
    PRINT 'dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2 finalizado. Total colaboradores consolidados: ' + CAST(@FilasInsertadas AS VARCHAR(10));
END;
GO
