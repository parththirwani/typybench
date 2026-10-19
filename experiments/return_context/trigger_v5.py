"""Choose a free static answer when the untyped target has no return path.

The static answer is the Python runtime value on normal completion. It is a
prediction of the reference annotation, which can still differ (for example,
if an author annotated a function that always raises as NoReturn).
"""

from .explore_static_types import source_features
from .trigger_v3 import choose_arm


NO_RETURN_MARKER = "No explicit return or yield; implicit return None."


def choose_action(case: dict) -> str:
    features = source_features(case)
    if (NO_RETURN_MARKER in case["return_memory"] and
            features["category"] == "implicit_none" and
            features["exceptions"] == 0):
        return "static:None"
    if (features["predicted"] and features["final_return"] and
            features["yields"] == 0 and
            features["category"] in {"literal", "fstring", "builtin_call",
                                     "constructor", "annassign", "literal_assign"}):
        return f"static:{features['predicted']}"
    return choose_arm(case)
