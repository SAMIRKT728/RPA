USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2
-- Base de Datos: DGEMPRES99 (o base configurada)
-- Descripción  : Motor de cálculo normativo para la tabla central dbo.BGD_MTZ3100_DASH.
--                1. Opera directamente sobre dbo.BGD_MTZ3100_DASH (sin tabla intermedia RAW).
--                2. Cruza con:
--                   - dbo.BGD_MTZ_COL (datos de cargo, servicio y sede del colaborador)
--                   - dbo.BGD_MTZ3100_CATCURSO (por ID_CURSO inmutable C01..C28, evitando descalces por tildes)
--                   - dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD (por cargo y curso con CI_AI insensible a tildes)
--                   - dbo.BGD_MTZ3100_AUDITORIA (ajustes de calidad activos)
--                3. Clasifica cada curso en su situación normativa (Vigente, Por Vencer, Vencido, etc.).
--                4. Conserva EXCLUSIVAMENTE los cursos obligatorios en dbo.BGD_MTZ3100_DASH.
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
    PRINT 'Iniciando dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2 (Recálculo directo en DASH)';
    PRINT 'Fecha de Corte : ' + CONVERT(VARCHAR(10), @FechaCorte, 120);
    PRINT 'Mes de Análisis: ' + @MesAnalisis;
    PRINT 'Ventana Días   : ' + CAST(@VentanaDias AS VARCHAR(5));
    PRINT '=======================================================';

    -- 2. Identificación y actualización de colaboradores multisede
    ;WITH MultisedeCheck AS (
        SELECT CEDULA
        FROM dbo.BGD_MTZ_COL
        GROUP BY CEDULA
        HAVING COUNT(DISTINCT SEDE) > 1
    )
    UPDATE d
    SET d.MULTISEDE = CASE WHEN m.CEDULA IS NOT NULL THEN 'SI' ELSE 'NO' END
    FROM dbo.BGD_MTZ3100_DASH d
    LEFT JOIN MultisedeCheck m
        ON m.CEDULA COLLATE DATABASE_DEFAULT = d.CEDULA COLLATE DATABASE_DEFAULT
    WHERE d.MES_ANALISIS = @MesAnalisis;

    -- 3. Evaluación normativa de cursos en dbo.BGD_MTZ3100_DASH
    ;WITH EvaluacionBase AS (
        SELECT 
            d.ID,
            d.MES_ANALISIS,
            d.SEDE,
            d.CEDULA,
            c.NOMBRE_COLABORADOR,
            c.CODIGO,
            c.ESTADO,
            c.CARGO,
            c.COD_SERVICIO,
            c.[JEFE INMEDIATO] AS JEFE_INMEDIATO,
            d.CURSO_ID,
            cat.CURSO_NOMBRE AS CAT_CURSO_NOMBRE,
            d.MARCA_ORIGEN,
            d.FECHA_REAL_ORIGEN,
            d.FECHA_VENC_ORIGEN,
            ISNULL(d.LECTURA, 'OK') AS LECTURA,
            cat.VIGENCIA_MESES,
            aud.ID AS ID_AUDITORIA,
            aud.MOTIVO AS MOTIVO_AUDITORIA,
            dt.VENC_EFECTIVO,
            dt.REAL_EFECTIVA,
            obl.ES_OBLIGATORIO
        FROM dbo.BGD_MTZ3100_DASH d
        INNER JOIN dbo.BGD_MTZ_COL c
            ON c.CEDULA COLLATE DATABASE_DEFAULT = d.CEDULA COLLATE DATABASE_DEFAULT
           AND c.SEDE COLLATE DATABASE_DEFAULT = d.SEDE COLLATE DATABASE_DEFAULT
        INNER JOIN dbo.BGD_MTZ3100_CATCURSO cat
            ON cat.ID_CURSO COLLATE DATABASE_DEFAULT = d.CURSO_ID COLLATE DATABASE_DEFAULT
        LEFT JOIN dbo.BGD_MTZ3100_AUDITORIA aud
            ON aud.CEDULA_COLABORADOR COLLATE DATABASE_DEFAULT = d.CEDULA COLLATE DATABASE_DEFAULT
           AND aud.CURSO_ID COLLATE DATABASE_DEFAULT = d.CURSO_ID COLLATE DATABASE_DEFAULT
           AND aud._activo = 1
        CROSS APPLY (
            SELECT 
                CASE 
                    WHEN c.CARGO COLLATE Modern_Spanish_CI_AI IN (
                        'ENFERMERO (A) JEFE', 'ENFERMERO JEFE', 'ENFERMERA JEFE', 
                        'ENFERMERO (A) JEFE AC', 'ENFERMERO (A) JEFE SERVICIO SOCIAL OBLIGATORIO',
                        'COORDINADOR (A) DE ENFERMERIA'
                    ) THEN 'ENFERMERO (A) JEFE AC'
                    WHEN c.CARGO COLLATE Modern_Spanish_CI_AI IN (
                        'MEDICO GENERAL', 'MEDICO GENERAL AC',
                        'MEDICO SERVICIO SOCIAL OBLIGATORIO', 'MEDICO SERVICIO OBLIGATORIO',
                        'COORDINADOR (A) MEDICO'
                    ) THEN 'MEDICO GENERAL AC'
                    ELSE c.CARGO
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
                          AND (
                              ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                              OR ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO + ' AC' COLLATE Modern_Spanish_CI_AI
                          )
                    ) THEN
                        CASE 
                            WHEN EXISTS (
                                SELECT 1 
                                FROM dbo.BGD_MTZ_INDICE_OBLIGATORIEDAD ind
                                WHERE ind.ESTADO = 'ACTIVO'
                                  AND (
                                      ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO COLLATE Modern_Spanish_CI_AI
                                      OR ind.CARGO COLLATE Modern_Spanish_CI_AI = h.CARGO_NORMATIVO + ' AC' COLLATE Modern_Spanish_CI_AI
                                  )
                                  AND (
                                      ind.COD_CURSO COLLATE Modern_Spanish_CI_AI = cat.CURSO_NOMBRE COLLATE Modern_Spanish_CI_AI
                                      OR ind.COD_CURSO COLLATE Modern_Spanish_CI_AI = d.CURSO_NOMBRE COLLATE Modern_Spanish_CI_AI
                                  )
                                  AND (
                                      ind.CODIGOS_SERVICIO = 'TODOS'
                                      OR (
                                          c.COD_SERVICIO IS NOT NULL AND c.COD_SERVICIO <> ''
                                          AND (
                                              ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + c.COD_SERVICIO + ';%'
                                              OR (TRY_CAST(c.COD_SERVICIO AS INT) IS NOT NULL 
                                                  AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + RIGHT('0000' + CAST(TRY_CAST(c.COD_SERVICIO AS INT) AS VARCHAR(10)), 4) + ';%')
                                              OR (TRY_CAST(c.COD_SERVICIO AS INT) IS NOT NULL 
                                                  AND ';' + ind.CODIGOS_SERVICIO + ';' LIKE '%;' + CAST(TRY_CAST(c.COD_SERVICIO AS INT) AS VARCHAR(10)) + ';%')
                                          )
                                      )
                                  )
                            ) THEN 1
                            ELSE 0
                        END
                    -- Si el cargo NO figura en el índice (cargos administrativos/otros): marcas SI/NO son obligatorias
                    ELSE
                        CASE 
                            WHEN d.MARCA_ORIGEN IN ('SI', 'NO') THEN 1
                            ELSE 0
                        END
                END AS ES_OBLIGATORIO
        ) obl
        CROSS APPLY (
            SELECT 
                COALESCE(aud.FECHA_VENC_NEW, d.FECHA_VENC_ORIGEN, 
                         CASE WHEN COALESCE(aud.FECHA_REAL_NEW, d.FECHA_REAL_ORIGEN) IS NOT NULL 
                              THEN DATEADD(month, cat.VIGENCIA_MESES, COALESCE(aud.FECHA_REAL_NEW, d.FECHA_REAL_ORIGEN)) 
                              ELSE NULL END
                ) AS VENC_EFECTIVO,
                COALESCE(aud.FECHA_REAL_NEW, d.FECHA_REAL_ORIGEN) AS REAL_EFECTIVA
        ) dt
        WHERE d.MES_ANALISIS = @MesAnalisis
    ),

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

    -- 4. Actualizar campos calculados en dbo.BGD_MTZ3100_DASH
    UPDATE d
    SET 
        d.NOMBRE_COLABORADOR = ev.NOMBRE_COLABORADOR,
        d.CURSO_NOMBRE = ev.CAT_CURSO_NOMBRE,
        d.OBLIGATORIO = CASE WHEN ev.ES_OBLIGATORIO = 1 THEN 'SI' ELSE 'NO' END,
        d.VIGENCIA_MESES = ev.VIGENCIA_MESES,
        d.VENC_EFECTIVO = ev.VENC_EFECTIVO,
        d.REAL_EFECTIVA = ev.REAL_EFECTIVA,
        d.ESTADO_DETALLADO = CASE 
            WHEN ev.SITUACION_NUM IN (2, 10) THEN 'VIGENTE'
            WHEN ev.SITUACION_NUM = 3 THEN 'POR VENCER'
            WHEN ev.SITUACION_NUM IN (4, 5) THEN 'VENCIDO'
            WHEN ev.SITUACION_NUM = 6 THEN 'CUMPLE SIN FECHA'
            WHEN ev.SITUACION_NUM IN (7, 8) THEN 'NO REALIZADO'
            WHEN ev.SITUACION_NUM = 9 THEN 'SIN COLUMNA EN SEDE'
            ELSE 'NO APLICA'
        END,
        d.MARCA = CASE 
            WHEN ev.SITUACION_NUM IN (2, 3, 6, 10) THEN 'SI'
            ELSE 'NO'
        END,
        d.DIAS_PARA_VENCER = CASE 
            WHEN ev.VENC_EFECTIVO IS NOT NULL THEN DATEDIFF(day, @FechaCorte, ev.VENC_EFECTIVO)
            ELSE NULL
        END,
        d.CUENTA_INDICADOR = CASE 
            WHEN ev.SITUACION_NUM IN (2, 3, 6, 10) THEN 1
            ELSE 0
        END,
        d.ALERTA = CASE 
            WHEN ev.ID_AUDITORIA IS NOT NULL THEN 'SUBSANADO_AUDITORIA'
            WHEN ev.SITUACION_NUM = 3 THEN 'ALERTA_POR_VENCER'
            WHEN ev.SITUACION_NUM = 4 THEN 'MARCA_DESACTUALIZADA'
            WHEN ev.SITUACION_NUM = 6 THEN 'FALTA_FECHA'
            WHEN ev.SITUACION_NUM = 8 THEN 'DISCREPANCIA_APLICABILIDAD'
            WHEN ev.SITUACION_NUM = 9 THEN 'SIN_COLUMNA'
            WHEN ev.SITUACION_NUM = 10 THEN 'MARCA_DESACTUALIZADA'
            ELSE NULL
        END,
        d.OBSERVACION = CASE 
            WHEN ev.ID_AUDITORIA IS NOT NULL THEN CONCAT('Subsanado en Auditoría: ', ev.MOTIVO_AUDITORIA)
            WHEN ev.SITUACION_NUM = 3 THEN 'Suma al indicador pero se lista para gestión preventiva'
            WHEN ev.SITUACION_NUM = 4 THEN 'La sede tenía SI pero el curso ya venció'
            WHEN ev.SITUACION_NUM = 6 THEN 'Suma al indicador pero requiere solicitud de soporte a la sede'
            WHEN ev.SITUACION_NUM = 8 THEN 'La sede indicó N/A pero la norma lo exige'
            WHEN ev.SITUACION_NUM = 9 THEN 'La sede no registra este curso; no puede evaluarse cumplimiento'
            WHEN ev.SITUACION_NUM = 10 THEN 'La sede marcó NO pero la fecha registrada indica vigencia'
            ELSE NULL
        END,
        d.SUBSANADO_CONTROL_CALIDAD = ev.ID_AUDITORIA,
        d.FECHA_CALCULO = SYSUTCDATETIME()
    FROM dbo.BGD_MTZ3100_DASH d
    INNER JOIN EvaluacionSituaciones ev
        ON ev.ID = d.ID;

    -- 5. Eliminar cursos NO obligatorios (conservar únicamente los obligatorios como se definió)
    DELETE FROM dbo.BGD_MTZ3100_DASH
    WHERE MES_ANALISIS = @MesAnalisis
      AND (OBLIGATORIO = 'NO' OR ESTADO_DETALLADO = 'NO APLICA');

    DECLARE @FilasActualizadas INT = @@ROWCOUNT;
    PRINT 'dbo.SP_POBLAR_BGD_MTZ3100_DASH_V2 finalizado exitosamente.';
END;
GO
