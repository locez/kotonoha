"""Executable packaging and release-metadata contracts."""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
DEBIAN_DIR = PROJECT_ROOT / "packaging" / "debian"
FEDORA_SPEC = PROJECT_ROOT / "packaging" / "fedora" / "kotonoha.spec"
PACKAGE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "package.yml"
RPM_SPEC_SED_PATTERN = re.compile(
    r'^\s*(sed -i -E "[^"]+" packaging/fedora/kotonoha\.spec)$',
    re.MULTILINE,
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_rpm_workflow_updates_spec_version_and_changelog(tmp_path: Path) -> None:
    """The release workflow's sed transform rewrites RPM Version and changelog cleanly."""
    workflow = PACKAGE_WORKFLOW.read_text(encoding="utf-8")
    sed_commands = RPM_SPEC_SED_PATTERN.findall(workflow)
    assert sed_commands

    spec_path = tmp_path / "packaging" / "fedora" / "kotonoha.spec"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_bytes(FEDORA_SPEC.read_bytes())

    environment = os.environ.copy()
    environment["VERSION"] = "2.3.4"
    for command in sed_commands:
        subprocess.run(("bash", "-c", command), cwd=tmp_path, env=environment, check=True)

    transformed = spec_path.read_text(encoding="utf-8")
    assert "Version:        2.3.4" in transformed
    assert re.search(r"^\* .* - 2\.3\.4-1$", transformed, re.MULTILINE)
    assert "Source0:        %{name}-%{version}.tar.gz" in transformed


def test_debian_rules_leave_the_source_tree_unchanged_on_repeated_configure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running debian/rules configure and clean repeatedly does not mutate pyproject.toml."""
    source_tree = tmp_path / "source"
    debian_dir = source_tree / "debian"
    fake_bin = tmp_path / "bin"
    debian_dir.mkdir(parents=True)
    fake_bin.mkdir()

    original_pyproject = (PROJECT_ROOT / "pyproject.toml").read_bytes()
    pyproject_path = source_tree / "pyproject.toml"
    pyproject_path.write_bytes(original_pyproject)
    rules_path = debian_dir / "rules"
    rules_path.write_bytes((DEBIAN_DIR / "rules").read_bytes())
    rules_path.chmod(0o755)
    _write_executable(fake_bin / "dh_auto_configure", "#!/bin/sh\nprintf 'configure\\n' >> debhelper.log\n")
    _write_executable(fake_bin / "dh_clean", "#!/bin/sh\nprintf 'clean\\n' >> debhelper.log\n")
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    backup_path = debian_dir / ".kotonoha-pyproject.toml.orig"
    configure_command = ("make", "-f", "debian/rules", "override_dh_auto_configure")
    subprocess.run(configure_command, cwd=source_tree, check=True)
    assert not backup_path.exists()
    assert pyproject_path.read_bytes() == original_pyproject

    subprocess.run(configure_command, cwd=source_tree, check=True)
    assert not backup_path.exists()
    assert pyproject_path.read_bytes() == original_pyproject

    clean_command = ("make", "-f", "debian/rules", "override_dh_clean")
    subprocess.run(clean_command, cwd=source_tree, check=True)
    assert pyproject_path.read_bytes() == original_pyproject
    assert not backup_path.exists()

    subprocess.run(clean_command, cwd=source_tree, check=True)
    assert pyproject_path.read_bytes() == original_pyproject
    assert (source_tree / "debhelper.log").read_text(encoding="utf-8").splitlines() == [
        "configure",
        "configure",
        "clean",
        "clean",
    ]


def test_the_release_check_imports_a_module_that_exists() -> None:
    """Smoke imports in the release workflow resolve to real package modules."""
    workflow = PACKAGE_WORKFLOW.read_text(encoding="utf-8")
    for module in set(re.findall(r"from (kotonoha[\w.]*) import", workflow)):
        importlib.import_module(module)


def test_every_declared_licence_has_its_text_packaged() -> None:
    """Every SPDX licence declared in pyproject.toml has a matching packaged licence file."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    declared = {part.strip() for part in project["license"].split(" AND ")}
    patterns = project["license-files"]

    packaged = {
        path.name
        for pattern in patterns
        for path in PROJECT_ROOT.glob(pattern)
    }

    assert "MIT" in declared and "LICENSE" in packaged
    for licence in declared - {"MIT"}:
        assert any(licence in name for name in packaged), (
            f"{licence} is declared but its text is not packaged: {sorted(packaged)}"
        )
