USE DGEMPRES01;
GO

IF OBJECT_ID('dbo.SP_POBLAR_BGD_RESUMEN_MES_3100', 'P') IS NOT NULL
    DROP PROCEDURE dbo.SP_POBLAR_BGD_RESUMEN_MES_3100;
GO

CREATE PROCEDURE dbo.SP_POBLAR_BGD_RESUMEN_MES_3100
    @FechaCorte DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Si no se especifica fecha de corte, toma la última fecha de corte en el Dashboard
    IF @FechaCorte IS NULL
        SELECT @FechaCorte = MAX(FECHA_CORTE) FROM dbo.BGD_DASHBOARD_CURSOS_3100;

    PRINT '=======================================================';
    PRINT 'Iniciando SP_POBLAR_BGD_RESUMEN_MES_3100';
    PRINT 'Fecha de Corte: ' + CONVERT(VARCHAR(10), @FechaCorte, 120);
    PRINT '=======================================================';

    -- 2. Limpieza previa de la fecha de corte para garantizar idempotencia
    DELETE FROM dbo.BGD_RESUMEN_MES_3100
    WHERE FECHA_CORTE = @FechaCorte;

    -- 3. Agregación ultrarrápida indexada desde BGD_DASHBOARD_CURSOS_3100
    INSERT INTO dbo.BGD_RESUMEN_MES_3100 (
        MES_ANALISIS,
        FECHA_CORTE,
        SEDE,
        CEDULA,
        NOMBRE,
        CODIGO,
        ESTADO,
        CARGO_NORMALIZADO,
        COD_SERVICIO,
        NOMBRE_SERVICIO,
        JEFE_INMEDIATO,
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
        _fecha_calculo
    )
    SELECT 
        d.MES_ANALISIS,
        d.FECHA_CORTE,
        d.SEDE,
        d.CEDULA,
        d.NOMBRE,
        d.CODIGO,
        d.ESTADO,
        d.CARGO_NORMALIZADO,
        d.COD_SERVICIO,
        d.NOMBRE_SERVICIO,
        d.JEFE_INMEDIATO,
        d.MULTISEDE,
        
        -- Conteo de Métricas
        SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS OBLIGATORIOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'VIGENTE' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VIGENTES,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS POR_VENCER,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'CUMPLE SIN FECHA' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS CUMPLE_SIN_FECHA,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'VENCIDO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VENCIDOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO = 'NO REALIZADO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS NO_REALIZADOS,
        SUM(CASE WHEN d.ESTADO_DETALLADO IN ('SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS SIN_REGISTRO,
        
        -- CUMPLIDOS = Vigentes + Por Vencer + Cumple Sin Fecha (= CUENTA_INDICADOR)
        SUM(d.CUENTA_INDICADOR) AS CUMPLIDOS,
        
        -- % CUMPLIMIENTO = (Cumplidos / Obligatorios) * 100
        CASE 
            WHEN SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) > 0 
            THEN CAST(ROUND(SUM(d.CUENTA_INDICADOR) * 100.0 / SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END), 2) AS DECIMAL(5, 2))
            ELSE 0.00 
        END AS PCT_CUMPLIMIENTO,
        
        -- ALERTAS CONSOLIDADAS
        NULLIF(
            LTRIM(RTRIM(
                CONCAT(
                    CASE WHEN SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' THEN 1 ELSE 0 END) > 0 
                         THEN 'POR_VENCER (' + CAST(SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.SUBSANADO_CONTROL_CALIDAD IS NOT NULL THEN 1 ELSE 0 END) > 0 
                         THEN 'SUBSANADO_CALIDAD (' + CAST(SUM(CASE WHEN d.SUBSANADO_CONTROL_CALIDAD IS NOT NULL THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'MARCA_DESACTUALIZADA' THEN 1 ELSE 0 END) > 0 
                         THEN 'MARCA_DESACTUALIZADA (' + CAST(SUM(CASE WHEN d.ALERTA = 'MARCA_DESACTUALIZADA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'FALTA_FECHA' THEN 1 ELSE 0 END) > 0 
                         THEN 'FALTA_FECHA (' + CAST(SUM(CASE WHEN d.ALERTA = 'FALTA_FECHA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'DISCREPANCIA_APLICABILIDAD' THEN 1 ELSE 0 END) > 0 
                         THEN 'DISCREPANCIA (' + CAST(SUM(CASE WHEN d.ALERTA = 'DISCREPANCIA_APLICABILIDAD' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'SIN_COLUMNA' THEN 1 ELSE 0 END) > 0 
                         THEN 'SIN_COLUMNA (' + CAST(SUM(CASE WHEN d.ALERTA = 'SIN_COLUMNA' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END,
                    CASE WHEN SUM(CASE WHEN d.ALERTA = 'FECHA_FUERA_DE_RANGO' THEN 1 ELSE 0 END) > 0 
                         THEN 'FECHA_FUERA_DE_RANGO (' + CAST(SUM(CASE WHEN d.ALERTA = 'FECHA_FUERA_DE_RANGO' THEN 1 ELSE 0 END) AS VARCHAR(10)) + '); ' ELSE '' END
                )
            )),
            ''
        ) AS ALERTAS,
        
        -- CURSOS PENDIENTES (Concatenados con punto y coma)
        ISNULL(
            STRING_AGG(
                CASE 
                    WHEN d.ESTADO_DETALLADO IN ('VENCIDO', 'NO REALIZADO', 'SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' 
                    THEN d.CURSO_PLANTILLA 
                END, 
                '; '
            ) WITHIN GROUP (ORDER BY d.CURSO_ID),
            ''
        ) AS CURSOS_PENDIENTES,
        
        SYSUTCDATETIME() AS _fecha_calculo
    FROM dbo.BGD_DASHBOARD_CURSOS_3100 d
    WHERE d.FECHA_CORTE = @FechaCorte
    GROUP BY 
        d.MES_ANALISIS,
        d.FECHA_CORTE,
        d.SEDE,
        d.CEDULA,
        d.NOMBRE,
        d.CODIGO,
        d.ESTADO,
        d.CARGO_NORMALIZADO,
        d.COD_SERVICIO,
        d.NOMBRE_SERVICIO,
        d.JEFE_INMEDIATO,
        d.MULTISEDE;

    DECLARE @FilasInsertadas INT = @@ROWCOUNT;
    PRINT 'Proceso finalizado. Total colaboradores consolidados: ' + CAST(@FilasInsertadas AS VARCHAR(10));
END;
GO
