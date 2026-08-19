import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "kotonoha"


def _python_modules():
    return tuple(path for path in SOURCE_ROOT.rglob("*.py") if path.is_file())


def _imports(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))


#: Modules outside the platform package that may still name the concrete bridge.
#: controller.py is the composition root and is meant to; overlay.py builds its own
#: default when none is passed, which is the one place the contract does not yet
#: reach and is recorded here rather than left to pass unnoticed.
_BRIDGE_NAMERS = {"controller.py", "overlay.py"}

#: The concrete native bridge, however it is spelled at the import site.
_BRIDGE_SYMBOLS = {"LayerShellController"}


def test_ui_does_not_reach_the_native_bridge():
    """No UI module may import the native bridge, by module path or by re-export.

    Rejecting `platform.native` alone left the boundary open: `platform/__init__.py`
    re-exports LayerShellController, so `from .platform import LayerShellController`
    hands a UI module the concrete bridge while the old check passed. The remaining
    two call sites are listed above, so this test says what is actually held.
    """
    violations = []
    for path in _python_modules():
        if "platform" in path.relative_to(SOURCE_ROOT).parts:
            continue
        for node in _imports(path):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("platform.native"):
                violations.append(f"{path.name}: platform.native")
            if isinstance(node, ast.Import) and any(
                alias.name == "kotonoha.platform.native" or alias.name.endswith(".platform.native")
                for alias in node.names
            ):
                violations.append(f"{path.name}: platform.native")
            if isinstance(node, ast.Import) and any(alias.name == "ctypes" for alias in node.names):
                violations.append(f"{path.name}: ctypes")
            if isinstance(node, ast.ImportFrom) and node.module == "ctypes":
                violations.append(f"{path.name}: ctypes")
            if (
                isinstance(node, ast.ImportFrom)
                and path.name not in _BRIDGE_NAMERS
                and any(alias.name in _BRIDGE_SYMBOLS for alias in node.names)
            ):
                violations.append(f"{path.name}: {node.names[0].name} through the package re-export")
    assert not violations, (
        "UI modules must depend on the platform contract, not the native bridge: " + ", ".join(violations)
    )


def test_overlay_contracts_is_toolkit_free():
    path = SOURCE_ROOT / "platform" / "overlay_contracts.py"
    assert all(
        not (
            isinstance(node, ast.Import)
            and any(alias.name == "PyQt6" or alias.name.startswith("PyQt6.") for alias in node.names)
            or isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "PyQt6" or node.module.startswith("PyQt6."))
        )
        for node in _imports(path)
    )


def test_desktop_environment_has_one_reader():
    """Only the platform probe names XDG_CURRENT_DESKTOP.

    Read from the parsed module rather than from its text: the previous check
    counted any file whose source contained the string, so a mention in a comment
    or a docstring counted as a reader and a formatting change could have hidden a
    real one. A key assembled at runtime is beyond any static check, and this test
    does not claim to catch that.
    """
    readers = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        if any(
            isinstance(node, ast.Constant) and node.value == "XDG_CURRENT_DESKTOP" and node not in docstrings
            for node in ast.walk(tree)
        ):
            readers.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert readers == ["platform/detect.py"]


def test_the_title_grammar_knows_nothing_about_matching():
    # The grammar has to serve every ingest path — MPRIS, a browser bridge, a player
    # plugin — so it must not depend on how a candidate is scored. When the two lived
    # in one module a rule could only be reached through the matcher, and the three
    # bilibili rules ended up stranded in the MPRIS parser for exactly that reason.
    titles = SOURCE_ROOT / "lyrics" / "titles.py"

    for node in _imports(titles):
        module = getattr(node, "module", "") or ""
        assert "match" not in module.split("."), f"titles.py imports {module}"
        for alias in node.names:
            assert "match" not in alias.name.split("."), f"titles.py imports {alias.name}"


def test_the_matcher_holds_no_platform_grammar():
    # Every regex that describes how a publisher decorates a title belongs to the
    # grammar module; match.py should only be scoring.
    match_source = (SOURCE_ROOT / "lyrics" / "match.py").read_text(encoding="utf-8")

    assert "re.compile" not in match_source, "a grammar rule has drifted back into the matcher"
