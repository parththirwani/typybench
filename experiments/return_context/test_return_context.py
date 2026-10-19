import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from .predict import make_messages, parse_prediction
from .predict_structured import COHORT, make_structured_messages
from .memory import build_memory
from .score import _mcnemar_two_sided, score
from .trigger_score import choose_arm, score_trigger
from .trigger_v2 import choose_arm as choose_v2
from .trigger_v3 import choose_arm as choose_v3
from .trigger_v5 import choose_action as choose_v5
from .trigger_v6 import choose_action as choose_v6
from .explore_static_types import source_features
from .extract_frozen_references import extract
from .select import select_candidates


class TestSelection(unittest.TestCase):
    def test_fresh_cohort_has_independent_callees(self):
        cases = select_candidates(COHORT, limit=60)
        self.assertEqual(len(cases), 60)
        self.assertEqual(len({case["case_id"] for case in cases}), 60)
        self.assertTrue({case["repo"] for case in cases} <= set(COHORT))

    def test_structured_memory_is_bounded_and_arm_a_unchanged(self):
        case = select_candidates(COHORT, limit=60)[0]
        case["return_memory"], case["return_memory_hash"] = build_memory(case)
        self.assertLessEqual(len(case["return_memory"]), 1000)
        a = make_structured_messages(case, "A")
        b = make_structured_messages(case, "B")
        self.assertEqual(a, make_messages(case, "A"))
        self.assertTrue(b[1]["content"].startswith(a[1]["content"]))
        self.assertIn(case["return_memory"], b[1]["content"])

    def test_candidates_are_unique_and_source_is_stripped(self):
        cases = select_candidates()
        self.assertGreaterEqual(len(cases), 20)
        self.assertLessEqual(len(cases), 60)
        self.assertEqual(len({case["case_id"] for case in cases}), len(cases))
        for case in cases:
            self.assertNotIn("original_repo", case["source_file"])
            self.assertNotIn("original_repo", case["callee_file"])
            self.assertLessEqual(len(case["callee_content"]), 1200)

    def test_arm_b_only_adds_retrieved_definition(self):
        case = select_candidates()[0]
        a = make_messages(case, "A")
        b = make_messages(case, "B")
        self.assertEqual(a[0], b[0])
        self.assertTrue(b[1]["content"].startswith(a[1]["content"]))
        self.assertNotIn("Retrieved untyped target definition", a[1]["content"])
        self.assertIn(case["callee_content"], b[1]["content"])


class TestParsing(unittest.TestCase):
    def test_valid_json_type(self):
        self.assertEqual(parse_prediction('{"return_type": "list[ str ]"}'), ("list[str]", None))

    def test_invalid_response(self):
        prediction, error = parse_prediction("not JSON")
        self.assertIsNone(prediction)
        self.assertIsNotNone(error)


class TestScoring(unittest.TestCase):
    def test_exact_mcnemar(self):
        self.assertEqual(_mcnemar_two_sided(0, 0), 1.0)
        self.assertEqual(_mcnemar_two_sided(0, 6), 0.03125)

    def test_freeze_checked_before_reference_read(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "selection.json").write_text("[]")
            (run / "rows.jsonl").write_text("")
            (run / "manifest.json").write_text(json.dumps({"phase": "smoke", "selection_sha256": "wrong"}))
            (run / "predictions_frozen.json").write_text(json.dumps({"rows_sha256": "wrong", "rows": 0}))
            with patch.object(sys.modules[score.__module__], "_reference_return") as reference:
                with self.assertRaises(ValueError):
                    score(run)
                reference.assert_not_called()


