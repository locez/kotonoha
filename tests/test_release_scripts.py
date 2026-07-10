from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.assemble_release import assemble_release  # noqa: E402
from scripts.release_version import main as release_version_main  # noqa: E402
from scripts.release_version import resolve_version  # noqa: E402


def write_project(path: Path, version: str) -> None:
    path.write_text(f'[project]\nname = "kotonoha"\nversion = "{version}"\n', encoding="utf-8")


@pytest.mark.parametrize("version", ("0.0.0", "0.1.0", "10.20.30"))
def test_canonical_tag_version_is_authoritative_over_pyproject(tmp_path: Path, version: str) -> None:
    project_path = tmp_path / "pyproject.toml"
    write_project(project_path, "not-a-version")

    assert resolve_version("tag", f"v{version}", project_path) == (version, True)


@pytest.mark.parametrize("version", ("0.0.0", "0.1.0", "10.20.30"))
def test_canonical_manual_version_comes_from_pyproject(tmp_path: Path, version: str) -> None:
    project_path = tmp_path / "pyproject.toml"
    write_project(project_path, version)

    assert resolve_version("branch", "main", project_path) == (version, False)


@pytest.mark.parametrize(
    "tag",
    (
        "1.2.3",
        "v1.2",
        "v1.2.3.4",
        "v1.two.3",
        "v1.2.3-extra",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
    ),
)
def test_invalid_tags_are_rejected(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError, match=r"vX\.Y\.Z"):
        resolve_version("tag", tag, tmp_path / "unused.toml")


@pytest.mark.parametrize(
    "version",
    ("v1.2.3", "1.2", "1.2.3.4", "1.two.3", "1.2.3rc1", "01.2.3", "1.02.3", "1.2.03"),
)
def test_invalid_project_versions_are_rejected(tmp_path: Path, version: str) -> None:
    project_path = tmp_path / "pyproject.toml"
    write_project(project_path, version)

    with pytest.raises(ValueError, match=r"X\.Y\.Z"):
        resolve_version("branch", "main", project_path)


def test_release_version_cli_prints_values_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_path = tmp_path / "pyproject.toml"
    write_project(project_path, "7.8.9")
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    assert release_version_main(["--project", str(project_path)]) == 0
    assert capsys.readouterr().out == "version=7.8.9\nis_tag=false\n"


def test_release_version_cli_appends_github_output(tmp_path: Path) -> None:
    project_path = tmp_path / "pyproject.toml"
    output_path = tmp_path / "github-output"
    write_project(project_path, "0.1.0")
    output_path.write_text("existing=value\n", encoding="utf-8")

    assert (
        release_version_main(
            [
                "--ref-type",
                "tag",
                "--ref-name",
                "v2.3.4",
                "--project",
                str(project_path),
                "--github-output",
                str(output_path),
            ]
        )
        == 0
    )
    assert output_path.read_text(encoding="utf-8") == "existing=value\nversion=2.3.4\nis_tag=true\n"


def create_artifacts(artifacts_dir: Path) -> dict[str, bytes]:
    contents = {
        "kotonoha_1.2.3_amd64.deb": b"deb package",
        "kotonoha-1.2.3-1.x86_64.rpm": b"rpm package",
        "kotonoha-1.2.3-linux_x86_64.whl": b"python wheel",
        "kotonoha-cider-lyrics-1.2.3.zip": b"cider plugin",
    }
    for index, (filename, content) in enumerate(contents.items()):
        artifact_path = artifacts_dir / f"job-{index}" / filename
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_bytes(content)
    return contents


def test_assemble_release_copies_four_artifacts_and_writes_checksums(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    output_dir = tmp_path / "release"
    contents = create_artifacts(artifacts_dir)
    output_dir.mkdir()

    copied = assemble_release(artifacts_dir, output_dir)

    assert copied == tuple(output_dir / filename for filename in sorted(contents))
    assert {path.name: path.read_bytes() for path in copied} == contents
    checksum_lines = (output_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 4
    assert checksum_lines == [
        f"{hashlib.sha256(contents[filename]).hexdigest()}  {filename}" for filename in sorted(contents)
    ]


def test_assemble_release_rejects_non_empty_output_without_mutating_it(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    output_dir = tmp_path / "release"
    create_artifacts(artifacts_dir)
    output_dir.mkdir()
    stale_path = output_dir / "stale-package.deb"
    stale_path.write_bytes(b"stale")

    with pytest.raises(ValueError, match=r"output directory.*empty"):
        assemble_release(artifacts_dir, output_dir)

    assert list(output_dir.iterdir()) == [stale_path]
    assert stale_path.read_bytes() == b"stale"


def test_assemble_release_rejects_duplicate_deb(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    create_artifacts(artifacts_dir)
    duplicate = artifacts_dir / "another-job" / "other.deb"
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"another deb")

    with pytest.raises(ValueError, match=r"exactly one.*\.deb"):
        assemble_release(artifacts_dir, tmp_path / "release")


def test_assemble_release_rejects_symlinked_artifact(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    create_artifacts(artifacts_dir)
    deb_path = next(artifacts_dir.rglob("*.deb"))
    deb_path.unlink()
    symlink_target = tmp_path / "external-deb"
    symlink_target.write_bytes(b"external")
    try:
        deb_path.symlink_to(symlink_target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"cannot create symlinks on this platform: {error}")

    with pytest.raises(ValueError, match=r"exactly one.*\.deb.*found 0"):
        assemble_release(artifacts_dir, tmp_path / "release")


def test_assemble_release_rejects_missing_artifact_class(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    create_artifacts(artifacts_dir)
    next(artifacts_dir.rglob("*.rpm")).unlink()

    with pytest.raises(ValueError, match=r"exactly one.*\.rpm"):
        assemble_release(artifacts_dir, tmp_path / "release")
