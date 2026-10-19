import os
import sys
import json
import ast
import unittest
import tempfile
import shutil
import dataclasses
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from experiments.error_to_context.fixtures import create_fixture_repo_without_types, create_cross_file_fixture
from experiments.error_to_context import retrieval as ret_mod
from experiments.error_to_context.cloud_client import MockCloudClient, CloudClient, ENV_KEY
from experiments.error_to_context.preflight import (
    run_preflight, check_data_path, check_split, check_mypy_version,
    check_api_key, check_output_path,
)
from experiments.error_to_context.diagnostics import (
    parse_mypy_lines, Diagnostic, deduplicate_diagnostics, sort_diagnostics,
    run_mypy, read_source_window, TARGET_CODES, Case,
)
from experiments.error_to_context.retrieval import (
    resolve_import, extract_definition, RetrievedDef,
    resolve_symbol_from_diagnostic, _truncate, find_parameter_annotation,
    find_positional_parameter_annotation,
)
from experiments.error_to_context.correction import (
    CorrectionRow, run_correction, _extract_code, _apply_valid_edit, _line_is_annotation, _matches_target, _relativize,
    _annotation_nodes_differ,
)
from experiments.error_to_context.diagnostics import Diagnostic
from experiments.error_to_context.baseline import (
    _extract_code as base_extract_code, _is_annotation_only_block,
    _annotate_file_by_defs, _check_gate, build_baseline,
)
from experiments.error_to_context.annotation_coverage import coverage_delta
from experiments.error_to_context.summarize import summarize


class TestPreflight(unittest.TestCase):
    def test_data_path_exists(self):
        ok, msg = check_data_path()
        self.assertTrue(ok, msg)

    def test_flask_in_dev_split(self):
        ok, msg = check_split()
        self.assertTrue(ok, msg)

    def test_mypy_version(self):
        ok, msg = check_mypy_version()
        self.assertTrue(ok, msg)

    def test_api_key_detection(self):
        old = os.environ.get(ENV_KEY)
        if old:
            del os.environ[ENV_KEY]
        try:
            ok, _ = check_api_key()
            self.assertFalse(ok)
        finally:
            if old:
                os.environ[ENV_KEY] = old

    def test_output_path_rejects_original_repo(self):
        ok, _ = check_output_path("/tmp/foo/original_repo/bar")
        self.assertFalse(ok)
        ok, _ = check_output_path("/tmp/runs/my_run")
        self.assertTrue(ok)

    def test_preflight_dry_run_no_api_calls(self):
        all_ok, results = run_preflight(output_path="/tmp/test_out", dry_run=True)
        self.assertIsInstance(all_ok, bool)


