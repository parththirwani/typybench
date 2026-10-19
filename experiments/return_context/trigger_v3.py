"""Frozen union of return-assignment and explicit-type source signals."""

import re


CONSTRUCTOR_RETURN = re.compile(r"return line \d+: [A-Z][A-Za-z_0-9]*\(")


def choose_arm(case: dict) -> str:
    memory = case["return_memory"]
    return "B" if (
        "assignment line" in memory or "yield line" in memory
        or "cast(" in memory or CONSTRUCTOR_RETURN.search(memory) is not None
    ) else "A"
