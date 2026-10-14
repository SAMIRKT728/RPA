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
--                y recalcula automáticamente BGD_MTZ3100_DASH y BGD_MTZ3100_RESUMEN.
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

    -- Obtener nombre del curso según catálogo
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

    -- Desactivar ajustes previos activos para la misma cédula y curso
    UPDATE dbo.BGD_MTZ3100_AUDITORIA
    SET _activo = 0
    WHERE CEDULA_COLABORADOR = @Cedula AND CURSO_ID = @CursoId AND _activo = 1;

    -- Insertar nuevo ajuste activo
    INSERT INTO dbo.BGD_MTZ3100_AUDITORIA (
        CEDULA_COLABORADOR,
        CURSO_ID,
        CURSO_NOMBRE,
        FECHA_REAL_NEW,
        FECHA_VENC_NEW,
        MOTIVO,
        USUARIO_MODIFICA,
        OBSERVACIONES,
        _fecha_creacion,
        _activo
    ) VALUES (
        @Cedula,
        @CursoId,
        @CursoNombre,
        @FechaReal,
        @FechaVenc,
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