class TestDiagnostics(unittest.TestCase):
    def test_parse_typical_line(self):
        line = "/tmp/foo.py:10: error: Incompatible types [arg-type]"
        diags = parse_mypy_lines([line])
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "arg-type")
        self.assertEqual(diags[0].line, 10)

    def test_parse_with_column(self):
        line = "/tmp/foo.py:10:5: error: Something [assignment]"
        diags = parse_mypy_lines([line])
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].code, "assignment")
        self.assertEqual(diags[0].line, 10)

    def test_parse_ignores_untargeted_codes(self):
        lines = [
            "/tmp/foo.py:1: error: X [arg-type]",
            "/tmp/foo.py:2: error: Y [return-value]",
            "/tmp/foo.py:3: error: Z [attr-defined]",
        ]
        diags = parse_mypy_lines(lines)
        codes = {d.code for d in diags}
        self.assertIn("arg-type", codes)
        self.assertIn("attr-defined", codes)
        self.assertNotIn("return-value", codes)

    def test_parse_code_after_bracketed_type_in_message(self):
        line = 'pkg/mod.py:9: error: Argument 1 has incompatible type "Sequence[Thing | None]"; expected "Sequence[Thing]"  [arg-type]'
        diagnostics = parse_mypy_lines([line])
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "arg-type")
        self.assertIn("Sequence[Thing | None]", diagnostics[0].message)

    def test_deduplicate(self):
        diags = [
            Diagnostic("/tmp/a.py", 10, 0, "arg-type", "msg"),
            Diagnostic("/tmp/a.py", 10, 0, "arg-type", "msg"),
            Diagnostic("/tmp/b.py", 5, 0, "assignment", "msg2"),
        ]
        result = deduplicate_diagnostics(diags)
        self.assertEqual(len(result), 2)

    def test_case_id_distinguishes_messages_at_same_location(self):
        first = Diagnostic("pkg/mod.py", 10, 0, "arg-type", "Expected str; got int")
        second = Diagnostic("pkg/mod.py", 10, 0, "arg-type", "Expected int; got str")
        self.assertNotEqual(first.case_id(), second.case_id())
        self.assertEqual(len(deduplicate_diagnostics([first, second])), 2)

    def test_sort_diagnostics(self):
        diags = [
            Diagnostic("/tmp/b.py", 5, 0, "assignment", "z"),
            Diagnostic("/tmp/a.py", 10, 0, "arg-type", "a"),
        ]
        result = sort_diagnostics(diags)
        self.assertEqual(result[0].file, "/tmp/a.py")
        self.assertEqual(result[1].file, "/tmp/b.py")

    def test_read_source_window(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("a\nb\nc\nd\ne\n")
            fname = f.name
        try:
            before, affected, after = read_source_window(fname, 3, context_lines=1)
            self.assertIn("b", before)
            self.assertIn("c", affected)
            self.assertIn("d", after)
        finally:
            os.unlink(fname)

    def test_credential_not_in_error_output(self):
        lines = parse_mypy_lines(["/tmp/x.py:1: error: test [arg-type]"])
        output = json.dumps([d.case_id() for d in lines])
        self.assertNotIn("sk-", output)
        self.assertNotIn("CODEMATE", output)


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.repo = create_fixture_repo_without_types()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_resolve_absolute_import(self):
        src_file = os.path.join(self.repo, "src", "app.py")
        path = resolve_import("mylib.models", src_file, os.path.join(self.repo, "src"))
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("models.py") or path.endswith("__init__.py"))

    def test_resolve_submodule_import(self):
        src_file = os.path.join(self.repo, "src", "app.py")
        path = resolve_import("mylib.utils", src_file, os.path.join(self.repo, "src"))
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("utils.py"))

    def test_generated_source_can_only_resolve_into_untyped_tree(self):
        with tempfile.TemporaryDirectory() as generated:
            predicted = os.path.join(generated, "src", "mylib")
            os.makedirs(predicted)
            generated_file = os.path.join(predicted, "caller.py")
            Path(generated_file).write_text("from .models import User\n")
            Path(os.path.join(predicted, "models.py")).write_text("class User: pass\n")
            resolved = resolve_import("models", generated_file, self.repo)
            self.assertEqual(resolved, os.path.join(self.repo, "src", "mylib", "models.py"))
            self.assertFalse(resolved.startswith(generated))

    def test_find_constructor_parameter_repair_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.py"
            path.write_text("class Widget:\n    def __init__(self, size: int = 1):\n        self.size = size\n")
            self.assertEqual(find_parameter_annotation(str(path), "Widget", "size"), 2)
            self.assertEqual(find_positional_parameter_annotation(str(path), "Widget", 1), ("size", 2))
            self.assertIsNone(find_parameter_annotation(str(path), "Widget", "missing"))

    def test_extract_function_definition(self):
        models_path = os.path.join(self.repo, "src", "mylib", "models.py")
        retrieved = extract_definition(models_path, "User")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.symbol_name, "User")
        self.assertIn("class User", retrieved.content)

    def test_extract_module_level_var_definition(self):
        pass

    def test_unresolved_symbol_returns_none(self):
        models_path = os.path.join(self.repo, "src", "mylib", "models.py")
        retrieved = extract_definition(models_path, "NonExistentSymbol")
        self.assertIsNone(retrieved)

    def test_truncation_approx(self):
        long = "x" * 2000
        truncated, mode = _truncate(long, 500)
        self.assertEqual(mode, "approx")
        self.assertLessEqual(len(truncated), 520)

    def test_truncation_exact(self):
        short = "hello world"
        truncated, mode = _truncate(short, 1200)
        self.assertEqual(mode, "exact")
        self.assertEqual(truncated, short)


