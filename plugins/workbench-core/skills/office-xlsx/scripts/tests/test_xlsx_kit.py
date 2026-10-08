import importlib.util, os, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COM = os.name == "nt" and os.environ.get("OFFICE_COM_TESTS") == "1"   # opt-in: launches real Excel


@unittest.skipUnless(importlib.util.find_spec("openpyxl"), "needs openpyxl")
class XlsxKitTest(unittest.TestCase):
    def setUp(self):
        import xlsx_kit
        from openpyxl import Workbook
        self.k = xlsx_kit
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "model.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Model"
        ws.append(["Item", "Units", "Price", "Revenue"])
        for i, (name, u, p) in enumerate([("A", 10, 2.5), ("B", 4, 10), ("C", 7, 3), ("D", 1, 1)], start=2):
            ws.append([name, u, p, f"=B{i}*C{i}"])
        ws["D4"] = 40                                  # a typed result where a formula belongs
        ws.append(["Total", "=SUM(B2:B5)", None, "=SUM(D2:D5)"])
        ws["F1"], ws["F2"] = "Ratio", "=D6/0"
        ws2 = wb.create_sheet("Summary")
        ws2.append(["Metric", "Value"])
        ws2.append(["Revenue", "=Model!D6"])
        ws2["C2"] = "#DIV/0!"                          # openpyxl stores this as an error value
        self.k.add_list_validation(ws2, "D2:D10", ["Low", "Medium", "High"], prompt="Pick a risk level")
        self.k.style_workbook(wb)
        wb.save(self.path)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_styles_freeze_validation(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.path)
        m, s = wb["Model"], wb["Summary"]
        self.assertEqual(m["B2"].style, "Input")
        self.assertEqual(m["B2"].font.color.rgb, "000000FF")
        self.assertEqual(m["D2"].style, "Formula")
        self.assertEqual(m["A1"].style, "Header")
        self.assertEqual(m["D6"].style, "Total")
        self.assertEqual(s["B2"].style, "Link")
        self.assertEqual(s["B2"].font.color.rgb, "00008000")
        self.assertEqual(m.freeze_panes, "A2")
        self.assertEqual(s.data_validations.dataValidation[0].formula1, '"Low,Medium,High"')

    def test_check_without_recalc(self):
        problems = self.k.check(self.path)
        kinds = {(p["kind"], p["sheet"], p["cell"]) for p in problems}
        self.assertIn(("error", "Summary", "C2"), kinds)
        self.assertIn(("uncalculated", "Model", "D2"), kinds)
        self.assertIn(("hardcoded", "Model", "D4"), kinds)
        self.assertNotIn(("hardcoded", "Model", "B3"), kinds)       # an input column, no formulas around it
        self.assertEqual(self.k.main(["check", self.path]), 1)

    def test_refuses_macro_and_legacy_formats(self):
        for ext in (".xlsm", ".xltm", ".xls"):
            p = os.path.join(self.d, "book" + ext)
            shutil.copyfile(self.path, p)
            self.assertEqual(self.k.main(["check", p, "--recalc", "excel"]), 2)
            self.assertEqual(self.k.main(["style", p]), 2)
            with self.assertRaises(ValueError):
                self.k.recalc(p, "excel")
        ps = self.k.PS_RECALC
        self.assertLess(ps.index("AutomationSecurity = 3"), ps.index(".Open("))
        self.assertIn("Workbooks.Open($env:XLSX_IN, 0, $true)", ps)       # read-only

    @unittest.skipUnless(COM, "set OFFICE_COM_TESTS=1 on Windows with Excel")
    def test_excel_recalc_finds_real_errors(self):
        self.assertEqual(self.k.recalc(self.path, "excel"), "excel")
        problems = self.k.check(self.path)
        self.assertIn(("error", "Model", "F2"), {(p["kind"], p["sheet"], p["cell"]) for p in problems})
        self.assertFalse([p for p in problems if p["kind"] == "uncalculated"])
        from openpyxl import load_workbook
        self.assertEqual(load_workbook(self.path, data_only=True)["Model"]["D2"].value, 25)


if __name__ == "__main__":
    unittest.main()
