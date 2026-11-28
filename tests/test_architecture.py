import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "kotonoha"


def _python_modules():
    return tuple(path for path in SOURCE_ROOT.rglob("*.py") if path.is_file())


def _imports(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))


def _module_names(path: Path) -> set[str]:
    """Return absolute and relative import spellings used by one module."""
    names: set[str] = set()
    for node in _imports(path):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif node.module is not None:
            names.add("." * node.level + node.module)
    return names


def _module_name(path: Path) -> str:
    """Return the package module name represented by a source path."""
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("kotonoha", *parts))


def _absolute_imports(path: Path) -> set[str]:
    """Resolve AST import nodes enough to enforce package dependency direction."""
    module_parts = _module_name(path).split(".")
    package_parts = module_parts[:-1]
    resolved: set[str] = set()
    for node in _imports(path):
        if isinstance(node, ast.Import):
            resolved.update(alias.name for alias in node.names)
            continue
        if node.level == 0:
            base = [] if node.module is None else node.module.split(".")
        else:
            root_length = len(package_parts) - (node.level - 1)
            if root_length < 0:
                continue
            base = package_parts[:root_length]
            if node.module is not None:
                base.extend(node.module.split("."))
        if node.module is None:
            resolved.update(".".join((*base, alias.name)) for alias in node.names)
        else:
            resolved.add(".".join(base))
    return resolved


#: Composition roots are the only modules outside the platform package allowed
#: to name the concrete bridge. Overlay defaults are built by the platform factory.
_BRIDGE_NAMERS = {"application_controller.py", "composition.py"}

#: The concrete native bridge, however it is spelled at the import site.
_BRIDGE_SYMBOLS = {"LayerShellController"}


