import ast
import unittest

from .predict import make_messages, parse_prediction
from .select import (
    _evidence_kind, _imported_names, _matches_call, _provided_argument,
    select_cases,
)


class SelectionTests(unittest.TestCase):
    def test_direct_alias_and_module_alias(self):
        direct, modules = _imported_names(
            "from package.api import build as make", "build", "api")
        self.assertEqual(direct, {"make"})
        self.assertEqual(modules, set())
        self.assertTrue(_matches_call(ast.parse("make(3)", mode="eval").body,
                                      direct, modules, "build"))
        direct, modules = _imported_names(
            "from package import api as module", "build", "api")
        self.assertEqual(modules, {"module"})
        self.assertTrue(_matches_call(ast.parse("module.build(3)", mode="eval").body,
                                      direct, modules, "build"))
        self.assertFalse(_matches_call(ast.parse("other.build(3)", mode="eval").body,
                                       direct, modules, "build"))

    def test_supplied_positional_and_keyword(self):
        function = ast.parse("def build(left, right, *, flag): pass").body[0]
        call = ast.parse("build(1, right='x', flag=True)", mode="eval").body
        parameters = function.args.args + function.args.kwonlyargs
        self.assertEqual(ast.unparse(_provided_argument(call, function, parameters[0])), "1")
        self.assertEqual(ast.unparse(_provided_argument(call, function, parameters[1])), "'x'")
        self.assertEqual(ast.unparse(_provided_argument(call, function, parameters[2])), "True")
        self.assertIsNone(_provided_argument(
            ast.parse("build(*values)", mode="eval").body, function, parameters[0]))

    def test_evidence_kind(self):
        self.assertEqual(_evidence_kind(ast.parse("'x'", mode="eval").body), "literal")
        self.assertEqual(_evidence_kind(ast.parse("[1]", mode="eval").body), "container")
        self.assertEqual(_evidence_kind(ast.parse("factory()", mode="eval").body), "call")
        self.assertEqual(_evidence_kind(ast.parse("value", mode="eval").body), "other")

    def test_source_only_cases_are_unique_and_have_supplied_argument(self):
        cases = select_cases(limit=120)
        self.assertGreaterEqual(len(cases), 90)
        self.assertEqual(len({case["case_id"] for case in cases}), len(cases))
        for case in cases:
            self.assertNotIn("original_repo", str(case))
            self.assertTrue(case["argument_expression"])
            self.assertTrue(case["call_text"])


class PredictionTests(unittest.TestCase):
    def test_prompts_differ_only_by_extra_caller_evidence(self):
        case = {
            "repo": "sample", "parameter": "item", "callee_symbol": "use",
            "callee_file": "sample/use.py", "callee_block": "def use(item): return item",
            "source_file": "sample/main.py", "call_line": 4,
            "import_statement": "from sample.use import use",
            "call_text": "use(3)", "argument_expression": "3",
            "caller_block": "def run(): return use(3)",
        }
        a = make_messages(case, "A")
        b = make_messages(case, "B")
        self.assertEqual(a[0], b[0])
        self.assertTrue(b[1]["content"].startswith(a[1]["content"]))
        self.assertIn("use(3)", b[1]["content"])

    def test_json_prediction_parser(self):
        self.assertEqual(parse_prediction('{"parameter_type":" list [ str ] "}'),
                         ("list[str]", None))
        self.assertIsNotNone(parse_prediction("not json")[1])
        self.assertIsNotNone(parse_prediction('{"parameter_type": 3}')[1])


if __name__ == "__main__":
    unittest.main()