class TestTrigger(unittest.TestCase):
    def test_source_signal_rule(self):
        self.assertEqual(choose_arm({"return_memory": "return line 4: result"}), "A")
        self.assertEqual(choose_arm({"return_memory": "assignment line 3: result = x"}), "B")
        self.assertEqual(choose_arm({"return_memory": "yield line 3: item"}), "B")

    def test_policy_uses_only_chosen_arm_cost_and_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            cases = [
                {"case_id": "x", "return_memory": "return line 4: result"},
                {"case_id": "y", "return_memory": "yield line 4: item"},
            ]
            rows = [
                {"case_id": cid, "arm": arm, "input_tokens": tokens,
                 "output_tokens": 1, "latency_ms": 1}
                for cid, arms in (("x", (("A", 10), ("B", 20))),
                                  ("y", (("A", 12), ("B", 22))))
                for arm, tokens in arms
            ]
            (run / "selection.json").write_text(json.dumps(cases))
            (run / "rows.jsonl").write_text("\n".join(map(json.dumps, rows)))
            paired = {
                "selected": 2, "evaluable": 2, "missing_reference": 0,
                "a_exact": 1, "b_exact": 1,
                "usage": {"A": {"input_tokens": 22, "missing_usage_rows": 0},
                          "B": {"input_tokens": 42, "missing_usage_rows": 0}},
                "cases": [
                    {"case_id": "x", "evaluable": True,
                     "a_correct": True, "b_correct": False},
                    {"case_id": "y", "evaluable": True,
                     "a_correct": False, "b_correct": True},
                ],
            }
            with patch.object(sys.modules[score_trigger.__module__], "score", return_value=paired):
                result = score_trigger(run)
            self.assertEqual(result["trigger_exact"], 2)
            self.assertEqual(result["usage"]["trigger"]["input_tokens"], 32)
            self.assertEqual(result["trigger_b_evaluable"], 1)
            self.assertEqual(result["trigger_vs_a"]["trigger_only"], 1)

    def test_v2_rule_uses_only_source_memory(self):
        self.assertEqual(choose_v2({"return_memory": "return line 2: cast(int, value)"}), "B")
        self.assertEqual(choose_v2({"return_memory": "yield line 3: item"}), "B")
        self.assertEqual(choose_v2({"return_memory": "return line 4: Path(value)"}), "B")
        self.assertEqual(choose_v2({"return_memory": "return line 4: path(value)"}), "A")

    def test_v3_combines_both_source_signals(self):
        self.assertEqual(choose_v3({"return_memory": "assignment line 3: x = value"}), "B")
        self.assertEqual(choose_v3({"return_memory": "yield line 3: value"}), "B")
        self.assertEqual(choose_v3({"return_memory": "return line 4: cast(int, x)"}), "B")
        self.assertEqual(choose_v3({"return_memory": "return line 4: Path(value)"}), "B")
        self.assertEqual(choose_v3({"return_memory": "return line 4: path(value)"}), "A")

    def test_v5_static_none_abstains_on_exception_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x/repo_without_types/mod.py"
            source.parent.mkdir(parents=True)
            case = {"case_id": "x:mod.py:f", "repo": "x", "callee_file": "mod.py",
                    "callee_symbol": "f", "return_memory":
                    "Source: mod.py:1 function f\nNo explicit return or yield; implicit return None."}
            with patch.object(sys.modules[source_features.__module__], "DATA_ROOT", root):
                source.write_text("def f():\n    print('done')\n")
                self.assertEqual(choose_v5(case), "static:None")
                source.write_text("def f():\n    assert False\n")
                self.assertEqual(choose_v5(case), "A")
                source.write_text("def f():\n    raise ValueError()\n")
                self.assertEqual(choose_v5(case), "A")
                case["return_memory"] = "return line 2: True"
                source.write_text("def f():\n    return True\n")
                self.assertEqual(choose_v5(case), "static:bool")
                source.write_text("def f():\n    yield True\n    return True\n")
                self.assertEqual(choose_v5(case), "A")

    def test_v6_distinguishes_assignment_from_type_bearing_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x/repo_without_types/mod.py"
            source.parent.mkdir(parents=True)
            case = {"case_id": "x:mod.py:f", "repo": "x", "callee_file": "mod.py",
                    "callee_symbol": "f", "return_memory":
                    "return line 3: value\nassignment line 2: value = []"}
            with (patch.object(sys.modules[source_features.__module__], "DATA_ROOT", root),
                  patch.object(sys.modules[choose_v6.__module__], "DATA_ROOT", root)):
                source.write_text("def f():\n    value = []\n    return value\n")
                self.assertEqual(choose_v6(case), "A")
                source.write_text("def f():\n    value = Factory()\n    return value\n")
                self.assertEqual(choose_v6(case), "B")
                case["return_memory"] = "return line 3: np.squeeze(value)"
                source.write_text("import numpy as np\ndef f(value):\n    return np.squeeze(value)\n")
                self.assertEqual(choose_v6(case), "B")


class TestReferenceExtraction(unittest.TestCase):
    def test_requires_freeze_then_extracts_only_selected_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            run.mkdir()
            selection = json.dumps([{"case_id": "x:file.py:f", "repo": "x",
                                     "callee_file": "file.py"}]).encode()
            rows = (json.dumps({"case_id": "x:file.py:f", "arm": "A"}) + "\n" +
                    json.dumps({"case_id": "x:file.py:f", "arm": "B"}) + "\n").encode()
            (run / "selection.json").write_bytes(selection)
            (run / "rows.jsonl").write_bytes(rows)
            (run / "manifest.json").write_text(json.dumps({
                "repositories": ["x"],
                "selection_sha256": hashlib.sha256(selection).hexdigest(),
            }))
            (run / "predictions_frozen.json").write_text(json.dumps({
                "rows_sha256": "invalid", "rows": 2,
            }))
            archive = root / "dataset.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("typybenchdata/x/original_repo/file.py", "def f() -> int: ...\n")
                z.writestr("typybenchdata/x/original_repo/other.py", "unused\n")
            with patch.object(sys.modules[extract.__module__], "DATA_ROOT", root / "data"):
                with self.assertRaises(ValueError):
                    extract(run, archive)
                self.assertFalse((root / "data").exists())
                (run / "predictions_frozen.json").write_text(json.dumps({
                    "rows_sha256": hashlib.sha256(rows).hexdigest(), "rows": 2,
                }))
                result = extract(run, archive)
                self.assertEqual(len(result["extracted"]), 1)
                self.assertTrue((root / "data/x/original_repo/file.py").exists())
                self.assertFalse((root / "data/x/original_repo/other.py").exists())


if __name__ == "__main__":
    unittest.main()
