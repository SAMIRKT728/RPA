USE [DGEMPRES01]
GO
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

-- ==========================================================================================
-- Procedimiento: dbo.sp_ObtenerJefesUnificados_MX100
-- Base de Datos: DGEMPRES01
-- Descripción  : Unifica y estandariza los nombres de jefes inmediatos provenientes de las
--                5 matrices de sedes (ALTA, CENTRO, AGUACHICA, SAN JUAN, VALLE).
--                Resuelve conflictos de intercalación (Collation) mediante COLLATE DATABASE_DEFAULT,
--                persiste el catálogo en dbo.BGD_JEFES_UNIFICADOS_MX100 y retorna el resultado.
-- ==========================================================================================

CREATE OR ALTER PROCEDURE [dbo].[sp_ObtenerJefesUnificados_MX100]
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Garantizar existencia física de la tabla de destino
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

    -- 2. Limpieza de datos previos para idempotencia
    TRUNCATE TABLE dbo.BGD_JEFES_UNIFICADOS_MX100;

    -- 3. Extracción con resolución de intercalación (Modern_Spanish_CI_AS vs Latin1_General_CI_AS)
    WITH Datos AS
    (
        SELECT CAST([JEFE INMEDIATO] AS VARCHAR(500)) COLLATE DATABASE_DEFAULT AS NombreOriginal
        FROM DGEMPRES01.dbo.BGD_MATRIZ_3100_A
        UNION ALL
        SELECT CAST([JEFE INMEDIATO] AS VARCHAR(500)) COLLATE DATABASE_DEFAULT AS NombreOriginal
        FROM DGEMPRES01.dbo.BGD_MATRIZ_3100_C
        UNION ALL
        SELECT CAST([JEFE INMEDIATO] AS VARCHAR(500)) COLLATE DATABASE_DEFAULT AS NombreOriginal
        FROM DGEMPRES30.dbo.BGD_MATRIZ_3100_AG
        UNION ALL
        SELECT CAST([JEFE INMEDIATO] AS VARCHAR(500)) COLLATE DATABASE_DEFAULT AS NombreOriginal
        FROM DGEMPRES70.dbo.BGD_MATRIZ_3100_SJ
        UNION ALL
        SELECT CAST([JEFE INMEDIATO] AS VARCHAR(500)) COLLATE DATABASE_DEFAULT AS NombreOriginal
        FROM DGEMPRES80.dbo.BGD_MATRIZ_3100_V
    ),

    Nombres AS
    (
        SELECT DISTINCT
            LTRIM(RTRIM(NombreOriginal)) AS NombreOriginal
        FROM Datos
        WHERE NombreOriginal IS NOT NULL
          AND LTRIM(RTRIM(NombreOriginal)) <> ''
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
                                REPLACE(NombreOriginal, '  ', ' '),
                                '.', ''
                            ),
                            ',', ''
                        ),
                        '-', ' '
                    )
                ))
            ) AS NombreNormalizado
        FROM Nombres
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

    -- 4. Persistir en la tabla física de catálogo
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
    FROM Resultado
    WHERE RN = 1
    GROUP BY NombreUnificado;

    -- 5. Retornar el dataset
    SELECT
        NombreUnificado,
        Variantes,
        CantidadVariantes,
        _fecha_calculo
    FROM dbo.BGD_JEFES_UNIFICADOS_MX100
    ORDER BY NombreUnificado;

END;
GO