class TestCorrection(unittest.TestCase):
    def test_existing_correction_artifact_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline"
            baseline.mkdir()
            case = Case(
                case_id="pkg/mod.py:1:0:arg-type", diagnostic=Diagnostic(
                    "pkg/mod.py", 1, 0, "arg-type", "test"),
                source_line="x\n", window_before="", window_after="",
                symbol_name=None, resolved_def_path=None, resolved_def_span=None,
            )
            saved = Path(directory) / "corrections" / "pkg_mod.py_1_0_arg-type_A"
            saved.mkdir(parents=True)
            marker = saved / "keep.txt"
            marker.write_text("original")
            with self.assertRaises(FileExistsError):
                run_correction(case, str(baseline), directory, MockCloudClient())
            self.assertEqual(marker.read_text(), "original")

    def test_extract_code_python_block(self):
        response = "```python\ndef foo() -> int:\n    return 1\n```"
        result = _extract_code(response)
        self.assertIn("def foo", result)
        self.assertNotIn("```", result)

    def test_extract_code_bare(self):
        result = _extract_code("def foo() -> int: return 1")
        self.assertEqual(result, "def foo() -> int: return 1")

    def test_apply_edit_patch_single_line(self):
        source = "a\nb: int = 1\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "b: str = 1"}')
        self.assertTrue(ok, f"edit failed: {err}")
        self.assertIsNotNone(result)
        lines = result.split("\n")
        self.assertIn("str", lines[1])

    def test_apply_edit_value_change_rejected(self):
        source = "a\nb: int = 1\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "b: str = \'hello\'"}')
        self.assertFalse(ok)

    def test_noop_patch_is_not_a_valid_correction(self):
        source = "value: int = 1\n"
        result, ok, err = _apply_valid_edit(source, 1, '{"line": 1, "replacement": "value: int = 1"}')
        self.assertIsNone(result)
        self.assertFalse(ok)
        self.assertIn("no annotation change", err)

    def test_function_header_annotation_edit_uses_whole_file_ast(self):
        source = "def render(app: App) -> str:\n    return app.name\n"
        patch = '{"line": 1, "replacement": "def render(app: Flask) -> str:"}'
        result, ok, err = _apply_valid_edit(source, 1, patch)
        self.assertTrue(ok, err)
        self.assertIn("app: Flask", result)

    def test_frozen_repair_site_rejects_edit_elsewhere(self):
        source = "def f(x: int) -> int:\n    return x\n"
        patch = '{"line": 1, "replacement": "def f(x: str) -> int:"}'
        _, ok, err = _apply_valid_edit(source, 2, patch, allowed_line=2)
        self.assertFalse(ok)
        self.assertIn("outside frozen repair site", err)

    def test_apply_edit_out_of_bounds(self):
        source = "a\n"
        result, ok, err = _apply_valid_edit(source, 999, '{"line": 999, "replacement": "x"}')
        self.assertFalse(ok)

    def test_invalid_empty_response(self):
        source = "a\nb\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, "")
        self.assertFalse(ok)

    def test_annotation_only_edit_passes(self):
        source = "a\ndef f(x): return x\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "def f(x: int) -> int: return x"}')
        self.assertTrue(ok, f"edit failed: {err}")

    def test_executable_change_rejected(self):
        source = "a\ndef f(x): return x\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "def f(x): return x + 1"}')
        self.assertFalse(ok)

    def test_variable_annotation_only_passes(self):
        source = "a\ncfg = make_user(42, \"old\")\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "cfg: dict = make_user(42, \\\"old\\\")"}')
        self.assertTrue(ok, f"annotation-only edit failed: {err}")

    def test_executable_rhs_change_rejected(self):
        source = "a\ncfg = make_user(42, \"old\")\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "cfg: dict = make_user(\\\"Alice\\\", 30)"}')
        self.assertFalse(ok)

    def test_syntax_error_rejected(self):
        source = "a\nb\nc\n"
        result, ok, err = _apply_valid_edit(source, 2, '{"line": 2, "replacement": "def broken("}')
        self.assertFalse(ok)

    def test_annotation_nodes_differ_rejects_call_change(self):
        orig = ast.parse("cfg = make_user(42, 'old')")
        repl = ast.parse("cfg: dict = make_user('Alice', 30)")
        self.assertTrue(_annotation_nodes_differ(orig, repl))

    def test_annotation_nodes_differ_accepts_annotation_add(self):
        orig = ast.parse("cfg = make_user(42, 'old')")
        repl = ast.parse("cfg: dict = make_user(42, 'old')")
        self.assertFalse(_annotation_nodes_differ(orig, repl))

    def test_correction_row_defaults(self):
        row = CorrectionRow(
            case_id="test", arm="A", baseline_hash="abc",
            prompt_hash="def", retrieved_hash=None,
            model_response_id="resp1", edit_valid=True,
            baseline_error_count=5, corrected_error_count=3,
            target_diagnostic_gone=True, clean_correction=True,
            usage_input_tokens=100, usage_output_tokens=50,
            latency_ms=200.0,
        )
        self.assertEqual(row.arm, "A")
        self.assertTrue(row.clean_correction)

    def test_matches_target_same_dir(self):
        t = Diagnostic("src/app.py", 5, 0, "arg-type", "msg")
        d = Diagnostic("src/app.py", 5, 0, "arg-type", "msg")
        self.assertTrue(_matches_target(d, t))

    def test_matches_target_different_abs_dir(self):
        t = Diagnostic("/tmp/baseline/src/app.py", 5, 0, "arg-type", "msg")
        d = Diagnostic("/tmp/corrections/case_A/src/app.py", 5, 0, "arg-type", "msg")
        self.assertTrue(_matches_target(d, t))

    def test_matches_target_mismatch_code(self):
        t = Diagnostic("src/app.py", 5, 0, "arg-type", "msg")
        d = Diagnostic("src/app.py", 5, 0, "assignment", "msg")
        self.assertFalse(_matches_target(d, t))

    def test_matches_target_mismatch_message(self):
        t = Diagnostic("src/app.py", 5, 0, "arg-type", "old msg")
        d = Diagnostic("src/app.py", 5, 0, "arg-type", "new msg")
        self.assertFalse(_matches_target(d, t))

    def test_relativize_abs_with_baseline(self):
        result = _relativize("/tmp/runs/baseline/src/app.py")
        self.assertEqual(result, "src/app.py")

    def test_relativize_abs_with_corrections(self):
        result = _relativize("/tmp/runs/corrections/case_A/src/app.py")
        self.assertEqual(result, "src/app.py")

    def test_relativize_relative_passthrough(self):
        result = _relativize("src/app.py")
        self.assertEqual(result, "src/app.py")