def test_ui_does_not_reach_the_native_bridge():
    """No UI module may import the native bridge, by module path or by re-export.

    Rejecting `platform.native` alone left the boundary open: `platform/__init__.py`
    re-exports LayerShellController, so `from .platform import LayerShellController`
    hands a UI module the concrete bridge while the old check passed. The only
    remaining call sites are the composition roots listed above.
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


def test_lyric_grammar_modules_know_nothing_about_matching():
    # The grammar has to serve every ingest path — MPRIS, a browser bridge, a player
    # plugin — so it must not depend on how a candidate is scored. When the two lived
    # in one module a rule could only be reached through the matcher, and the three
    # bilibili rules ended up stranded in the MPRIS parser for exactly that reason.
    grammar_paths = (
        SOURCE_ROOT / "lyrics" / "title_grammar.py",
        SOURCE_ROOT / "lyrics" / "artist_grammar.py",
        SOURCE_ROOT / "lyrics" / "title_queries.py",
        SOURCE_ROOT / "lyrics" / "player_title_grammar.py",
    )

    for path in grammar_paths:
        for node in _imports(path):
            module = getattr(node, "module", "") or ""
            assert "match" not in module.split("."), f"{path.name} imports {module}"
            for alias in node.names:
                assert "match" not in alias.name.split("."), f"{path.name} imports {alias.name}"


def test_the_matcher_holds_no_platform_grammar():
    # Every regex that describes how a publisher decorates a title belongs to the
    # grammar module; match.py should only be scoring.
    tree = ast.parse((SOURCE_ROOT / "lyrics" / "match.py").read_text(encoding="utf-8"))
    regex_compiles = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
    ]
    assert not regex_compiles, "a grammar rule has drifted back into the matcher"


def test_lyrics_contract_modules_are_toolkit_and_transport_neutral():
    """Domain/source contracts must not acquire Qt, aiohttp, or display imports."""
    contract_paths = (
        SOURCE_ROOT / "lyrics" / "models.py",
        SOURCE_ROOT / "app" / "source_contracts.py",
        SOURCE_ROOT / "lyrics" / "sources.py",
        SOURCE_ROOT / "lyrics" / "workflow.py",
        SOURCE_ROOT / "lyrics" / "live_source.py",
        SOURCE_ROOT / "playback" / "models.py",
    )
    forbidden = ("PyQt6", "aiohttp", "display", "QtDisplayPublisher")
    violations = [
        f"{path.name}: {module}"
        for path in contract_paths
        for module in _module_names(path)
        if any(part in module for part in forbidden)
    ]
    assert not violations, "feature contracts must not depend on UI or concrete transports: " + ", ".join(violations)


def test_display_publisher_has_one_application_owner():
    """Provider and receiver adapters may not construct their own Qt publisher."""
    owners: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "QtDisplayPublisher":
                owners.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert owners == ["app/composition.py"]


def test_provider_boundaries_do_not_retain_legacy_display_or_gate_contracts():
    """Player adapters publish through application ports and source ownership."""
    forbidden = {"LyricsState", "LyricsSnapshot", "SourceGate", "QtDisplayPublisher"}
    violations: list[str] = []
    for name in ("mpris.py", "mpris_lyrics.py", "cider_api.py"):
        path = SOURCE_ROOT / "providers" / name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and node.id in forbidden:
                violations.append(f"{name}: {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                violations.append(f"{name}: {node.attr}")
    assert not violations, "provider boundaries retain legacy contracts: " + ", ".join(violations)


def test_provider_adapters_depend_on_feature_ports_not_concrete_coordinators():
    """Adapters must consume narrow application contracts at their boundaries."""
    paths = (*tuple((SOURCE_ROOT / "providers").glob("*.py")), SOURCE_ROOT / "receiver.py")
    forbidden = {
        "kotonoha.app.source_gate",
        "kotonoha.app.display_coordinator",
    }
    violations = [
        f"{path.relative_to(SOURCE_ROOT)} -> {imported}"
        for path in paths
        for imported in _absolute_imports(path)
        if imported in forbidden
    ]
    assert not violations, "adapters depend on concrete application owners: " + ", ".join(violations)


def test_application_workflow_is_toolkit_free_outside_the_composition_root():
    """Application orchestration depends on ports; Qt and process adapters stay in composition."""
    forbidden = ("PyQt6", "QProcess", "platform.restart")
    violations = [
        f"{path.relative_to(SOURCE_ROOT)} -> {module}"
        for path in (SOURCE_ROOT / "app").glob("*.py")
        if path.name != "composition.py"
        for module in _absolute_imports(path)
        if any(part in module for part in forbidden)
    ]
    assert not violations, "application workflow imports toolkit/process adapters: " + ", ".join(violations)


def test_cache_management_uses_a_narrow_cache_port():
    """Cache management must not acquire cache operations through the MPRIS bundle."""
    path = SOURCE_ROOT / "app" / "cache_management.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }

    assert "MprisPort" not in names
    assert "kotonoha.app.components" not in _absolute_imports(path)


def test_mpris_layers_do_not_forward_cache_management():
    """MPRIS owns playback resolution, while cache management owns cache CRUD."""
    forbidden = {
        "lookup",
        "lookup_manual",
        "search",
        "get",
        "upsert",
        "update",
        "delete",
        "delete_many",
        "clear",
        "count",
    }
    paths = (
        SOURCE_ROOT / "app" / "components.py",
        SOURCE_ROOT / "providers" / "mpris.py",
        SOURCE_ROOT / "providers" / "mpris_lyrics.py",
        SOURCE_ROOT / "providers" / "mpris_resolution.py",
        SOURCE_ROOT / "lyrics" / "workflow.py",
    )
    violations = [
        f"{path.relative_to(SOURCE_ROOT)}: {node.name}"
        for path in paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden
    ]
    assert not violations, "MPRIS layers must not expose cache CRUD: " + ", ".join(violations)


def test_lyrics_feature_does_not_depend_on_application_or_presentation_layers():
    """Lyrics contracts and workflows remain usable without application wiring or Qt."""
    forbidden = ("kotonoha.app", "PyQt6", "aiohttp.web", "kotonoha.ui")
    violations = [
        f"{path.relative_to(SOURCE_ROOT)} -> {module}"
        for path in (SOURCE_ROOT / "lyrics").rglob("*.py")
        for module in _absolute_imports(path)
        if any(part in module for part in forbidden)
    ]
    assert not violations, "lyrics feature depends on outer layers: " + ", ".join(violations)


def test_display_package_is_free_of_toolkit_ui_and_persistence_dependencies():
    """Display policy and timing cannot depend on Qt or concrete persistence state."""
    forbidden_modules = ("PyQt6", "ui.overlay", "QtDisplayPublisher", "sqlite3")
    forbidden_names = {"LyricsState", "QtDisplayPublisher", "LyricsSnapshot"}
    violations: list[str] = []
    for path in (SOURCE_ROOT / "display").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _module_names(path):
            if any(part in module for part in forbidden_modules):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {node.attr}")
    assert not violations, "display policy depends on UI state: " + ", ".join(violations)


def test_concrete_runtime_graph_is_assembled_in_composition_only():
    """Concrete application services and providers have one construction owner."""
    concrete_names = {
        "AppController",
        "CiderApiProvider",
        "MprisProvider",
        "RuntimeConfigApplier",
        "QtDisplayPublisher",
        "QProcessRestartLauncher",
    }
    owners: dict[str, list[str]] = {name: [] for name in concrete_names}
    for path in _python_modules():
        if path == SOURCE_ROOT / "app" / "composition.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in concrete_names:
                owners[node.func.id].append(path.relative_to(SOURCE_ROOT).as_posix())
    violations = [f"{name}: {paths}" for name, paths in owners.items() if paths]
    assert not violations, "concrete graph construction escaped composition.py: " + ", ".join(violations)


def test_runtime_config_policy_uses_ports_not_concrete_adapters():
    """Runtime policy stays independent from Qt, providers, and UI widgets."""
    path = SOURCE_ROOT / "app" / "services.py"
    forbidden = ("PyQt6", "providers", "ui", "tray", "source_gate", "display_coordinator", "strings")
    violations = [module for module in _absolute_imports(path) if any(part in module for part in forbidden)]
    assert not violations, "runtime config policy imports concrete adapters: " + ", ".join(violations)


def test_process_entrypoint_delegates_configuration_and_graph_assembly():
    """The process entrypoint does not load config or construct runtime services."""
    path = SOURCE_ROOT / "main.py"
    forbidden_names = {"ConfigStore", "ConfigService", "load_config"}
    names = {
        node.id
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name)
    }
    assert not names.intersection(forbidden_names)
    forbidden_modules = {"kotonoha.config.store", "kotonoha.app.config_service"}
    assert not _absolute_imports(path).intersection(forbidden_modules)


def test_component_boundary_dependencies_are_required():
    """Stateful boundaries may not silently create their collaborators."""
    required: dict[str, tuple[str, ...]] = {
        "providers/cider_api.py": ("client",),
        "providers/mpris.py": ("ownership", "resolver", "playback_adapter", "playback_session"),
        "providers/mpris_playback.py": ("session", "playback_adapter"),
        "app/display_coordinator.py": ("presenter", "timeline"),
        "lyrics/catalog.py": ("live_source", "local_source"),
        "lyrics/cache/__init__.py": ("worker",),
        "lyrics/sources.py": ("worker",),
        "lyrics/resolver.py": ("cache",),
    }
    violations: list[str] = []
    for relative, names in required.items():
        path = SOURCE_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constructor = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        defaults = dict(
            zip(
                (argument.arg for argument in constructor.args.kwonlyargs),
                constructor.args.kw_defaults,
                strict=True,
            )
        )
        for name in names:
            if name not in defaults or defaults[name] is not None:
                violations.append(f"{relative}: {name}")
    assert not violations, "provider dependencies have concrete fallbacks: " + ", ".join(violations)


def test_track_offset_identity_has_one_value_owner():
    """Structured timing-correction identities have one domain owner."""
    definitions: list[str] = []
    constructors: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "TrackOffsetKey":
                definitions.append(path.relative_to(SOURCE_ROOT).as_posix())
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "track_offset_key":
                constructors.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert definitions == ["display/offsets.py"]
    assert constructors == ["display/offsets.py"]


def test_timeline_engine_is_clock_only():
    """Timeline state must not import lyric policy or presentation modules."""
    path = SOURCE_ROOT / "display" / "timeline.py"
    forbidden = ("lyrics", "rules", "presentation", "PyQt6")
    violations = [module for module in _module_names(path) if any(part in module for part in forbidden)]
    assert not violations, "TimelineEngine must own clock state only: " + ", ".join(sorted(violations))


def test_display_engine_is_the_single_policy_owner():
    """The display policy class must have one concrete definition."""
    owners: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.ClassDef) and node.name == "DisplayEngine" for node in ast.walk(tree)):
            owners.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert owners == ["display/presentation.py"]


def test_overlay_consumes_display_progress_without_owning_display_policy():
    """The Qt renderer may paint progress but may not select or calculate it."""
    path = SOURCE_ROOT / "ui" / "overlay" / "window.py"
    forbidden_modules = ("display.karaoke", "display.rules", "display.presentation", "lyrics.select")
    imported = _module_names(path)
    assert not any(any(part in module for part in forbidden_modules) for module in imported), imported

    forbidden_names = {
        "active_word_index",
        "find_current_index",
        "in_interlude",
        "interlude_at",
        "interlude_text",
        "line_fill_fraction",
        "line_progress",
        "word_fill_fraction",
        "word_fill_fractions",
    }
    names = {
        node.id
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name)
    }
    assert not names.intersection(forbidden_names)


def test_playback_application_boundary_does_not_expose_dbus_dynamic_values():
    """D-Bus variants must be normalized before reaching playback coordination."""
    path = SOURCE_ROOT / "providers" / "mpris_playback.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dynamic_names = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "Any"]
    assert not dynamic_names, "playback coordination must use typed property-change values"


def test_playback_domain_does_not_depend_on_player_adapters():
    """Neutral playback models cannot import a concrete provider package."""
    violations = []
    for path in (SOURCE_ROOT / "playback").rglob("*.py"):
        for imported in _absolute_imports(path):
            if imported == "kotonoha.providers" or imported.startswith("kotonoha.providers."):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {imported}")
    assert not violations, "playback domain depends on provider adapters: " + ", ".join(violations)


def test_application_code_does_not_swallow_unknown_failures():
    """Broad exception handlers must not become an application control path."""
    violations: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not isinstance(node.type, ast.Name) or node.type.id not in {"Exception", "BaseException"}:
                continue
            relative = path.relative_to(SOURCE_ROOT).as_posix()
            # The composition root has one deliberate cleanup-only catch around
            # pre-controller construction. It must clean every worker and then
            # re-raise the original failure; broad catches remain forbidden in
            # normal application control flow.
            if relative == "app/composition.py" and any(
                isinstance(child, ast.Raise) and child.exc is None for child in ast.walk(node)
            ):
                continue
            violations.append(relative)
    assert not violations, "catch expected boundary failures explicitly: " + ", ".join(violations)
