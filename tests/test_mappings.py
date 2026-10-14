import unittest
from config import resolve_db_and_table

class TestMappings(unittest.TestCase):
    def test_alta_mapping(self):
        res = resolve_db_and_table("MATRIZ 3100- ALTA AGOSTO (1).xlsx")
        self.assertIsNotNone(res)
        db, table, sede = res
        self.assertEqual(db, "DGEMPRES01")
        self.assertEqual(table, "BGD_MATRIZ_3100_A")
        self.assertEqual(sede, "A")

    def test_centro_mapping(self):
        res = resolve_db_and_table("MATRIZ 3100 - CENTRO AGOSTO.xlsx")
        self.assertIsNotNone(res)
        db, table, sede = res
        self.assertEqual(db, "DGEMPRES01")
        self.assertEqual(table, "BGD_MATRIZ_3100_C")
        self.assertEqual(sede, "C")

    def test_aguachica_mapping(self):
        res = resolve_db_and_table("MATRIZ 3100 -AGUACHICA AGOSTO.xlsx")
        self.assertIsNotNone(res)
        db, table, sede = res
        self.assertEqual(db, "DGEMPRES30")
        self.assertEqual(table, "BGD_MATRIZ_3100_AG")
        self.assertEqual(sede, "AG")

    def test_san_juan_mapping(self):
        res = resolve_db_and_table("MATRIZ 3100 - SAN JUAN AGOSTO.xlsx")
        self.assertIsNotNone(res)
        db, table, sede = res
        self.assertEqual(db, "DGEMPRES70")
        self.assertEqual(table, "BGD_MATRIZ_3100_SJ")
        self.assertEqual(sede, "SJ")

    def test_valle_mapping(self):
        res = resolve_db_and_table("MATRIZ 3100 - VALLE AGOSTO.xlsx")
        self.assertIsNotNone(res)
        db, table, sede = res
        self.assertEqual(db, "DGEMPRES80")
        self.assertEqual(table, "BGD_MATRIZ_3100_V")
        self.assertEqual(sede, "V")

    def test_unknown_mapping(self):
        res = resolve_db_and_table("OTRO ARCHIVO DESCONOCIDO.xlsx")
        self.assertIsNone(res)

if __name__ == "__main__":
    unittest.main()
