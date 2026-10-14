USE [DGEMPRES99]
GO

-- ==========================================================================================
-- Script: seed_catalogos_v2.sql
-- Descripción: Inserción directa de los 28 cursos normativos en dbo.BGD_MTZ3100_CATCURSO
--              con sus códigos de servicio por defecto exactos definidos por el usuario.
-- ==========================================================================================

SET NOCOUNT ON;

-- 1. Catálogo de Cursos (dbo.BGD_MTZ3100_CATCURSO)
MERGE dbo.BGD_MTZ3100_CATCURSO AS target
USING (
    VALUES
        ('BLS', 'C01', 1, 24, 1, 'TODOS'),
        ('ACLS', 'C02', 2, 24, 1, 'TODOS'),
        ('GESTION DEL DUELO', 'C03', 3, 24, 1, 'TODOS'),
        ('ATENCION A LAS VICTIMAS DE ATAQUES QUIMICOS', 'C04', 4, 24, 1, 'TODOS'),
        ('ATENCION A LAS VICTIMAS DE VIOLENCIA SEXUAL', 'C05', 5, 24, 1, 'TODOS'),
        ('HUMANIZACION', 'C06', 6, 24, 1, 'TODOS'),
        ('GESTION OPERATIVA DE LA DONACION', 'C07', 7, 24, 1, 'TODOS'),
        ('DENGUE', 'C08', 8, 24, 1, 'TODOS'),
        ('POCT', 'C09', 9, 24, 1, 'TODOS'),
        ('PALS', 'C10', 10, 24, 1, '0048;0049;0050;0089;0094;0103;0113'),
        ('NALS', 'C11', 11, 24, 1, '0059;0088'),
        ('AIEPI', 'C12', 12, 24, 1, '0048;0049;0050;0059;0089;0094;0103;0113'),
        ('MANEJO DEL DOLOR Y CUIDADOS PALIATIVOS', 'C13', 13, 24, 1, 'TODOS'),
        ('INMUNOLOGIA DE TRANSPLANTES', 'C14', 14, 24, 1, 'TODOS'),
        ('GESTION PRE-TRANSFUCIONAL', 'C15', 15, 24, 1, 'TODOS'),
        ('ADMINISTRACION DE MEDICAMENTOS', 'C16', 16, 24, 1, 'TODOS'),
        ('TOMA DE MUESTRAS', 'C17', 17, 24, 1, 'TODOS'),
        ('CADENA DE FRIO', 'C18', 18, 24, 1, '0055;0056;0072;0100'),
        ('ATENCION DEL PACIENTE EN DIALISIS RENAL - DIALISIS', 'C19', 19, 24, 1, '0076;0079'),
        ('ASESORIA PRE TEST POST TEST HIV', 'C20', 20, 24, 1, 'TODOS'),
        ('OVEM - COVE', 'C21', 21, 24, 1, 'TODOS'),
        ('DIPLOMADO MANEJO DE PACIENTE ONCOLOGICO', 'C22', 22, 60, 1, '0062'),
        ('DIPLOMADO CUIDADO INTENSIVO DE PACIENTE NEONATO', 'C23', 23, 60, 1, '0059;0088'),
        ('DIPLOMADO CUIDADO INTENSIVO DE PACIENTE ADULTO', 'C24', 24, 60, 1, '0080;0081;0082;0084;0085;0086;0106'),
        ('DIPLOMADO CUIDADO INTENSIVO DE PACIENTE PEDIATRICO', 'C25', 25, 60, 1, '0048;0049;0050;0089;0094;0103;0113'),
        ('DIPLOMADO ONCO - HEMATOLOGIA PEDIATRICA', 'C26', 26, 60, 1, '0113'),
        ('DIPLOMADO CUIDADO INTENSIVO DE PACIENTE QUEMADO', 'C27', 27, 60, 1, '0090'),
        ('DIPLOMADO URGENCIAS', 'C28', 28, 60, 1, '0091;0092;0093;0094;0095;0096;0097;0099;0103;0107;0108')
) AS source (CURSO_NOMBRE, ID_CURSO, ORDEN, VIGENCIA_MESES, ACTIVO, SERVICIOS_DEFECTO)
ON (target.CURSO_NOMBRE = source.CURSO_NOMBRE)
WHEN MATCHED THEN
    UPDATE SET 
        target.ID_CURSO = source.ID_CURSO,
        target.ORDEN = source.ORDEN,
        target.VIGENCIA_MESES = source.VIGENCIA_MESES,
        target.ACTIVO = source.ACTIVO,
        target.SERVICIOS_DEFECTO = source.SERVICIOS_DEFECTO,
        target.FECHA_ACTUALIZACION = SYSUTCDATETIME()
WHEN NOT MATCHED THEN
    INSERT (CURSO_NOMBRE, ID_CURSO, ORDEN, VIGENCIA_MESES, ACTIVO, SERVICIOS_DEFECTO, FECHA_CREACION, USUARIO_CREACION)
    VALUES (source.CURSO_NOMBRE, source.ID_CURSO, source.ORDEN, source.VIGENCIA_MESES, source.ACTIVO, source.SERVICIOS_DEFECTO, SYSUTCDATETIME(), 'SYSTEM_RPA');

PRINT 'dbo.BGD_MTZ3100_CATCURSO actualizado exitosamente con 28 cursos normativos.';
GO
