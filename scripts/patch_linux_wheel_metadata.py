from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from email.message import Message
from email.parser import Parser
from pathlib import Path

QT_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
REQUIREMENT_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _metadata_path(unpacked_dir: Path, filename: str) -> Path:
    matches = sorted(
        path for path in unpacked_dir.rglob(filename) if path.is_file() and path.parent.name.endswith(".dist-info")
    )
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {filename} file, found {len(matches)}")
    return matches[0]


def _requirement_name(requirement: str) -> str:
    match = REQUIREMENT_NAME_PATTERN.match(requirement)
    if match is None:
        raise ValueError(f"invalid wheel requirement: {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


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
    if wheel.get_all("Root-Is-Purelib", []) != ["true"]:
        raise ValueError("wheel must contain exactly one Root-Is-Purelib: true field")
    wheel.replace_header("Root-Is-Purelib", "false")
    _write_message(wheel_path, wheel)

    metadata_path = _metadata_path(unpacked_dir, "METADATA")
    metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
    requirements = metadata.get_all("Requires-Dist", [])
    pyqt_indexes = [
        index for index, requirement in enumerate(requirements) if _requirement_name(requirement) == "pyqt6"
    ]
    if len(pyqt_indexes) != 1:
        raise ValueError(f"expected exactly one PyQt6 requirement, found {len(pyqt_indexes)}")
    if requirements[pyqt_indexes[0]].strip() != "PyQt6":
        raise ValueError("expected an unqualified PyQt6 requirement without extras, versions, or markers")
    if any(_requirement_name(requirement) == "pyqt6-qt6" for requirement in requirements):
        raise ValueError("wheel metadata already contains a PyQt6-Qt6 requirement")

    requirements[pyqt_indexes[0]] = f"PyQt6<{qt_upper},>={qt_lower}"
    requirements.append(f"PyQt6-Qt6<{qt_upper},>={qt_lower}")
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