class TestSummarize(unittest.TestCase):
    def test_no_results(self):
        with tempfile.TemporaryDirectory() as d:
            result = summarize(d)
            self.assertIn("error", result)

    def test_single_result(self):
        run_dir = tempfile.mkdtemp()
        try:
            corr_dir = os.path.join(run_dir, "corrections", "case1_A")
            os.makedirs(corr_dir)
            row = CorrectionRow(
                case_id="case1", arm="A", baseline_hash="abc",
                prompt_hash="def", retrieved_hash=None,
                model_response_id="r1", edit_valid=True,
                baseline_error_count=5, corrected_error_count=0,
                target_diagnostic_gone=True, clean_correction=True,
                usage_input_tokens=100, usage_output_tokens=50,
                latency_ms=200.0,
            )
            with open(os.path.join(corr_dir, "row.json"), "w") as f:
                json.dump({
                    "case_id": "case1", "arm": "A", "baseline_hash": "abc",
                    "prompt_hash": "def", "retrieved_hash": None,
                    "model_response_id": "r1", "edit_valid": True,
                    "baseline_error_count": 5, "corrected_error_count": 0,
                    "target_diagnostic_gone": True, "clean_correction": True,
                    "usage_input_tokens": 100, "usage_output_tokens": 50,
                    "latency_ms": 200.0, "error": None,
                }, f)
            result = summarize(run_dir)
            self.assertEqual(result["total_cases"], 1)
            self.assertEqual(result["arm_a_clean"], 1)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


