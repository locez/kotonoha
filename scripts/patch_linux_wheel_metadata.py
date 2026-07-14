from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from email.message import Message
from email.parser import Parser
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

QT_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _metadata_path(unpacked_dir: Path, filename: str) -> Path:
    matches = sorted(
        path for path in unpacked_dir.rglob(filename) if path.is_file() and path.parent.name.endswith(".dist-info")
    )
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {filename} file, found {len(matches)}")
    return matches[0]


def _parse_requirement(requirement: str) -> Requirement:
    try:
        return Requirement(requirement)
    except InvalidRequirement as error:
        raise ValueError(f"invalid wheel requirement: {requirement!r}") from error


def _pin_pyqt_requirement(requirement: Requirement, qt_lower: str, qt_upper: str) -> tuple[str, str]:
    if requirement.url is not None:
        raise ValueError("PyQt6 must use a version requirement, not a direct URL")

    specifiers = ",".join(part for part in (str(requirement.specifier), f">={qt_lower}", f"<{qt_upper}") if part)
    combined_specifiers = SpecifierSet(specifiers)
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    marker = f"; {requirement.marker}" if requirement.marker is not None else ""
    pyqt = f"{requirement.name}{extras}{combined_specifiers}{marker}"
    qt_runtime = f"PyQt6-Qt6<{qt_upper},>={qt_lower}{marker}"
    return pyqt, qt_runtime


def _write_message(path: Path, message: Message) -> None:
    path.write_text(message.as_string(), encoding="utf-8")


def patch_linux_wheel_metadata(unpacked_dir: Path, qt_version: str) -> None:
    version_match = QT_VERSION_PATTERN.fullmatch(qt_version)
    if version_match is None:
        raise ValueError(f"invalid Qt version {qt_version!r}; expected X.Y.Z")

    qt_major = int(version_match.group(1))
    qt_minor = int(version_match.group(2))
    qt_lower = f"{qt_major}.{qt_minor}"
    qt_upper = f"{qt_major}.{qt_minor + 1}"

    wheel_path = _metadata_path(unpacked_dir, "WHEEL")
    wheel = Parser().parsestr(wheel_path.read_text(encoding="utf-8"))
    purelib = wheel.get_all("Root-Is-Purelib", [])
    if purelib == ["true"]:
        wheel.replace_header("Root-Is-Purelib", "false")
    elif purelib != ["false"]:
        raise ValueError("wheel must contain exactly one Root-Is-Purelib: true or false field")
    _write_message(wheel_path, wheel)

    metadata_path = _metadata_path(unpacked_dir, "METADATA")
    metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
    requirements = metadata.get_all("Requires-Dist", [])
    parsed_requirements = [_parse_requirement(requirement) for requirement in requirements]
    pyqt_indexes = [
        index
        for index, requirement in enumerate(parsed_requirements)
        if canonicalize_name(requirement.name) == "pyqt6"
    ]
    if len(pyqt_indexes) != 1:
        raise ValueError(f"expected exactly one PyQt6 requirement, found {len(pyqt_indexes)}")
    if any(canonicalize_name(requirement.name) == "pyqt6-qt6" for requirement in parsed_requirements):
        raise ValueError("wheel metadata already contains a PyQt6-Qt6 requirement")

    pyqt, qt_runtime = _pin_pyqt_requirement(parsed_requirements[pyqt_indexes[0]], qt_lower, qt_upper)
    requirements[pyqt_indexes[0]] = pyqt
    requirements.append(qt_runtime)
    del metadata["Requires-Dist"]
    for requirement in requirements:
        metadata["Requires-Dist"] = requirement
    _write_message(metadata_path, metadata)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bind an unpacked Kotonoha wheel to its build Qt minor ABI.")
    parser.add_argument("unpacked_dir", type=Path)
    parser.add_argument("qt_version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    patch_linux_wheel_metadata(args.unpacked_dir, args.qt_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
