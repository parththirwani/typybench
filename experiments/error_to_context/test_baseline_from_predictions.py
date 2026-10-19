import ast
import unittest

from .baseline_from_predictions import _insert_annotations


class DerivedBaselineTests(unittest.TestCase):
    def test_inserts_one_annotation_without_changing_call(self):
        source = "def use(value):\n    return print(value)\n"
        result, rejected = _insert_annotations(source, [{
            "case_id": "one", "callee_symbol": "use",
            "parameter": "value", "prediction": "str",
        }])
        self.assertEqual(rejected, [])
        self.assertIn("def use(value: str):", result)
        self.assertEqual(ast.unparse(ast.parse(result).body[0].body[0]),
                         "return print(value)")

    def test_multiline_header_and_unicode_before_parameter(self):
        source = "def f(\n    first,\n    value,\n):\n    return first\n"
        result, rejected = _insert_annotations(source, [{
            "case_id": "two", "callee_symbol": "f",
            "parameter": "value", "prediction": "list[str]",
        }])
        self.assertEqual(rejected, [])
        self.assertIn("    value: list[str],", result)

    def test_rejects_missing_parameter(self):
        source = "def f(item): return item\n"
        result, rejected = _insert_annotations(source, [{
            "case_id": "three", "callee_symbol": "f",
            "parameter": "other", "prediction": "int",
        }])
        self.assertEqual(result, source)
        self.assertEqual(len(rejected), 1)


if __name__ == "__main__":
    unittest.main()