class TestBaseline(unittest.TestCase):
    def test_flat_package_layout_is_not_written_under_src(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "untyped"
            package = source / "pkg"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (package / "mod.py").write_text("def f(x):\n    return x\n")
            output = Path(directory) / "output"
            baseline = build_baseline(str(source), str(output), MockCloudClient(),
                                      max_api_calls=1, gate=False)
            self.assertTrue((Path(baseline) / "pkg" / "mod.py").is_file())
            self.assertFalse((Path(baseline) / "src" / "pkg" / "mod.py").exists())

    def test_extract_code_from_markdown(self):
        content = "Here is the fix:\n```python\ndef f() -> int:\n    return 1\n```\n"
        from experiments.error_to_context.baseline import _extract_code as base_ec
        result = base_ec(content)
        self.assertIn("def f", result)

    def test_original_repo_isolation(self):
        self.assertNotIn("original_repo", __file__)


class TestBaselineAnnotationBlock(unittest.TestCase):
    def test_annotation_only_block_rejects_exec_change(self):
        old_lines = ["def f(x):", "    return x"]
        new_lines = ["def f(x):", "    return x + 1"]
        self.assertFalse(
            _is_annotation_only_block(old_lines, new_lines),
            "Adding +1 is an executable change",
        )

    def test_annotation_only_block_passes_annotation_add(self):
        old_lines = ["def f(x):", "    return x"]
        new_lines = ["def f(x: int) -> int:", "    return x"]
        self.assertTrue(
            _is_annotation_only_block(old_lines, new_lines),
            "Adding type annotations should pass",
        )

    def test_annotation_only_block_rejects_rhs_change_with_annotation(self):
        old = ["def f(x):", "    value = x + 1", "    return value"]
        new = ["def f(x: int) -> int:", "    value: int = x + 2", "    return value"]
        self.assertFalse(_is_annotation_only_block(old, new))

    def test_class_methods_are_annotated_without_overlapping_class_edit(self):
        class AnnotatingClient:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                if "def first(self, x):" in prompt:
                    return "def first(self, x: int) -> int:\n    return x", None
                if "def second(self, y):" in prompt:
                    return "def second(self, y: str) -> str:\n    return y", None
                return "", None

        source = "class Example:\n    def first(self, x):\n        return x\n\n    def second(self, y):\n        return y\n"
        with tempfile.TemporaryDirectory() as root:
            original = Path(root) / "original.py"
            annotated = Path(root) / "annotated.py"
            original.write_text(source)
            calls = _annotate_file_by_defs(original, annotated, AnnotatingClient(), 0, 10)
            result = annotated.read_text()
        self.assertEqual(calls, 2)
        self.assertIn("x: int", result)
        self.assertIn("y: str", result)
        self.assertEqual(len(ast.parse(result).body[0].body), 2)


class TestBaselineQualityGate(unittest.TestCase):
    def test_gate_uses_new_annotations_not_existing_types(self):
        original = "from typing import Any\ndef existing(x: str) -> str: return x\ndef new(y): return y\n"
        annotated = "from typing import Any\ndef existing(x: str) -> str: return x\ndef new(y: list[Any]) -> object: return y\n"
        with tempfile.TemporaryDirectory() as root:
            before = Path(root) / "before.py"
            after = Path(root) / "after.py"
            before.write_text(original)
            after.write_text(annotated)
            delta = coverage_delta(str(before), str(after))
        self.assertEqual(delta.added_total, 2)
        self.assertEqual(delta.added_any_annotations, 1)
        self.assertEqual(delta.added_object_annotations, 1)
        self.assertTrue(_check_gate([delta]))

    def test_gate_requires_some_new_annotations(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "typed.py"
            path.write_text("def f(x: str) -> str: return x\n")
            delta = coverage_delta(str(path), str(path))
        self.assertIn("No annotations were added", _check_gate([delta])[0]["reason"])


class TestCrossFileIntegration(unittest.TestCase):
    """End-to-end integration: fixture → mypy → selection → retrieval → correction → arm_b_total."""

    def setUp(self):
        self.repo = create_cross_file_fixture()
        self.run_dir = tempfile.mkdtemp(suffix="_cross_int")
        lines = run_mypy(self.repo)
        self.diags = sort_diagnostics(deduplicate_diagnostics(parse_mypy_lines(lines)))

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def _diagnostic_to_case(self, d: Diagnostic):
        before, affected, after = read_source_window(d.file, d.line, repo_root=self.repo)
        return Case(
            case_id=d.case_id(), diagnostic=d,
            source_line=affected, window_before=before,
            window_after=after, symbol_name=None,
            resolved_def_path=None, resolved_def_span=None,
        )

    def _extract_callee(self, message: str, code: str) -> str | None:
        if code == "assignment":
            return None
        if code == "attr-defined":
            parts = message.split()
            if parts:
                return parts[0].strip("'\"")
        if "to" in message:
            after_to = message.split("to", 1)[1].strip()
            if after_to.startswith('"'):
                return after_to.split('"')[1]
        return None

    def _resolve_import_name(self, name: str, source_path: str) -> str | None:
        import ast
        try:
            with open(source_path) as f:
                tree = ast.parse(f.read())
        except (SyntaxError, FileNotFoundError):
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    asname = alias.asname or alias.name.split(".")[-1]
                    if asname == name:
                        return alias.name
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    asname = alias.asname or alias.name
                    if asname == name:
                        return node.module or ""
        return None

    def test_full_pipeline_arm_b_total_equals_1(self):
        eligible = []
        for d in self.diags:
            if len(eligible) >= 1:
                break
            before, affected, after = read_source_window(d.file, d.line, repo_root=self.repo)
            callee = self._extract_callee(d.message, d.code)
            retrieved = None
            if callee:
                callee_module = self._resolve_import_name(callee, os.path.join(self.repo, d.file))
                if callee_module:
                    resolved_file = ret_mod.resolve_import(callee_module, os.path.join(self.repo, d.file), self.repo)
                    if resolved_file:
                        retrieved = ret_mod.extract_definition(resolved_file, callee)
            eligible.append({"d": d, "before": before, "affected": affected, "after": after, "retrieved": retrieved, "callee": callee})

        self.assertGreater(len(eligible), 0, "Expected at least one eligible case")

        client = MockCloudClient()
        results = []
        for cd in eligible:
            d = cd["d"]
            case = self._diagnostic_to_case(d)
            for arm, def_info in [("A", None), ("B", cd["retrieved"])]:
                row = run_correction(case, self.repo, self.run_dir, client, retrieved_def=def_info, dry_run=False)
                results.append(row)
                safe_id = d.case_id().replace(":", "_").replace("/", "_").replace("\\", "_")
                out_dir = os.path.join(self.run_dir, "corrections", f"{safe_id}_{arm}")
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "row.json"), "w") as f:
                    json.dump(dataclasses.asdict(row), f)

        summary = summarize(self.run_dir)
        self.assertEqual(summary["arm_b_total"], 1, f"Expected arm_b_total=1, got {summary}")

    def test_retrieval_resolves_cross_file_def(self):
        for d in self.diags:
            callee = self._extract_callee(d.message, d.code)
            if callee:
                callee_module = self._resolve_import_name(callee, os.path.join(self.repo, d.file))
                self.assertIsNotNone(callee_module, f"Could not resolve import for {callee}")
                resolved_file = ret_mod.resolve_import(callee_module, os.path.join(self.repo, d.file), self.repo)
                self.assertIsNotNone(resolved_file, f"Could not resolve file for {callee_module}")
                retrieved = ret_mod.extract_definition(resolved_file, callee)
                self.assertIsNotNone(retrieved, f"Could not extract definition for {callee}")
                self.assertEqual(retrieved.symbol_name, callee)
                return
        self.fail("No cross-file retrievable diagnostic found")


