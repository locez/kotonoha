from __future__ import annotations

import argparse
import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path

ARTIFACT_PATTERNS = (
    (".deb", "*.deb"),
    (".rpm", "*.rpm"),
    ("Linux x86_64 wheel", "*-linux_x86_64.whl"),
    ("Cider lyrics ZIP", "kotonoha-cider-lyrics-*.zip"),
)


def _require_artifact(artifacts_dir: Path, label: str, pattern: str) -> Path:
    matches = sorted(path for path in artifacts_dir.rglob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label} artifact matching {pattern!r}, found {len(matches)}")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assemble_release(artifacts_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    selected = [_require_artifact(artifacts_dir, label, pattern) for label, pattern in ARTIFACT_PATTERNS]
    filenames = [path.name for path in selected]
    if len(filenames) != len(set(filenames)):
        raise ValueError("release artifacts must have unique destination filenames")

    output_dir.mkdir(parents=True, exist_ok=True)
    copied = tuple(sorted((output_dir / artifact.name for artifact in selected), key=lambda path: path.name))
    selected_by_name = {artifact.name: artifact for artifact in selected}
    for destination in copied:
        shutil.copy2(selected_by_name[destination.name], destination)

    checksum_lines = [f"{_sha256(path)}  {path.name}\n" for path in copied]
    (output_dir / "SHA256SUMS").write_text("".join(checksum_lines), encoding="utf-8")
    return copied


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble Kotonoha release artifacts and checksums.")
    parser.add_argument("artifacts_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    assemble_release(args.artifacts_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
