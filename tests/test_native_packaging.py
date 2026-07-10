from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib  # ty: ignore[unresolved-import]

PROJECT_ROOT = Path(__file__).parents[1]
DEBIAN_DIR = PROJECT_ROOT / "packaging" / "debian"
FEDORA_SPEC = PROJECT_ROOT / "packaging" / "fedora" / "kotonoha.spec"
NATIVE_PACKAGING_DOCS = (
    PROJECT_ROOT / "docs" / "superpowers" / "specs" / "2026-07-11-github-workflows-design.md",
    PROJECT_ROOT / "docs" / "superpowers" / "plans" / "2026-07-11-github-workflows.md",
)
SED_EXPRESSION_PATTERN = re.compile(r"^\s*sed -i '([^']+)' pyproject\.toml$", re.MULTILINE)


def read_packaging_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains(content: str, expected_values: tuple[str, ...]) -> None:
    for expected in expected_values:
        assert expected in content


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_debian_control_declares_package_metadata_and_dependencies() -> None:
    control = read_packaging_file(DEBIAN_DIR / "control")

    assert_contains(
        control,
        (
            "Source: kotonoha",
            "Section: sound",
            "Maintainer: Locez <locez@locez.com>",
            "Homepage: https://github.com/locez/kotonoha",
            "debhelper-compat (= 13)",
            "dh-python",
            "dh-sequence-python3",
            "pybuild-plugin-pyproject",
            "python3-all",
            "python3-hatchling",
            "python3-aiohttp",
            "python3-dbus-fast",
            "python3-pyqt6",
            "python3-qasync",
            "qt6-base-private-dev",
            "qt6-wayland-dev",
            "liblayershellqtinterface-dev",
            "libwayland-dev",
            "pkg-config",
            "g++",
            "desktop-file-utils",
            "Package: kotonoha",
            "${python3:Depends}",
            "${misc:Depends}",
        ),
    )


def test_debian_rules_builds_with_system_libraries_and_installs_icon() -> None:
    rules_path = DEBIAN_DIR / "rules"
    rules = read_packaging_file(rules_path)

    assert os.access(rules_path, os.X_OK)
    assert_contains(
        rules,
        (
            "export PYBUILD_NAME=kotonoha",
            "export USE_SYSTEM_LIBS=1",
            "dh $@ --buildsystem=pybuild",
            "override_dh_auto_configure:",
            "USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh",
            "dh_auto_configure --buildsystem=pybuild",
            "override_dh_auto_test:",
            "Tests run separately; skipping duplicate package-build tests.",
            "override_dh_install:",
            "dh_install",
            "src/kotonoha/assets/icon.png",
            "debian/kotonoha/usr/share/pixmaps/kotonoha.png",
        ),
    )


def test_debian_install_and_changelog_define_desktop_file_and_initial_release() -> None:
    install = read_packaging_file(DEBIAN_DIR / "install")
    changelog = read_packaging_file(DEBIAN_DIR / "changelog")

    assert "packaging/kotonoha.desktop usr/share/applications" in install
    assert_contains(
        changelog,
        (
            "kotonoha (0.1.0-1)",
            "Initial release.",
            "Locez <locez@locez.com>",
            "Sat, 11 Jul 2026",
        ),
    )


def test_fedora_spec_declares_metadata_and_dependencies() -> None:
    spec = read_packaging_file(FEDORA_SPEC)

    assert_contains(
        spec,
        (
            "Name:           kotonoha",
            "Version:        0.1.0",
            "Release:        1%{?dist}",
            "License:        MIT",
            "URL:            https://github.com/locez/kotonoha",
            "Source0:        %{name}-%{version}.tar.gz",
            "BuildRequires:  python3-devel",
            "BuildRequires:  python3-hatchling",
            "BuildRequires:  pyproject-rpm-macros",
            "BuildRequires:  gcc-c++",
            "BuildRequires:  qt6-qtbase-private-devel",
            "BuildRequires:  qt6-qtwayland-devel",
            "BuildRequires:  layer-shell-qt-devel",
            "BuildRequires:  wayland-devel",
            "BuildRequires:  desktop-file-utils",
            "Requires:       python3",
            "Requires:       python3-qt6",
            "Requires:       python3-aiohttp",
            "Requires:       python3-qasync",
            "Requires:       python3-dbus-fast",
            "Requires:       layer-shell-qt",
        ),
    )


def test_fedora_spec_builds_and_installs_native_desktop_assets() -> None:
    spec = read_packaging_file(FEDORA_SPEC)

    assert "PYTHONPATH" not in spec
    assert_contains(
        spec,
        (
            "%prep",
            "%autosetup",
            "%build",
            "USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh",
            "%pyproject_wheel",
            "%install",
            "%pyproject_install",
            "%pyproject_save_files kotonoha",
            "%{_datadir}/applications/kotonoha.desktop",
            "%{_datadir}/pixmaps/kotonoha.png",
            "%check",
            "desktop-file-validate %{buildroot}%{_datadir}/applications/kotonoha.desktop",
            "%{_bindir}/kotonoha",
        ),
    )