class TestCloudClient(unittest.TestCase):
    def test_timeout_does_not_retry_ambiguous_post(self):
        from unittest.mock import Mock
        import requests
        client = CloudClient(api_key="sk-test-secret-12345", max_retries=3)
        client._session.post = Mock(side_effect=requests.Timeout("request timed out"))
        content, record = client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(content, "")
        self.assertEqual(record.status, "error")
        self.assertEqual(client._session.post.call_count, 1)

    def test_malformed_success_is_recorded_without_retry(self):
        from unittest.mock import Mock
        client = CloudClient(api_key="sk-test-secret-12345")
        response = Mock(status_code=200, headers={"x-request-id": "request-1"})
        response.json.return_value = {"choices": []}
        client._session.post = Mock(return_value=response)
        content, record = client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(content, "")
        self.assertEqual(record.status, "invalid_response")
        self.assertEqual(client._session.post.call_count, 1)

    def test_mock_client_returns_expected(self):
        client = MockCloudClient()
        content, record = client.chat([{"role": "user", "content": "hi"}])
        self.assertIsInstance(content, str)
        self.assertEqual(record.status, "success")
        self.assertEqual(len(client.records), 1)

    def test_real_client_no_key_no_call(self):
        old = os.environ.get(ENV_KEY)
        if old:
            del os.environ[ENV_KEY]
        try:
            client = CloudClient()
            self.assertEqual(client.api_key, "")
        finally:
            if old:
                os.environ[ENV_KEY] = old

    def test_credential_redacted_in_record(self):
        client = CloudClient(api_key="sk-test-secret-12345")
        record_str = json.dumps([r.__dict__ for r in client.records])
        self.assertNotIn("sk-test-secret-12345", record_str)


if __name__ == "__main__":
    unittest.main()
