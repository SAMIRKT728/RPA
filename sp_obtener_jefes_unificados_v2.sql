USE [DGEMPRES99]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.sp_ObtenerJefesUnificados_v2
-- Base de Datos: DGEMPRES99 (o base configurada)
-- Descripción  : Unifica y estandariza los nombres de jefes inmediatos provenientes de
--                la tabla normalizada dbo.BGD_MTZ_COL (o fuentes de sedes).
--                1. Resuelve similitudes léxicas para crear el catálogo canonical.
--                2. Alimenta la nueva tabla dbo.BDG_MTZ_JEFE:
--                   - CEDULA: NULL
--                   - NOMBRE DEL JEFE: NombreUnificado
--                   - SEDE: Sede donde labora/supervisa
--                   - FECHA CARGA: SYSUTCDATETIME()
--                3. Persiste el catálogo unificado en dbo.BGD_JEFES_UNIFICADOS_MX100.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE [dbo].[sp_ObtenerJefesUnificados_v2]
AS
BEGIN
    SET NOCOUNT ON;

    PRINT '=======================================================';
    PRINT 'Iniciando dbo.sp_ObtenerJefesUnificados_v2';
    PRINT '=======================================================';

    -- 1. Garantizar existencia física de la tabla de catálogo BGD_JEFES_UNIFICADOS_MX100
    IF OBJECT_ID('dbo.BGD_JEFES_UNIFICADOS_MX100', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.BGD_JEFES_UNIFICADOS_MX100 (
            NombreUnificado NVARCHAR(250) NOT NULL PRIMARY KEY,
            Variantes NVARCHAR(MAX) NOT NULL,
            CantidadVariantes INT NOT NULL,
            _fecha_calculo DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
        );

        CREATE NONCLUSTERED INDEX IX_BGD_JEFES_UNIFICADOS_CANTIDAD
        ON dbo.BGD_JEFES_UNIFICADOS_MX100 (CantidadVariantes DESC);
    END;

    -- 2. Garantizar existencia física de la tabla BDG_MTZ_JEFE
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

    -- 3. Limpieza previa de tablas de destino
    TRUNCATE TABLE dbo.BGD_JEFES_UNIFICADOS_MX100;
    TRUNCATE TABLE dbo.BDG_MTZ_JEFE;

    -- 4. Extracción de Nombres Originales de Jefes por Sede desde BGD_MTZ_COL
    -- (si BGD_MTZ_COL está vacía, no generará error)
    IF NOT EXISTS (SELECT 1 FROM dbo.BGD_MTZ_COL WHERE [JEFE INMEDIATO] IS NOT NULL AND LTRIM(RTRIM([JEFE INMEDIATO])) <> '')
    BEGIN
        PRINT 'Aviso: dbo.BGD_MTZ_COL no contiene registros de colaboradores aún. Finalizando sin inserción.';
        RETURN;
    END;

    DROP TABLE IF EXISTS #SedeJefes;
    DROP TABLE IF EXISTS #ResultadoUnificacion;

    SELECT DISTINCT 
        LTRIM(RTRIM(CAST([JEFE INMEDIATO] AS VARCHAR(500)))) COLLATE DATABASE_DEFAULT AS NombreOriginal,
        LTRIM(RTRIM(CAST(SEDE AS VARCHAR(50)))) COLLATE DATABASE_DEFAULT AS Sede
    INTO #SedeJefes
    FROM dbo.BGD_MTZ_COL
    WHERE [JEFE INMEDIATO] IS NOT NULL 
      AND LTRIM(RTRIM([JEFE INMEDIATO])) <> ''
      AND UPPER(LTRIM(RTRIM([JEFE INMEDIATO]))) NOT IN (
          'NO APLICA', 'N/A', 'SIN DATO', 'SIN ASIGNAR', 'PENDIENTE', '0', '-'
      );

    ;WITH NombresUnicos AS
    (
        SELECT DISTINCT NombreOriginal
        FROM #SedeJefes
    ),

    Normalizados AS
    (
        SELECT
            NombreOriginal,
            UPPER(
                LTRIM(RTRIM(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(NombreOriginal, '  ', ' '),
                                    '.', ''
                                ),
                                ',', ''
                            ),
                            '-', ' '
                        ),
                        '  ', ' '
                    )
                ))
            ) AS NombreNormalizado
        FROM NombresUnicos
    ),

    ConteoPalabras AS
    (
        SELECT
            N.NombreOriginal,
            N.NombreNormalizado,
            COUNT(DISTINCT S.value) AS TotalPalabras
        FROM Normalizados N
        CROSS APPLY STRING_SPLIT(
            CAST(N.NombreNormalizado AS VARCHAR(500)),
            ' '
        ) S
        WHERE LTRIM(RTRIM(S.value)) <> ''
        GROUP BY
            N.NombreOriginal,
            N.NombreNormalizado
    ),

    Comparaciones AS
    (
        SELECT
            A.NombreOriginal AS NombreA,
            B.NombreOriginal AS NombreB,

            A.TotalPalabras AS PalabrasA,
            B.TotalPalabras AS PalabrasB,

            COUNT(DISTINCT T1.value) AS PalabrasCoincidentes,

            CAST(
                COUNT(DISTINCT T1.value) * 100.0 /
                CASE
                    WHEN A.TotalPalabras > B.TotalPalabras
                        THEN A.TotalPalabras
                    ELSE B.TotalPalabras
                END
                AS DECIMAL(5,2)
            ) AS PorcentajeCoincidencia

        FROM ConteoPalabras A
        INNER JOIN ConteoPalabras B
            ON 1=1
        CROSS APPLY STRING_SPLIT(
            CAST(A.NombreNormalizado AS VARCHAR(500)),
            ' '
        ) T1
        CROSS APPLY STRING_SPLIT(
            CAST(B.NombreNormalizado AS VARCHAR(500)),
            ' '
        ) T2
        WHERE LTRIM(RTRIM(T1.value)) <> ''
          AND LTRIM(RTRIM(T2.value)) <> ''
          AND LTRIM(RTRIM(T1.value)) = LTRIM(RTRIM(T2.value))
        GROUP BY
            A.NombreOriginal,
            B.NombreOriginal,
            A.TotalPalabras,
            B.TotalPalabras
    ),

    CoincidenciasValidas AS
    (
        SELECT *
        FROM Comparaciones
        WHERE 
            (PalabrasA = PalabrasB AND PorcentajeCoincidencia = 100)
            OR 
            (PalabrasA <> PalabrasB AND PorcentajeCoincidencia >= 75)
    ),

    Resultado AS
    (
        SELECT
            NombreA AS NombreOriginal,
            NombreB AS NombreUnificado,
            PorcentajeCoincidencia,

            ROW_NUMBER() OVER
            (
                PARTITION BY NombreA
                ORDER BY
                    PalabrasB DESC,
                    LEN(NombreB) DESC,
                    NombreB ASC 
            ) AS RN
        FROM CoincidenciasValidas
    )
    SELECT NombreOriginal, NombreUnificado, PorcentajeCoincidencia
    INTO #ResultadoUnificacion
    FROM Resultado
    WHERE RN = 1;

    -- 5. Persistir en la tabla de catálogo BGD_JEFES_UNIFICADOS_MX100
    INSERT INTO dbo.BGD_JEFES_UNIFICADOS_MX100 (
        NombreUnificado,
        Variantes,
        CantidadVariantes,
        _fecha_calculo
    )
    SELECT
        NombreUnificado,
        STRING_AGG(CAST(NombreOriginal AS VARCHAR(MAX)), ' | ') AS Variantes,
        COUNT(NombreOriginal) AS CantidadVariantes,
        SYSUTCDATETIME()
    FROM #ResultadoUnificacion
    GROUP BY NombreUnificado;

    -- 6. Poblar la nueva tabla dbo.BDG_MTZ_JEFE
    -- Rellenando los demás campos excepto la CÉDULA (que permanece en NULL)
    INSERT INTO dbo.BDG_MTZ_JEFE (
        CEDULA,
        [NOMBRE DEL JEFE],
        SEDE,
        [FECHA CARGA]
    )
    SELECT DISTINCT
        CAST(NULL AS NVARCHAR(12)) AS CEDULA,
        r.NombreUnificado AS [NOMBRE DEL JEFE],
        s.Sede AS SEDE,
        SYSUTCDATETIME() AS [FECHA CARGA]
    FROM #SedeJefes s
    JOIN #ResultadoUnificacion r ON s.NombreOriginal = r.NombreOriginal
    ORDER BY s.Sede, r.NombreUnificado;

    DECLARE @TotalJefes INT = @@ROWCOUNT;
    PRINT 'Proceso completado. Registros insertados en BDG_MTZ_JEFE: ' + CAST(@TotalJefes AS VARCHAR(10));

    DROP TABLE IF EXISTS #SedeJefes;
    DROP TABLE IF EXISTS #ResultadoUnificacion;
END;
GO