def test_fedora_spec_only_packages_existing_documentation() -> None:
    spec = read_packaging_file(FEDORA_SPEC)
    documentation_paths = (
        line.split(maxsplit=1)[1]
        for line in spec.splitlines()
        if line.startswith(("%doc ", "%license "))
    )

    for documentation_path in documentation_paths:
        assert (PROJECT_ROOT / documentation_path).is_file()


def apply_packaging_sed_expressions(tmp_path: Path, packaging_path: Path, *, makefile: bool) -> tuple[str, dict]:
    packaging = read_packaging_file(packaging_path)
    expressions = SED_EXPRESSION_PATTERN.findall(packaging)
    assert len(expressions) == 2

    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_bytes((PROJECT_ROOT / "pyproject.toml").read_bytes())
    for expression in expressions:
        if makefile:
            expression = expression.replace("$$", "$")
        subprocess.run(("sed", "-i", expression, str(pyproject_path)), check=True)

    transformed = pyproject_path.read_text(encoding="utf-8")
    return transformed, tomllib.loads(transformed)


@pytest.mark.parametrize(
    ("packaging_path", "makefile"),
    ((DEBIAN_DIR / "rules", True), (FEDORA_SPEC, False)),
)
def test_native_packaging_sed_expressions_remove_only_the_build_hook(
    tmp_path: Path,
    packaging_path: Path,
    makefile: bool,
) -> None:
    transformed, pyproject = apply_packaging_sed_expressions(tmp_path, packaging_path, makefile=makefile)

    assert pyproject["build-system"]["requires"] == ["hatchling"]
    assert "hatch-build-scripts" not in transformed
    hatch_build = pyproject["tool"]["hatch"]["build"]
    assert "hooks" not in hatch_build
    assert hatch_build["targets"]["wheel"]["force-include"] == {
        "src/kotonoha/libkoto-layer.so": "kotonoha/libkoto-layer.so"
    }


def test_native_packaging_docs_do_not_require_the_removed_build_hook() -> None:
    for documentation_path in NATIVE_PACKAGING_DOCS:
        documentation = read_packaging_file(documentation_path)
        assert re.search(r"pip install[^\n]*hatch-build-scripts", documentation) is None
        assert "PYTHONPATH" not in documentation


def test_debian_rules_restore_the_source_tree_after_repeated_configure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_tree = tmp_path / "source"
    debian_dir = source_tree / "debian"
    package_dir = source_tree / "src" / "kotonoha"
    fake_bin = tmp_path / "bin"
    debian_dir.mkdir(parents=True)
    package_dir.mkdir(parents=True)
    fake_bin.mkdir()

    original_pyproject = (PROJECT_ROOT / "pyproject.toml").read_bytes()
    pyproject_path = source_tree / "pyproject.toml"
    pyproject_path.write_bytes(original_pyproject)
    rules_path = debian_dir / "rules"
    rules_path.write_bytes((DEBIAN_DIR / "rules").read_bytes())
    rules_path.chmod(0o755)
    write_executable(package_dir / "build_bridge.sh", "#!/bin/bash\n: > src/kotonoha/libkoto-layer.so\n")
    write_executable(fake_bin / "dh_auto_configure", "#!/bin/sh\nprintf 'configure\\n' >> debhelper.log\n")
    write_executable(fake_bin / "dh_clean", "#!/bin/sh\nprintf 'clean\\n' >> debhelper.log\n")
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    backup_path = debian_dir / ".kotonoha-pyproject.toml.orig"
    configure_command = ("make", "-f", "debian/rules", "override_dh_auto_configure")
    subprocess.run(configure_command, cwd=source_tree, check=True)
    assert backup_path.is_file()
    assert backup_path.read_bytes() == original_pyproject
    assert pyproject_path.read_bytes() != original_pyproject
    assert "hatch-build-scripts" not in pyproject_path.read_text(encoding="utf-8")

    subprocess.run(configure_command, cwd=source_tree, check=True)
    assert backup_path.read_bytes() == original_pyproject
    assert pyproject_path.read_bytes() != original_pyproject
    assert (package_dir / "libkoto-layer.so").is_file()

    clean_command = ("make", "-f", "debian/rules", "override_dh_clean")
    subprocess.run(clean_command, cwd=source_tree, check=True)
    assert pyproject_path.read_bytes() == original_pyproject
    assert not backup_path.exists()
    assert not (package_dir / "libkoto-layer.so").exists()

    subprocess.run(clean_command, cwd=source_tree, check=True)
    assert pyproject_path.read_bytes() == original_pyproject
    assert (source_tree / "debhelper.log").read_text(encoding="utf-8").splitlines() == [
        "configure",
        "configure",
        "clean",
        "clean",
    ]
