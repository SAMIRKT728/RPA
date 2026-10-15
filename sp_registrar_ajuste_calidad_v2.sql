USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.SP_REGISTRAR_AJUSTE_CALIDAD_V2
-- Base de Datos: DGEMPRES99 (o base configurada)
-- Descripción  : Registra o actualiza una novedad manual en dbo.BGD_MTZ3100_AUDITORIA
--                con trazabilidad histórica completa (OLD vs NEW) y recalcula
--                inmediata y puntualmente (in-place) BGD_MTZ3100_DASH y BGD_MTZ3100_RESUMEN
--                únicamente para el colaborador modificado (< 15 ms).
--
-- Opciones de @Recalcular:
--   1 (Predeterminado): Recálculo puntual e inmediato del colaborador en DASH y RESUMEN (< 15 ms).
--   2 : Recálculo global completo de toda la base (SP_POBLAR_DASH_V2 y RESUMEN_V2, ~11 s).
--   0 : Solo registra auditoría sin recalcular ni alterar tablas de salida.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE dbo.SP_REGISTRAR_AJUSTE_CALIDAD_V2
    @Cedula NVARCHAR(12),
    @CursoId VARCHAR(10),
    @FechaReal DATE = NULL,
    @FechaVenc DATE = NULL,
    @Motivo VARCHAR(100),
    @UsuarioModifica NVARCHAR(100) = NULL,
    @Observaciones NVARCHAR(500) = NULL,
    @Recalcular INT = 1
AS
BEGIN
    SET NOCOUNT ON;

    IF @UsuarioModifica IS NULL
        SET @UsuarioModifica = SYSTEM_USER;

    -- Normalizar CursoId y obtener nombre del curso y vigencia según catálogo
    DECLARE @CursoNombre NVARCHAR(150), @VigenciaMeses INT;
    SELECT 
        @CursoId = ID_CURSO,
        @CursoNombre = CURSO_NOMBRE, 
        @VigenciaMeses = VIGENCIA_MESES 
    FROM dbo.BGD_MTZ3100_CATCURSO 
    WHERE ID_CURSO = @CursoId OR CURSO_NOMBRE = @CursoId;

    IF @CursoNombre IS NULL
    BEGIN
        RAISERROR('El CURSO_ID o CURSO_NOMBRE especificado no existe en dbo.BGD_MTZ3100_CATCURSO.', 16, 1);
        RETURN;
    END;

    -- Si se dio FechaReal pero no FechaVenc, calcular vencimiento por vigencia
    IF @FechaReal IS NOT NULL AND @FechaVenc IS NULL
        SET @FechaVenc = DATEADD(month, @VigenciaMeses, @FechaReal);

    -- Obtener valores actuales (OLD) y mes de análisis desde BGD_MTZ3100_DASH
    DECLARE @FechaRealOld DATE = NULL,
            @FechaVencOld DATE = NULL,
            @EstadoOld VARCHAR(30) = NULL,
            @MesAnalisis VARCHAR(10) = NULL,
            @FechaCorte DATE = NULL;

    SELECT TOP 1
        @FechaRealOld = REAL_EFECTIVA,
        @FechaVencOld = VENC_EFECTIVO,
        @EstadoOld = ESTADO_DETALLADO,
        @MesAnalisis = MES_ANALISIS
    FROM dbo.BGD_MTZ3100_DASH
    WHERE CEDULA = @Cedula AND CURSO_ID = @CursoId
    ORDER BY MES_ANALISIS DESC;

    -- Obtener la fecha de corte de referencia
    SELECT TOP 1 @FechaCorte = FECHA_CORTE
    FROM dbo.BGD_MTZ3100_RESUMEN
    ORDER BY MES_ANALISIS DESC;

    IF @FechaCorte IS NULL
        SET @FechaCorte = EOMONTH(DATEADD(month, -1, GETDATE()));

    -- Determinar ESTADO_NEW basado en la nueva FechaVenc vs FechaCorte (ventana estándar de 90 días)
    DECLARE @EstadoNew VARCHAR(30) = 'NO REALIZADO';
    IF @FechaVenc IS NOT NULL
    BEGIN
        IF @FechaVenc < @FechaCorte
            SET @EstadoNew = 'VENCIDO';
        ELSE IF @FechaVenc < DATEADD(day, 90, @FechaCorte)
            SET @EstadoNew = 'POR VENCER';
        ELSE
            SET @EstadoNew = 'VIGENTE';
    END
    ELSE IF @FechaReal IS NOT NULL
    BEGIN
        SET @EstadoNew = 'VIGENTE';
    END;

    -- Desactivar ajustes previos activos para la misma cédula y curso
    UPDATE dbo.BGD_MTZ3100_AUDITORIA
    SET _activo = 0
    WHERE CEDULA_COLABORADOR = @Cedula AND CURSO_ID = @CursoId AND _activo = 1;

    -- Insertar nuevo ajuste activo con trazabilidad de fechas y estados
    INSERT INTO dbo.BGD_MTZ3100_AUDITORIA (
        CEDULA_COLABORADOR,
        CURSO_ID,
        CURSO_NOMBRE,
        FECHA_REAL_OLD,
        FECHA_VENC_OLD,
        FECHA_REAL_NEW,
        FECHA_VENC_NEW,
        ESTADO_OLD,
        ESTADO_NEW,
        MOTIVO,
        USUARIO_MODIFICA,
        OBSERVACIONES,
        _fecha_creacion,
        _activo
    ) VALUES (
        @Cedula,
        @CursoId,
        @CursoNombre,
        @FechaRealOld,
        @FechaVencOld,
        @FechaReal,
        @FechaVenc,
        @EstadoOld,
        @EstadoNew,
        @Motivo,
        @UsuarioModifica,
        @Observaciones,
        SYSUTCDATETIME(),
        1
    );

    DECLARE @NuevoIdAuditoria INT = SCOPE_IDENTITY();

    PRINT 'Ajuste de calidad registrado exitosamente (ID: ' + CAST(@NuevoIdAuditoria AS VARCHAR(10)) + ') para la cédula ' + @Cedula + ' en el curso ' + @CursoNombre;

    -- ==========================================================================================
    -- Recálculo automático:
    -- 1: Puntual e inmediato in-place (< 15 ms). Recomendado para plataformas web y ajustes unitarios.
    -- 2: Global completo (~11 s).
    -- 0: Sin recálculo.
    -- ==========================================================================================
    IF @Recalcular = 1
    BEGIN
        -- 1. Actualizar puntualmente la fila del colaborador y curso en BGD_MTZ3100_DASH
        UPDATE d
        SET 
            d.REAL_EFECTIVA = ISNULL(@FechaReal, d.REAL_EFECTIVA),
            d.VENC_EFECTIVO = ISNULL(@FechaVenc, d.VENC_EFECTIVO),
            d.ESTADO_DETALLADO = @EstadoNew,
            d.MARCA = CASE WHEN @EstadoNew IN ('VIGENTE', 'POR VENCER', 'CUMPLE SIN FECHA') THEN 'SI' ELSE 'NO' END,
            d.CUENTA_INDICADOR = CASE WHEN @EstadoNew IN ('VIGENTE', 'POR VENCER', 'CUMPLE SIN FECHA') THEN 1 ELSE 0 END,
            d.DIAS_PARA_VENCER = CASE WHEN @FechaVenc IS NOT NULL THEN DATEDIFF(day, @FechaCorte, @FechaVenc) ELSE NULL END,
            d.ALERTA = 'SUBSANADO_AUDITORIA',
            d.OBSERVACION = CONCAT('Subsanado en Auditoría: ', @Motivo),
            d.SUBSANADO_CONTROL_CALIDAD = @NuevoIdAuditoria,
            d.FECHA_CALCULO = SYSUTCDATETIME()
        FROM dbo.BGD_MTZ3100_DASH d
        WHERE d.CEDULA = @Cedula 
          AND d.CURSO_ID = @CursoId
          AND (@MesAnalisis IS NULL OR d.MES_ANALISIS = @MesAnalisis);

        -- 2. Recalcular puntualmente las métricas agregadas del colaborador en BGD_MTZ3100_RESUMEN
        ;WITH MetricasColaborador AS (
            SELECT 
                d.CEDULA,
                d.MES_ANALISIS,
                SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS OBLIGATORIOS,
                SUM(CASE WHEN d.ESTADO_DETALLADO = 'VIGENTE' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VIGENTES,
                SUM(CASE WHEN d.ESTADO_DETALLADO = 'POR VENCER' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS POR_VENCER,
                SUM(CASE WHEN d.ESTADO_DETALLADO = 'CUMPLE SIN FECHA' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS CUMPLE_SIN_FECHA,
                SUM(CASE WHEN d.ESTADO_DETALLADO = 'VENCIDO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS VENCIDOS,
                SUM(CASE WHEN d.ESTADO_DETALLADO = 'NO REALIZADO' AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS NO_REALIZADOS,
                SUM(CASE WHEN d.ESTADO_DETALLADO IN ('SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) AS SIN_REGISTRO,
                SUM(d.CUENTA_INDICADOR) AS CUMPLIDOS,
                CASE 
                    WHEN SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END) > 0 
                    THEN CAST(ROUND(SUM(d.CUENTA_INDICADOR) * 100.0 / SUM(CASE WHEN d.OBLIGATORIO = 'SI' THEN 1 ELSE 0 END), 2) AS DECIMAL(5, 2))
                    ELSE 0.00 
                END AS PCT_CUMPLIMIENTO,
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
                ISNULL(
                    STRING_AGG(
                        CASE 
                            WHEN d.ESTADO_DETALLADO IN ('VENCIDO', 'NO REALIZADO', 'SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' 
                            THEN d.CURSO_NOMBRE 
                        END, 
                        '; '
                    ) WITHIN GROUP (ORDER BY d.CURSO_ID),
                    ''
                ) AS CURSOS_PENDIENTES
            FROM dbo.BGD_MTZ3100_DASH d
            WHERE d.CEDULA = @Cedula
              AND (@MesAnalisis IS NULL OR d.MES_ANALISIS = @MesAnalisis)
            GROUP BY d.CEDULA, d.MES_ANALISIS
        )
        UPDATE r
        SET 
            r.OBLIGATORIOS = m.OBLIGATORIOS,
            r.VIGENTES = m.VIGENTES,
            r.POR_VENCER = m.POR_VENCER,
            r.CUMPLE_SIN_FECHA = m.CUMPLE_SIN_FECHA,
            r.VENCIDOS = m.VENCIDOS,
            r.NO_REALIZADOS = m.NO_REALIZADOS,
            r.SIN_REGISTRO = m.SIN_REGISTRO,
            r.CUMPLIDOS = m.CUMPLIDOS,
            r.PCT_CUMPLIMIENTO = m.PCT_CUMPLIMIENTO,
            r.ALERTAS = m.ALERTAS,
            r.CURSOS_PENDIENTES = m.CURSOS_PENDIENTES,
            r.FECHA_CALCULO = SYSUTCDATETIME()
        FROM dbo.BGD_MTZ3100_RESUMEN r
        INNER JOIN MetricasColaborador m
            ON m.CEDULA = r.CEDULA AND m.MES_ANALISIS = r.MES_ANALISIS;

        PRINT 'Recálculo puntual completado exitosamente para el colaborador ' + @Cedula;
    END
    ELSE IF @Recalcular = 2
    BEGIN
        PRINT 'Iniciando recálculo global de toda la base...';
        EXEC dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2;
        EXEC dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2;
        PRINT 'Recálculo global completado exitosamente.';
    END;
END;
GO
