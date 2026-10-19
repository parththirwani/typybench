import os
import tempfile

_TYPELESS_CROSS_FILE = {
    "src/mylib/__init__.py": "",
    "src/mylib/models.py": """
class User:
    def __init__(self, name, age):
        self.name = name
        self.age = age

def make_user(name, age):
    return User(name, age)
""",
    "src/app.py": """
from mylib.models import User, make_user

def run() -> None:
    u: User = make_user(42, "old")
""",
}

_CORRECTION_TYPED_FIXTURE = {
    "src/mylib/__init__.py": "",
    "src/mylib/models.py": """
def greet(name: str) -> str:
    return f"Hello, {name}"
""",
    "src/app.py": """
from mylib.models import greet

def run() -> None:
    x: int = greet(42)
""",
}


def create_typeless_cross_file_fixture(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_typeless_cross")
    for relpath, content in _TYPELESS_CROSS_FILE.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest


def create_correction_typed_fixture(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_correction_typed")
    for relpath, content in _CORRECTION_TYPED_FIXTURE.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest