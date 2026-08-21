"""Package-layout and market-data boundary regression tests."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_src_root_contains_only_public_entrypoints():
    assert {path.name for path in SRC.glob("*.py")} == {"__init__.py", "cli.py"}


def test_market_data_reads_live_inside_research_data():
    """A parquet/CSV read outside the data package is a new access door."""
    violations = []
    for path in _python_files(SRC):
        if (SRC / "research_data") in path.parents:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"read_parquet", "read_csv"}:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == [], "market-data reads outside research_data: " + ", ".join(violations)


def test_research_data_never_imports_hypothesis_code():
    """The data layer may not depend on any hypothesis-family implementation."""
    violations = []
    data_root = SRC / "research_data"
    for path in _python_files(data_root):
        module_parts = list(path.with_suffix("").relative_to(ROOT).parts)
        if module_parts[-1] == "__init__":
            module_parts.pop()
        package = module_parts if path.name == "__init__.py" else module_parts[:-1]
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    keep = len(package) - node.level + 1
                    base = package[:keep]
                    target = ".".join(base + ((node.module or "").split(".") if node.module else []))
                else:
                    target = node.module or ""
                targets.append(target)
            for target in targets:
                if target == "src.research" or target.startswith("src.research."):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {target}")
    assert violations == [], "research_data imports hypothesis code: " + ", ".join(violations)
