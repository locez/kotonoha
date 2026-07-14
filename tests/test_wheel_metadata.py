from __future__ import annotations

import importlib
import sys
from email.parser import Parser
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

sys.path.insert(0, str(Path(__file__).parents[1]))


def load_patcher():
    module = importlib.import_module("scripts.patch_linux_wheel_metadata")
    return module.patch_linux_wheel_metadata


def create_unpacked_wheel(
    root: Path,
    *,
    pyqt_requirement: str | None = "PyQt6",
    root_is_purelib: str = "true",
) -> Path:
    dist_info = root / "kotonoha-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "WHEEL").write_text(
        f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: {root_is_purelib}\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    requirements = ["Requires-Dist: qasync"]
    if pyqt_requirement is not None:
        requirements.insert(0, f"Requires-Dist: {pyqt_requirement}")
    (dist_info / "METADATA").write_text(
        "\n".join(("Metadata-Version: 2.4", "Name: kotonoha", "Version: 0.1.0", *requirements, "")),
        encoding="utf-8",
    )
    return dist_info


def test_patch_linux_wheel_metadata_pins_pyqt_to_qt_minor(tmp_path: Path) -> None:
    dist_info = create_unpacked_wheel(tmp_path)

    load_patcher()(tmp_path, "6.10.2")

    wheel = Parser().parsestr((dist_info / "WHEEL").read_text(encoding="utf-8"))
    metadata = Parser().parsestr((dist_info / "METADATA").read_text(encoding="utf-8"))
    assert wheel.get_all("Root-Is-Purelib") == ["false"]
    assert metadata.get_all("Requires-Dist") == [
        "PyQt6<6.11,>=6.10",
        "qasync",
        "PyQt6-Qt6<6.11,>=6.10",
    ]


def test_patch_linux_wheel_metadata_accepts_an_already_non_pure_wheel(tmp_path: Path) -> None:
    dist_info = create_unpacked_wheel(tmp_path, root_is_purelib="false")

    load_patcher()(tmp_path, "6.10.2")

    wheel = Parser().parsestr((dist_info / "WHEEL").read_text(encoding="utf-8"))
    assert wheel.get_all("Root-Is-Purelib") == ["false"]


@pytest.mark.parametrize("version", ("6.10", "6.10.x", "6.10.2.1", "v6.10.2", ""))
def test_patch_linux_wheel_metadata_rejects_invalid_qt_version(tmp_path: Path, version: str) -> None:
    create_unpacked_wheel(tmp_path)

    with pytest.raises(ValueError, match="Qt version"):
        load_patcher()(tmp_path, version)


def test_patch_linux_wheel_metadata_requires_one_dist_info_directory(tmp_path: Path) -> None:
    create_unpacked_wheel(tmp_path / "first")
    create_unpacked_wheel(tmp_path / "second")

    with pytest.raises(ValueError, match="exactly one"):
        load_patcher()(tmp_path, "6.10.2")


def test_patch_linux_wheel_metadata_requires_pyqt_dependency(tmp_path: Path) -> None:
    create_unpacked_wheel(tmp_path, pyqt_requirement=None)

    with pytest.raises(ValueError, match="PyQt6 requirement"):
        load_patcher()(tmp_path, "6.10.2")


def test_patch_linux_wheel_metadata_preserves_qualified_pyqt_dependency(tmp_path: Path) -> None:
    dist_info = create_unpacked_wheel(
        tmp_path,
        pyqt_requirement='PyQt6[alpha,beta]>=6.7; python_version >= "3.10"',
    )

    load_patcher()(tmp_path, "6.10.2")

    metadata = Parser().parsestr((dist_info / "METADATA").read_text(encoding="utf-8"))
    requirements = [Requirement(value) for value in metadata.get_all("Requires-Dist", [])]
    by_name = {canonicalize_name(requirement.name): requirement for requirement in requirements}
    pyqt = by_name[canonicalize_name("pyqt6")]
    qt_runtime = by_name[canonicalize_name("pyqt6-qt6")]
    assert {str(specifier) for specifier in pyqt.specifier} == {">=6.7", ">=6.10", "<6.11"}
    assert {str(specifier) for specifier in qt_runtime.specifier} == {">=6.10", "<6.11"}
    assert pyqt.extras == {"alpha", "beta"}
    assert str(pyqt.marker) == 'python_version >= "3.10"'
    assert str(qt_runtime.marker) == 'python_version >= "3.10"'


def test_patch_linux_wheel_metadata_rejects_direct_url_pyqt_dependency(tmp_path: Path) -> None:
    create_unpacked_wheel(tmp_path, pyqt_requirement="PyQt6 @ https://example.invalid/PyQt6.whl")

    with pytest.raises(ValueError, match="direct URL"):
        load_patcher()(tmp_path, "6.10.2")
