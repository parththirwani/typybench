import os
import tempfile


_CROSS_FILE_FIXTURE = {
    "src/mylib/__init__.py": "",
    "src/mylib/models.py": """
from __future__ import annotations

class User:
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

def make_config(name: str, timeout: int = 30) -> dict:
    return {"name": name, "timeout": timeout}
""",
    "src/app.py": """
from __future__ import annotations

from mylib.models import make_config

def run() -> None:
    cfg = make_config(42, "short")
""",
}


def create_cross_file_fixture(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_cross_file_fixture")
    for relpath, content in _CROSS_FILE_FIXTURE.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest


_FIXTURE_REPO = {
    "src/mylib/__init__.py": "",
    "src/mylib/models.py": """
from __future__ import annotations

class User:
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

def create_default_user() -> User:
    return User(name="guest", age=0)

class Repository:
    def __init__(self, items: list[str]) -> None:
        self.items = items

    def add(self, item: str) -> None:
        self.items.append(item)
""",
    "src/mylib/utils.py": """
from __future__ import annotations

def format_greeting(name: str) -> str:
    return f"Hello, {name}"

def parse_count(raw: str) -> int:
    return int(raw.strip())
""",
    "src/app.py": """
from __future__ import annotations

from mylib.models import User, Repository
from mylib.utils import format_greeting, parse_count

def main() -> None:
    u = User("Alice", "thirty")
    r = Repository([1, 2, 3])
    msg = format_greeting(42)
    n = parse_count("7")
""",
}


def create_fixture_repo(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_fixture_repo")
    for relpath, content in _FIXTURE_REPO.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest


def create_fixture_repo_without_types(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_fixture_without_types")
    content_without = {
        "src/app.py": """
from __future__ import annotations

from mylib.models import User, Repository
from mylib.utils import format_greeting, parse_count

def main():
    u = User("Alice", "thirty")
    r = Repository([1, 2, 3])
    msg = format_greeting(42)
    n = parse_count("7")
""",
        "src/mylib/__init__.py": "",
        "src/mylib/models.py": """
from __future__ import annotations

class User:
    def __init__(self, name, age):
        self.name = name
        self.age = age

def create_default_user():
    return User(name="guest", age=0)

class Repository:
    def __init__(self, items):
        self.items = items

    def add(self, item):
        self.items.append(item)
""",
        "src/mylib/utils.py": """
from __future__ import annotations

def format_greeting(name):
    return f"Hello, {name}"

def parse_count(raw):
    return int(raw.strip())
""",
    }
    for relpath, content in content_without.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest