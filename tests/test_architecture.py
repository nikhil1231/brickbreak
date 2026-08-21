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


# A family is a *leaf*. The lab tests beliefs about the market; it must not be
# shaped by any one of them. `src/interface` is exempt on purpose — the CLI and
# the screener API are exactly where a family gets bound to a command.
LAB_PACKAGES = ("alpha_eval", "research_data", "persistence", "runner",
                "discretionary", "core")


def test_the_lab_never_imports_a_hypothesis_family():
    """The dependency runs one way: families import the lab, never the reverse.

    Before 2026-08-22 the opening-window family owned thirteen top-level CLI
    commands and the dashboard's landing view, which made one belief about the
    market look like the architecture. Nothing below `src/interface` may reach
    into `src/research` again.
    """
    violations = []
    for package in LAB_PACKAGES:
        root = SRC / package
        if not root.exists():
            continue
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Import):
                    targets.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    # Relative imports cannot escape the package they sit in
                    # without going through `src`, which `node.module` records.
                    targets.append(node.module or "")
                for target in targets:
                    if target == "research" or target.startswith(
                            ("research.", "src.research", "..research",
                             "...research")):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno} -> {target}")
    assert violations == [], (
        "the lab imports a hypothesis family: " + ", ".join(violations))


# A dynamic import is still an import. `generators.contraction_breakout` binds
# the opening-window screen as one candidate generator among several, by name
# and inside the function, so a definition has to ask for it. That is a
# deliberate exception and it is listed here rather than being invisible to the
# static check above.
ALLOWED_DYNAMIC_FAMILY_IMPORTS = {
    ("discretionary/generators.py",
     "src.research.families.opening_window.screener"),
}


def test_dynamic_imports_of_a_family_are_declared():
    """importlib.import_module with a string literal bypasses the check above.

    Without this the previous test reads as "the lab never touches a family"
    while the lab touches a family, which is worse than no test at all.
    """
    undeclared = []
    for package in LAB_PACKAGES:
        root = SRC / package
        if not root.exists():
            continue
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(
                    fn, "id", "")
                if name not in ("import_module", "__import__"):
                    continue
                for arg in node.args:
                    if not (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)):
                        continue
                    if not arg.value.startswith("src.research"):
                        continue
                    key = (str(path.relative_to(SRC)), arg.value)
                    if key not in ALLOWED_DYNAMIC_FAMILY_IMPORTS:
                        undeclared.append(f"{key[0]} -> {key[1]}")
    assert undeclared == [], (
        "undeclared dynamic import of a hypothesis family: "
        + ", ".join(undeclared)
        + ". Add it to ALLOWED_DYNAMIC_FAMILY_IMPORTS with a reason, or "
          "remove the coupling.")


def test_families_live_under_research_families():
    """No family may sit at the root of `src/research` again."""
    stray = {path.name for path in (SRC / "research").glob("*.py")
             if path.name != "__init__.py"}
    assert stray == set(), (
        f"hypothesis-family modules at src/research/: {sorted(stray)}. "
        f"They belong in src/research/families/.")


def _resolve_relative(path, node):
    """The absolute module a relative ImportFrom names, or None if absolute."""
    if not node.level:
        return None
    parts = path.relative_to(SRC).parts
    package = ("src",) + (parts[:-1] if path.name != "__init__.py"
                          else parts[:-1])
    if node.level > len(package):
        return "<escapes src>"
    base = package[:len(package) - node.level + 1]
    return ".".join(base + tuple((node.module or "").split(".") if node.module
                                 else ()))


def test_every_relative_import_resolves_to_something_that_exists():
    """A relative import at the wrong depth is silent until the line executes.

    Moving `src/research/opening_window` down one level in 2026-08-22 turned
    every `from ...research_data import x` into `src.research.research_data`.
    Module-level ones broke immediately; the four inside function bodies did
    not, and one survived the whole suite until a single test happened to walk
    that branch. This check is static, so a function-local import is no safer
    than a top-level one.
    """
    violations = []
    for path in _python_files(SRC):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            target = _resolve_relative(path, node)
            if target == "<escapes src>":
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} escapes src/")
                continue
            rel = Path(*target.split(".")[1:])       # drop the leading "src"
            if (SRC / rel).is_dir() or (SRC / rel).with_suffix(".py").exists():
                continue
            # `from .x import y` where y is the module and x the package.
            if (SRC / rel).parent.is_dir():
                continue
            violations.append(
                f"{path.relative_to(ROOT)}:{node.lineno} -> {target} (no such module)")
    assert violations == [], (
        "relative imports that do not resolve: " + "; ".join(violations))
