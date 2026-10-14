USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2
-- Base de Datos: DGEMPRES99 (o base configurada)
-- Descripción  : Procedimiento v2 para evaluar y poblar la tabla granular dbo.BGD_MTZ3100_DASH.
--                1. Cruza los cursos registrados en dbo.BGD_MTZ_CURSOS_RAW con:
--                   - dbo.BGD_MTZ_COL (datos del colaborador y sede)
--                   - dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD (matriz normativa por cargo y servicio)
--                   - dbo.BGD_MTZ3100_CATCURSO (vigencias y metadatos de cursos)
--                   - dbo.BGD_MTZ3100_AUDITORIA (ajustes de calidad activos)
--                2. Clasifica cada registro en una de las 10 situaciones normativas.
--                3. Persiste en dbo.BGD_MTZ3100_DASH con su ID identity autoincremental.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2
    @FechaCorte DATE = NULL,
    @VentanaDias INT = 90,
    @MesAnalisis VARCHAR(10) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Determinar fecha de corte y mes de análisis
    IF @FechaCorte IS NULL
        SET @FechaCorte = EOMONTH(DATEADD(month, -1, GETDATE()));

    IF @MesAnalisis IS NULL
        SET @MesAnalisis = FORMAT(@FechaCorte, 'yyyy-MM');

    PRINT '=======================================================';
    PRINT 'Iniciando dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2';
    PRINT 'Fecha de Corte : ' + CONVERT(VARCHAR(10), @FechaCorte, 120);
    PRINT 'Mes de Análisis: ' + @MesAnalisis;
    PRINT 'Ventana Días   : ' + CAST(@VentanaDias AS VARCHAR(5));
    PRINT '=======================================================';

    -- 2. Limpieza de registros previos para idempotencia
    DELETE FROM dbo.BGD_MTZ3100_DASH
    WHERE MES_ANALISIS = @MesAnalisis;

    -- 3. Identificación de colaboradores multisede en el mes
    ;WITH MultisedeCheck AS (
        SELECT CEDULA
        FROM dbo.BGD_MTZ_COL
        GROUP BY CEDULA
        HAVING COUNT(DISTINCT SEDE) > 1
    ),

    -- 4. Extracción base cruzada entre Cursos Raw y Colaboradores
    BaseRaw AS (
        SELECT 
            r.MES_ANALISIS,
            r.SEDE,
            r.CEDULA,
            c.NOMBRE_COLABORADOR,
            c.CODIGO,
            c.ESTADO,
            c.CARGO,
            c.COD_SERVICIO,
            c.[JEFE INMEDIATO] AS JEFE_INMEDIATO,
            CASE WHEN m.CEDULA IS NOT NULL THEN 'SI' ELSE 'NO' END AS MULTISEDE,
            r.CURSO_ID,
            r.CURSO_NOMBRE,
            r.MARCA_ORIGEN,
            r.FECHA_REAL_ORIGEN,
            r.FECHA_VENC_ORIGEN,
            ISNULL(r.LECTURA, 'OK') AS LECTURA,
            cat.VIGENCIA_MESES
        FROM dbo.BGD_MTZ_CURSOS_RAW r
        INNER JOIN dbo.BGD_MTZ_COL c
            ON c.CEDULA COLLATE DATABASE_DEFAULT = r.CEDULA COLLATE DATABASE_DEFAULT
           AND c.SEDE COLLATE DATABASE_DEFAULT = r.SEDE COLLATE DATABASE_DEFAULT
        INNER JOIN dbo.BGD_MTZ3100_CATCURSO cat
            ON cat.CURSO_NOMBRE COLLATE DATABASE_DEFAULT = r.CURSO_NOMBRE COLLATE DATABASE_DEFAULT
        LEFT JOIN MultisedeCheck m
            ON m.CEDULA COLLATE DATABASE_DEFAULT = r.CEDULA COLLATE DATABASE_DEFAULT
        WHERE r.MES_ANALISIS = @MesAnalisis
    ),

    -- 5. Evaluación de fechas efectivas y control de auditoría
    EvaluacionBase AS (
        SELECT 
            b.*,
            aud.ID AS ID_AUDITORIA,
            aud.MOTIVO AS MOTIVO_AUDITORIA,
            dt.VENC_EFECTIVO,
            dt.REAL_EFECTIVA,
            obl.ES_OBLIGATORIO
        FROM BaseRaw b
        LEFT JOIN dbo.BGD_MTZ3100_AUDITORIA aud
            ON aud.CEDULA_COLABORADOR COLLATE DATABASE_DEFAULT = b.CEDULA COLLATE DATABASE_DEFAULT
           AND aud.CURSO_ID COLLATE DATABASE_DEFAULT = b.CURSO_ID COLLATE DATABASE_DEFAULT
           AND aud._activo = 1
        CROSS APPLY (
            SELECT 
                CASE 
                    WHEN b.CARGO COLLATE Modern_Spanish_CI_AI = 'ENFERMERO (A) JEFE SERVICIO SOCIAL OBLIGATORIO' 
                        THEN 'ENFERMERO (A) JEFE'
                    WHEN b.CARGO COLLATE Modern_Spanish_CI_AI IN ('MEDICO SERVICIO SOCIAL OBLIGATORIO', 'MEDICO SERVICIO OBLIGATORIO') 
                        THEN 'MEDICO GENERAL'
                    ELSE b.CARGO
                END AS CARGO_NORMATIVO
        ) h
        CROSS APPLY (
            SELECT 
                CASE 
                    -- Si el cargo figura en la matriz de obligatoriedad
                    WHEN EXISTS (
                        SELECT 1 
                        FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD ind
                        WHERE ind.ESTADO = 'ACTIVO'
                          AND ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                    ) THEN
                        CASE 
                            WHEN EXISTS (
                                SELECT 1 
                                FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD ind
                                WHERE ind.ESTADO = 'ACTIVO'
                                  AND ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                                  AND ind.COD_CURSO COLLATE Modern_Spanish_CI_AI = b.CURSO_NOMBRE COLLATE Modern_Spanish_CI_AI
                                  AND (
                                      ind.CODIGOS_SERVICIO = 'TODOS'
                                      OR (
                                          b.COD_SERVICIO IS NOT NULL AND b.COD_SERVICIO <> ''
                                          AND (
                                              ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + b.COD_SERVICIO + ';%'
                                              OR (TRY_CAST(b.COD_SERVICIO AS INT) IS NOT NULL 
                                                  AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + RIGHT('0000' + CAST(TRY_CAST(b.COD_SERVICIO AS INT) AS VARCHAR(10)), 4) + ';%')
                                              OR (TRY_CAST(b.COD_SERVICIO AS INT) IS NOT NULL 
                                                  AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + CAST(TRY_CAST(b.COD_SERVICIO AS INT) AS VARCHAR(10)) + ';%')
                                          )
                                      )
                                  )
                            ) THEN 1
                            ELSE 0
                        END
                    -- Si el cargo NO figura en el índice (cargos no asistenciales): marcas SI/NO son obligatorias
                    ELSE
                        CASE 
                            WHEN b.MARCA_ORIGEN IN ('SI', 'NO') THEN 1
                            ELSE 0
                        END
                END AS ES_OBLIGATORIO
        ) obl
        CROSS APPLY (
            SELECT 
                COALESCE(aud.FECHA_VENC_NEW, b.FECHA_VENC_ORIGEN, 
                         CASE WHEN COALESCE(aud.FECHA_REAL_NEW, b.FECHA_REAL_ORIGEN) IS NOT NULL 
                              THEN DATEADD(month, b.VIGENCIA_MESES, COALESCE(aud.FECHA_REAL_NEW, b.FECHA_REAL_ORIGEN)) 
                              ELSE NULL END
                ) AS VENC_EFECTIVO,
                COALESCE(aud.FECHA_REAL_NEW, b.FECHA_REAL_ORIGEN) AS REAL_EFECTIVA
        ) dt
    ),

    -- 6. Clasificación de las 10 situaciones normativas
    EvaluacionSituaciones AS (
        SELECT 
            eb.*,
            CASE 
                -- Sit 1: No obligatorio según índice
                WHEN eb.ES_OBLIGATORIO = 0 THEN 1

                -- Si está subsanado por Control de Calidad / Auditoría
                WHEN eb.ID_AUDITORIA IS NOT NULL THEN
                    CASE 
                        WHEN eb.VENC_EFECTIVO < @FechaCorte THEN 5
                        WHEN eb.VENC_EFECTIVO < DATEADD(day, @VentanaDias, @FechaCorte) THEN 3
                        ELSE 2
                    END

                -- Sit 9: Obligatorio según índice pero sin columna en sede
                WHEN eb.LECTURA = 'SIN_COLUMNA' THEN 9

                -- Sin fechas registradas
                WHEN eb.VENC_EFECTIVO IS NULL AND eb.REAL_EFECTIVA IS NULL THEN 
                    CASE 
                        WHEN eb.MARCA_ORIGEN IN ('SI', 'S') THEN 6
                        WHEN eb.MARCA_ORIGEN IN ('N/A', 'NA') THEN 8
                        ELSE 7
                    END

                -- Con fecha de vencimiento anterior al corte
                WHEN eb.VENC_EFECTIVO < @FechaCorte THEN 
                    CASE 
                        WHEN eb.MARCA_ORIGEN IN ('SI', 'S') THEN 4
                        ELSE 5
                    END

                -- Con fecha de vencimiento posterior o igual al corte
                ELSE 
                    CASE 
                        WHEN eb.MARCA_ORIGEN IN ('NO', 'N') THEN 10
                        WHEN eb.VENC_EFECTIVO < DATEADD(day, @VentanaDias, @FechaCorte) THEN 3
                        ELSE 2
                    END
            END AS SITUACION_NUM
        FROM EvaluacionBase eb
    )

    -- 7. Inserción en dbo.BGD_MTZ3100_DASH (solo cursos obligatorios)
    INSERT INTO dbo.BGD_MTZ3100_DASH (
        MES_ANALISIS,
        CEDULA,
        NOMBRE_COLABORADOR,
        SEDE,
        MULTISEDE,
        CURSO_ID,
        CURSO_NOMBRE,
        MARCA_ORIGEN,
        FECHA_REAL_ORIGEN,
        FECHA_VENC_ORIGEN,
        LECTURA,
        OBLIGATORIO,
        VIGENCIA_MESES,
        VENC_EFECTIVO,
        REAL_EFECTIVA,
        ESTADO_DETALLADO,
        MARCA,
        DIAS_PARA_VENCER,
        CUENTA_INDICADOR,
        ALERTA,
        OBSERVACION,
        SUBSANADO_CONTROL_CALIDAD,
        FECHA_CALCULO
    )
    SELECT 
        MES_ANALISIS,
        CEDULA,
        NOMBRE_COLABORADOR,
        SEDE,
        MULTISEDE,
        CURSO_ID,
        CURSO_NOMBRE,
        MARCA_ORIGEN,
        FECHA_REAL_ORIGEN,
        FECHA_VENC_ORIGEN,
        LECTURA,
        'SI' AS OBLIGATORIO,
        VIGENCIA_MESES,
        VENC_EFECTIVO,
        REAL_EFECTIVA,

        -- ESTADO_DETALLADO
        CASE 
            WHEN SITUACION_NUM IN (2, 10) THEN 'VIGENTE'
            WHEN SITUACION_NUM = 3 THEN 'POR VENCER'
            WHEN SITUACION_NUM IN (4, 5) THEN 'VENCIDO'
            WHEN SITUACION_NUM = 6 THEN 'CUMPLE SIN FECHA'
            WHEN SITUACION_NUM IN (7, 8) THEN 'NO REALIZADO'
            WHEN SITUACION_NUM = 9 THEN 'SIN COLUMNA EN SEDE'
            ELSE 'NO APLICA'
        END AS ESTADO_DETALLADO,

        -- MARCA
        CASE 
            WHEN SITUACION_NUM IN (2, 3, 6, 10) THEN 'SI'
            ELSE 'NO'
        END AS MARCA,

        -- DÍAS PARA VENCER
        CASE 
            WHEN VENC_EFECTIVO IS NOT NULL THEN DATEDIFF(day, @FechaCorte, VENC_EFECTIVO)
            ELSE NULL
        END AS DIAS_PARA_VENCER,

        -- CUENTA EN INDICADOR
        CASE 
            WHEN SITUACION_NUM IN (2, 3, 6, 10) THEN 1
            ELSE 0
        END AS CUENTA_INDICADOR,

        -- ALERTA
        CASE 
            WHEN ID_AUDITORIA IS NOT NULL THEN 'SUBSANADO_AUDITORIA'
            WHEN SITUACION_NUM = 3 THEN 'ALERTA_POR_VENCER'
            WHEN SITUACION_NUM = 4 THEN 'MARCA_DESACTUALIZADA'
            WHEN SITUACION_NUM = 6 THEN 'FALTA_FECHA'
            WHEN SITUACION_NUM = 8 THEN 'DISCREPANCIA_APLICABILIDAD'
            WHEN SITUACION_NUM = 9 THEN 'SIN_COLUMNA'
            WHEN SITUACION_NUM = 10 THEN 'MARCA_DESACTUALIZADA'
            ELSE NULL
        END AS ALERTA,

        -- OBSERVACIÓN
        CASE 
            WHEN ID_AUDITORIA IS NOT NULL THEN CONCAT('Subsanado en Auditoría: ', MOTIVO_AUDITORIA)
            WHEN SITUACION_NUM = 3 THEN 'Suma al indicador pero se lista para gestión preventiva'
            WHEN SITUACION_NUM = 4 THEN 'La sede tenía SI pero el curso ya venció'
            WHEN SITUACION_NUM = 6 THEN 'Suma al indicador pero requiere solicitud de soporte a la sede'
            WHEN SITUACION_NUM = 8 THEN 'La sede indicó N/A pero la norma lo exige'
            WHEN SITUACION_NUM = 9 THEN 'La sede no registra este curso; no puede evaluarse cumplimiento'
            WHEN SITUACION_NUM = 10 THEN 'La sede marcó NO pero la fecha registrada indica vigencia'
            ELSE NULL
        END AS OBSERVACION,

        ID_AUDITORIA AS SUBSANADO_CONTROL_CALIDAD,
        SYSUTCDATETIME() AS FECHA_CALCULO
    FROM EvaluacionSituaciones
    WHERE SITUACION_NUM <> 1; -- Solo obligatorios

    DECLARE @FilasInsertadas INT = @@ROWCOUNT;
    PRINT 'dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2 finalizado. Total registros insertados: ' + CAST(@FilasInsertadas AS VARCHAR(10));
END;
GO
