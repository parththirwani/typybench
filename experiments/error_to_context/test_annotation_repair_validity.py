import json
import unittest

from .correction import _apply_valid_edit


class TargetAnnotationTests(unittest.TestCase):
    source = "def use(item: str, flag: bool):\n    return item\n"

    def patch(self, replacement):
        return _apply_valid_edit(
            self.source, 1,
            json.dumps({"line": 1, "replacement": replacement}),
            allowed_line=1,
            target_function="use",
            target_parameter="item",
        )

    def test_target_retype_passes(self):
        _, valid, error = self.patch("def use(item: str | None, flag: bool):")
        self.assertTrue(valid, error)

    def test_target_annotation_removal_is_invalid(self):
        _, valid, error = self.patch("def use(item, flag: bool):")
        self.assertFalse(valid)
        self.assertIn("removes", error)

    def test_other_parameter_edit_does_not_count(self):
        _, valid, error = self.patch("def use(item: str, flag: int):")
        self.assertFalse(valid)
        self.assertIn("target parameter", error)

    def test_executable_default_change_still_rejected(self):
        source = "def use(item: str = 'x'):\n    return item\n"
        response = json.dumps({"line": 1, "replacement": "def use(item: int = 'y'):"})
        _, valid, error = _apply_valid_edit(
            source, 1, response, allowed_line=1,
            target_function="use", target_parameter="item")
        self.assertFalse(valid)
        self.assertIn("executable", error)

    def test_malformed_line_type_is_rejected(self):
        _, valid, error = _apply_valid_edit(
            self.source, 1,
            '{"line": "not-a-number", "replacement": "def use(item: int, flag: bool):"}',
            allowed_line=1, target_function="use", target_parameter="item")
        self.assertFalse(valid)
        self.assertIn("parse JSON patch", error)


if __name__ == "__main__":
    unittest.main()
