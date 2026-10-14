USE DGEMPRES01;
GO

IF OBJECT_ID('dbo.SP_REGISTRAR_AJUSTE_CALIDAD', 'P') IS NOT NULL
    DROP PROCEDURE dbo.SP_REGISTRAR_AJUSTE_CALIDAD;
GO

CREATE PROCEDURE dbo.SP_REGISTRAR_AJUSTE_CALIDAD
    @Cedula NVARCHAR(12),
    @CursoId VARCHAR(10),
    @FechaReal DATE = NULL,
    @FechaVenc DATE = NULL,
    @Motivo VARCHAR(100),
    @Usuario NVARCHAR(100) = NULL,
    @Observaciones NVARCHAR(500) = NULL,
    @FechaCorte DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Determinar la Fecha de Corte objetivo (si no se envía, toma la fecha de corte registrada del colaborador)
    IF @FechaCorte IS NULL
    BEGIN
        SELECT TOP 1 @FechaCorte = FECHA_CORTE
        FROM dbo.BGD_DASHBOARD_CURSOS_3100
        WHERE CEDULA = @Cedula
        ORDER BY FECHA_CORTE DESC;

        -- Respaldo general si el colaborador no estuviera en Dashboard
        IF @FechaCorte IS NULL
            SELECT @FechaCorte = MAX(FECHA_CORTE) FROM dbo.BGD_DASHBOARD_CURSOS_3100;
        
        IF @FechaCorte IS NULL
            SET @FechaCorte = EOMONTH(DATEADD(month, -1, GETDATE()));
    END;

    -- 2. Validar que la cédula y el curso existan en el modelo o catálogo
    DECLARE @CursoPlantilla NVARCHAR(150);
    DECLARE @VigenciaMeses INT = 24;

    SELECT TOP 1 
        @CursoPlantilla = CURSO_PLANTILLA,
        @VigenciaMeses = ISNULL(VIGENCIA_MESES, 24)
    FROM dbo.BGD_DASHBOARD_CURSOS_3100
    WHERE CURSO_ID = @CursoId;

    IF @CursoPlantilla IS NULL
    BEGIN
        SELECT @CursoPlantilla = CASE @CursoId
            WHEN 'C01' THEN 'BLS'
            WHEN 'C02' THEN 'ACLS'
            WHEN 'C03' THEN 'GESTION DEL DUELO'
            WHEN 'C04' THEN 'ATENCION A LAS VICTIMAS DE ATAQUES QUIMICOS'
            WHEN 'C05' THEN 'ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL'
            WHEN 'C06' THEN 'HUMANIZACION'
            WHEN 'C07' THEN 'GESTION OPERATIVA DE LA DONACION'
            WHEN 'C08' THEN 'DENGUE'
            WHEN 'C09' THEN 'POCT'
            WHEN 'C10' THEN 'PALS'
            WHEN 'C11' THEN 'NALS'
            WHEN 'C12' THEN 'AIEPI'
            WHEN 'C13' THEN 'MANEJO DEL DOLOR Y CUIDADOS PALIATIVOS'
            WHEN 'C14' THEN 'INMUNOLOGIA DE TRANSPLANTES'
            WHEN 'C15' THEN 'GESTION PRE-TRANSFUCIONAL'
            WHEN 'C16' THEN 'ADMINISTRACION DE MEDICAMENTOS'
            WHEN 'C17' THEN 'TOMA DE MUESTRAS'
            WHEN 'C18' THEN 'CADENA DE FRIO'
            WHEN 'C19' THEN 'ATENCION DEL PACIENTE EN DIALISIS RENAL - DIALISIS'
            WHEN 'C20' THEN 'ASESORIA PRE TEST POST TEST HIV'
            WHEN 'C21' THEN 'OVEM - COVE'
            WHEN 'C22' THEN 'DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO'
            WHEN 'C23' THEN 'DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO'
            WHEN 'C24' THEN 'DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO'
            WHEN 'C25' THEN 'DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO'
            WHEN 'C26' THEN 'DIPLOMADO ONCO - HEMATOLOGIA PEDIATRICA'
            WHEN 'C27' THEN 'DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO'
            WHEN 'C28' THEN 'DIPLOMADO URGENCIAS'
            ELSE 'CURSO_DESCONOCIDO'
        END;
        IF @CursoId IN ('C22','C23','C24','C25','C26','C27','C28')
            SET @VigenciaMeses = 60;
    END;

    -- Si se envió FechaReal pero no FechaVenc, calcular vencimiento automáticamente
    IF @FechaVenc IS NULL AND @FechaReal IS NOT NULL
        SET @FechaVenc = DATEADD(month, @VigenciaMeses, @FechaReal);

    IF @FechaReal IS NULL AND @FechaVenc IS NULL
    BEGIN
        RAISERROR('Debe proporcionar al menos Fecha de Realización o Fecha de Vencimiento.', 16, 1);
        RETURN;
    END;

    -- 3. Registrar o actualizar en la tabla de auditoría BGD_CONTROL_CALIDAD_3100
    DECLARE @CalidadID INT;

    MERGE dbo.BGD_CONTROL_CALIDAD_3100 AS target
    USING (SELECT @Cedula AS CEDULA, @CursoId AS CURSO_ID) AS source
    ON (target.CEDULA = source.CEDULA AND target.CURSO_ID = source.CURSO_ID)
    WHEN MATCHED THEN
        UPDATE SET 
            FECHA_REAL = ISNULL(@FechaReal, target.FECHA_REAL),
            FECHA_VENC = ISNULL(@FechaVenc, target.FECHA_VENC),
            MOTIVO = @Motivo,
            USUARIO_MODIFICA = ISNULL(@Usuario, SYSTEM_USER),
            OBSERVACIONES = @Observaciones,
            _activo = 1,
            _fecha_creacion = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (CEDULA, CURSO_ID, CURSO_PLANTILLA, FECHA_REAL, FECHA_VENC, MOTIVO, USUARIO_MODIFICA, OBSERVACIONES, _activo, _fecha_creacion)
        VALUES (@Cedula, @CursoId, @CursoPlantilla, @FechaReal, @FechaVenc, @Motivo, ISNULL(@Usuario, SYSTEM_USER), @Observaciones, 1, SYSUTCDATETIME());

    SELECT @CalidadID = ID 
    FROM dbo.BGD_CONTROL_CALIDAD_3100 
    WHERE CEDULA = @Cedula AND CURSO_ID = @CursoId;

    -- 4. Actualizar en sitio la tabla BGD_DASHBOARD_CURSOS_3100 para la misma Fecha de Corte
    UPDATE d
    SET 
        d.SUBSANADO_CONTROL_CALIDAD = @CalidadID,
        d.VENC_EFECTIVO = @FechaVenc,
        d.REAL_EFECTIVA = @FechaReal,
        d.ESTADO_DETALLADO = CASE 
            WHEN @FechaVenc < d.FECHA_CORTE THEN 'VENCIDO'
            WHEN @FechaVenc < DATEADD(day, 90, d.FECHA_CORTE) THEN 'POR VENCER'
            ELSE 'VIGENTE'
        END,
        d.MARCA = CASE 
            WHEN @FechaVenc >= d.FECHA_CORTE THEN 'SI'
            ELSE 'NO'
        END,
        d.CUENTA_INDICADOR = CASE 
            WHEN @FechaVenc >= d.FECHA_CORTE THEN 1
            ELSE 0
        END,
        d.DIAS_PARA_VENCER = DATEDIFF(day, d.FECHA_CORTE, @FechaVenc),
        d.ALERTA = 'SUBSANADO_CONTROL_CALIDAD',
        d.OBSERVACION = CONCAT('Subsanado en Control de Calidad: ', @Motivo),
        d._fecha_calculo = SYSUTCDATETIME()
    FROM dbo.BGD_DASHBOARD_CURSOS_3100 d
    WHERE d.CEDULA = @Cedula 
      AND d.CURSO_ID = @CursoId
      AND d.FECHA_CORTE = @FechaCorte;

    -- 5. Actualizar en sitio únicamente el registro EXISTENTE en BGD_RESUMEN_MES_3100 para esa misma Fecha de Corte
    WITH MetricasCalculadas AS (
        SELECT 
            d.CEDULA,
            d.FECHA_CORTE,
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
            ISNULL(
                STRING_AGG(
                    CASE 
                        WHEN d.ESTADO_DETALLADO IN ('VENCIDO', 'NO REALIZADO', 'SIN REGISTRO', 'SIN COLUMNA EN SEDE') AND d.OBLIGATORIO = 'SI' 
                        THEN d.CURSO_PLANTILLA 
                    END, 
                    '; '
                ) WITHIN GROUP (ORDER BY d.CURSO_ID),
                ''
            ) AS CURSOS_PENDIENTES
        FROM dbo.BGD_DASHBOARD_CURSOS_3100 d
        WHERE d.CEDULA = @Cedula
          AND d.FECHA_CORTE = @FechaCorte
        GROUP BY d.CEDULA, d.FECHA_CORTE
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
        r._fecha_calculo = SYSUTCDATETIME()
    FROM dbo.BGD_RESUMEN_MES_3100 r
    JOIN MetricasCalculadas m 
      ON r.CEDULA = m.CEDULA 
     AND r.FECHA_CORTE = m.FECHA_CORTE;

    -- Retornar resultado confirmando la fecha de corte actualizada
    SELECT 
        @CalidadID AS ID_CONTROL_CALIDAD,
        @Cedula AS CEDULA,
        @CursoId AS CURSO_ID,
        @CursoPlantilla AS CURSO_PLANTILLA,
        @FechaCorte AS FECHA_CORTE,
        @FechaReal AS FECHA_REAL,
        @FechaVenc AS FECHA_VENC,
        'Registro subsanado y resumen actualizado exitosamente en el mismo corte.' AS MENSAJE;
END;
GO
