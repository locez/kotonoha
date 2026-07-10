from __future__ import annotations

import argparse
import os
import re
from collections.abc import Sequence
from pathlib import Path

try:
    import tomllib  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib  # ty: ignore[unresolved-import]


VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
TAG_PATTERN = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+)")


def resolve_version(ref_type: str, ref_name: str, project_path: Path) -> tuple[str, bool]:
    if ref_type == "tag":
        match = TAG_PATTERN.fullmatch(ref_name)
        if match is None:
            raise ValueError(f"invalid release tag {ref_name!r}; expected vX.Y.Z")
        return match.group(1), True

    with project_path.open("rb") as project_file:
        project = tomllib.load(project_file)

    try:
        version = project["project"]["version"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{project_path} must define project.version as X.Y.Z") from error
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"invalid project.version {version!r} in {project_path}; expected X.Y.Z")
    return version, False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve the version for a Kotonoha release build.")
    parser.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE", ""))
    parser.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    version, is_tag = resolve_version(args.ref_type, args.ref_name, args.project)
    output = f"version={version}\nis_tag={str(is_tag).lower()}\n"
    if args.github_output is None:
        print(output, end="")
    else:
        with args.github_output.open("a", encoding="utf-8") as output_file:
            output_file.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
