import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_runtime_import_is_a_declared_dependency():
    """Docker and the hosted demo install without the dev group, so a module the server
    imports must not arrive only through pytest's dependencies."""
    declared = {d.split(">")[0].split("=")[0].split("[")[0].strip().lower()
                for d in tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]}
    dists = packages_distributions()
    missing = set()
    for path in (ROOT / "moderator").rglob("*.py"):
        if "bench" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                     else [])
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top == "moderator":
                    continue
                owners = {d.lower() for d in dists.get(top, [top])}
                if not owners & declared:
                    missing.add(f"{top} ({path.relative_to(ROOT)})")
    assert not missing, sorted(missing)
