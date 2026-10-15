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
--                automáticamente BGD_MTZ3100_DASH y BGD_MTZ3100_RESUMEN.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE dbo.SP_REGISTRAR_AJUSTE_CALIDAD_V2
    @Cedula NVARCHAR(12),
    @CursoId VARCHAR(10),
    @FechaReal DATE = NULL,
    @FechaVenc DATE = NULL,
    @Motivo VARCHAR(100),
    @UsuarioModifica NVARCHAR(100) = NULL,
    @Observaciones NVARCHAR(500) = NULL,
    @Recalcular BIT = 1
AS
BEGIN
    SET NOCOUNT ON;

    IF @UsuarioModifica IS NULL
        SET @UsuarioModifica = SYSTEM_USER;

    -- Obtener nombre del curso y vigencia según catálogo
    DECLARE @CursoNombre NVARCHAR(150), @VigenciaMeses INT;
    SELECT @CursoNombre = CURSO_NOMBRE, @VigenciaMeses = VIGENCIA_MESES 
    FROM dbo.BGD_MTZ3100_CATCURSO 
    WHERE ID_CURSO = @CursoId OR CURSO_NOMBRE = @CursoId;

    IF @CursoNombre IS NULL
    BEGIN
        RAISERROR('El CURSO_ID especificado no existe en dbo.BGD_MTZ3100_CATCURSO.', 16, 1);
        RETURN;
    END;

    -- Si se dio FechaReal pero no FechaVenc, calcular vencimiento por vigencia
    IF @FechaReal IS NOT NULL AND @FechaVenc IS NULL
        SET @FechaVenc = DATEADD(month, @VigenciaMeses, @FechaReal);

    -- Obtener valores actuales (OLD) desde BGD_MTZ3100_DASH
    DECLARE @FechaRealOld DATE = NULL,
            @FechaVencOld DATE = NULL,
            @EstadoOld VARCHAR(30) = NULL,
            @FechaCorte DATE = NULL;

    SELECT TOP 1
        @FechaRealOld = REAL_EFECTIVA,
        @FechaVencOld = VENC_EFECTIVO,
        @EstadoOld = ESTADO_DETALLADO
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

    PRINT 'Ajuste de calidad registrado exitosamente para la cédula ' + @Cedula + ' en el curso ' + @CursoNombre;

    -- Recálculo automático si se solicita
    IF @Recalcular = 1
    BEGIN
        EXEC dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2;
        EXEC dbo.SP_POBLAR_BGD_MTZ3100_RESUMEN_V2;
    END;
END;
GO
