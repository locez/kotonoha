# GitHub Workflows and Linux Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable Python/Cider CI and tag-driven DEB, RPM, Linux wheel, Cider ZIP, checksum, desktop integration, and GitHub Release builds.

**Architecture:** Keep GitHub Actions split into a reusable validation workflow and a release orchestration workflow. Put version resolution and release-bundle validation in small tested Python scripts, keep distro installation metadata under `packaging/`, and inject the resolved release version into both Python and Cider builds without changing local development defaults.

**Tech Stack:** GitHub Actions, Python 3.10+, pytest, uv, Hatchling, Debian debhelper/pybuild, Fedora RPM macros, PyQt6/Qt6, LayerShellQt, Node.js 20, pnpm 9, Vite, Vitest

---

### Task 1: Add Tested Release Utilities

**Files:**
- Create: `scripts/release_version.py`
- Create: `scripts/assemble_release.py`
- Create: `tests/test_release_scripts.py`

- [ ] **Step 1: Write failing tests for version resolution and artifact assembly**

Create `tests/test_release_scripts.py`:

```python
from pathlib import Path

import pytest

from scripts.assemble_release import assemble_release
from scripts.release_version import resolve_version


def _write_project(path: Path, version: str = "0.1.0") -> None:
    path.write_text(f'[project]\nname = "kotonoha"\nversion = "{version}"\n', encoding="utf-8")


def test_tag_version_is_authoritative(tmp_path):
    project = tmp_path / "pyproject.toml"
    _write_project(project)
    assert resolve_version("tag", "v1.2.3", project) == ("1.2.3", True)


def test_manual_version_comes_from_pyproject(tmp_path):
    project = tmp_path / "pyproject.toml"
    _write_project(project, "2.4.6")
    assert resolve_version("branch", "main", project) == ("2.4.6", False)


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "v1.2.3.4", "vnext"])
def test_invalid_release_tag_is_rejected(tmp_path, tag):
    project = tmp_path / "pyproject.toml"
    _write_project(project)
    with pytest.raises(ValueError, match="X.Y.Z"):
        resolve_version("tag", tag, project)


def test_release_assembly_requires_one_of_each_artifact(tmp_path):
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "release"
    files = {
        "deb/kotonoha_1.2.3_amd64.deb": b"deb",
        "rpm/kotonoha-1.2.3-1.x86_64.rpm": b"rpm",
        "wheel/kotonoha-1.2.3-py3-none-linux_x86_64.whl": b"wheel",
        "cider/kotonoha-cider-lyrics-1.2.3.zip": b"zip",
    }
    for relative, payload in files.items():
        path = artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    assembled = assemble_release(artifacts, output)

    assert {path.name for path in assembled} == {Path(name).name for name in files}
    assert len((output / "SHA256SUMS").read_text(encoding="ascii").splitlines()) == 4


def test_release_assembly_rejects_duplicate_artifacts(tmp_path):
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "release"
    (artifacts / "deb").mkdir(parents=True)
    (artifacts / "deb/a.deb").write_bytes(b"a")
    (artifacts / "deb/b.deb").write_bytes(b"b")
    with pytest.raises(ValueError, match="exactly one DEB"):
        assemble_release(artifacts, output)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run `uv run pytest tests/test_release_scripts.py -q`.

Expected: collection fails because the two release script modules do not exist.

- [ ] **Step 3: Implement version resolution**

Create `scripts/release_version.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import tomllib
from pathlib import Path

# Canonical numeric X.Y.Z: each component is 0 or starts with 1-9.
VERSION_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


def _validate_version(version: str) -> str:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"release version must use X.Y.Z, got {version!r}")
    return version


def resolve_version(ref_type: str, ref_name: str, project_path: Path) -> tuple[str, bool]:
    if ref_type == "tag":
        if not ref_name.startswith("v"):
            raise ValueError(f"release tag must use vX.Y.Z, got {ref_name!r}")
        return _validate_version(ref_name[1:]), True
    with project_path.open("rb") as project_file:
        project = tomllib.load(project_file)
    version = project.get("project", {}).get("version")
    if not isinstance(version, str):
        raise ValueError("pyproject.toml has no string project.version")
    return _validate_version(version), False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE", "branch"))
    parser.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    version, is_tag = resolve_version(args.ref_type, args.ref_name, args.pyproject)
    values = {"version": version, "is_tag": str(is_tag).lower()}
    if args.github_output is None:
        for key, value in values.items():
            print(f"{key}={value}")
    else:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement artifact assembly and checksums**

Create `scripts/assemble_release.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

ARTIFACT_PATTERNS = {
    "DEB": "**/*.deb",
    "RPM": "**/*.rpm",
    "Linux wheel": "**/*-linux_x86_64.whl",
    "Cider ZIP": "**/kotonoha-cider-lyrics-*.zip",
}


def _one_match(root: Path, label: str, pattern: str) -> Path:
    matches = sorted(path for path in root.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0]


def assemble_release(artifacts_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    selected = tuple(
        _one_match(artifacts_dir, label, pattern)
        for label, pattern in ARTIFACT_PATTERNS.items()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = tuple(output_dir / source.name for source in selected)
    if len({path.name for path in copied}) != len(copied):
        raise ValueError("release artifact filenames must be unique")
    for source, destination in zip(selected, copied, strict=True):
        shutil.copy2(source, destination)
    lines = []
    for path in sorted(copied, key=lambda item: item.name):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    assemble_release(args.artifacts_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify and commit the utilities**

Run:

```bash
uv run pytest tests/test_release_scripts.py -q
uv run ruff check scripts tests/test_release_scripts.py
uv run ty check scripts tests/test_release_scripts.py
git add scripts/release_version.py scripts/assemble_release.py tests/test_release_scripts.py
git commit -m "build: add release metadata utilities"
```

Expected: tests and static checks pass before the commit.

### Task 2: Inject the Release Version into the Cider Manifest

**Files:**
- Modify: `plugins/cider/lyrics/src/plugin.config.ts`
- Modify: `plugins/cider/lyrics/vite.config.ts`
- Create: `plugins/cider/lyrics/src/__tests__/pluginConfig.test.ts`

- [ ] **Step 1: Add failing plugin-version tests**

Create `plugins/cider/lyrics/src/__tests__/pluginConfig.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { resolvePluginVersion } from "../plugin.config";

describe("resolvePluginVersion", () => {
  it("keeps the development version without release input", () => {
    expect(resolvePluginVersion(undefined)).toBe("0.0.1");
  });

  it("accepts X.Y.Z", () => {
    expect(resolvePluginVersion("1.2.3")).toBe("1.2.3");
  });

  it("rejects prefixed versions", () => {
    expect(() => resolvePluginVersion("v1.2.3")).toThrow("X.Y.Z");
  });
});
```

- [ ] **Step 2: Run `pnpm exec vitest run src/__tests__/pluginConfig.test.ts` and verify RED**

Run from `plugins/cider/lyrics`. Expected: FAIL because the resolver is not exported.

- [ ] **Step 3: Implement version validation and Vite injection**

Add to `src/plugin.config.ts`:

```ts
const DEVELOPMENT_VERSION = "0.0.1";
const RELEASE_VERSION_PATTERN = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;

export function resolvePluginVersion(value: string | undefined): string {
  if (value === undefined || value === "") {
    return DEVELOPMENT_VERSION;
  }
  if (!RELEASE_VERSION_PATTERN.test(value)) {
    throw new Error(`Cider plugin release version must use X.Y.Z, got ${value}`);
  }
  return value;
}
```

Change the manifest field to:

```ts
version: resolvePluginVersion(process.env.KOTONOHA_VERSION),
```

Change the existing `process.env` definition in `vite.config.ts` to:

```ts
"process.env": JSON.stringify({
  NODE_ENV: "production",
  cider: "2",
  KOTONOHA_VERSION: process.env.KOTONOHA_VERSION ?? "",
}),
```

- [ ] **Step 4: Verify generated plugin metadata and commit**

Run from `plugins/cider/lyrics`:

```bash
pnpm exec vitest run src/__tests__/pluginConfig.test.ts
KOTONOHA_VERSION=1.2.3 pnpm build
rg '^version: 1.2.3$' dist/dev.locez.kotonoha.cider.lyrics/plugin.yml
git add src/plugin.config.ts vite.config.ts src/__tests__/pluginConfig.test.ts
git commit -m "build(cider): inject release version"
```

Expected: Vitest passes and the generated manifest contains version `1.2.3`.

### Task 3: Add the Multilingual Desktop Entry

**Files:**
- Create: `packaging/kotonoha.desktop`
- Create: `tests/test_desktop_entry.py`

- [ ] **Step 1: Write the failing desktop metadata test**

Create `tests/test_desktop_entry.py`:

```python
from configparser import ConfigParser
from pathlib import Path

DESKTOP_FILE = Path("packaging/kotonoha.desktop")


def test_desktop_entry_has_commands_icon_and_localizations():
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    assert parser.read(DESKTOP_FILE, encoding="utf-8") == [str(DESKTOP_FILE)]
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Exec"] == "kotonoha"
    assert entry["Icon"] == "kotonoha"
    assert entry["Terminal"] == "false"
    assert entry["Categories"].endswith(";")
    for locale in ("zh_CN", "zh_TW", "ja"):
        assert entry[f"Name[{locale}]"]
        assert entry[f"GenericName[{locale}]"]
        assert entry[f"Comment[{locale}]"]
        assert entry[f"Keywords[{locale}]"].endswith(";")
```

- [ ] **Step 2: Run `uv run pytest tests/test_desktop_entry.py -q` and verify RED**

Expected: FAIL because the desktop file does not exist.

- [ ] **Step 3: Create `packaging/kotonoha.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Kotonoha
Name[zh_CN]=Kotonoha 歌词 HUD
Name[zh_TW]=Kotonoha 歌詞 HUD
Name[ja]=Kotonoha 歌詞 HUD
GenericName=Lyrics Overlay
GenericName[zh_CN]=桌面歌词悬浮窗
GenericName[zh_TW]=桌面歌詞懸浮視窗
GenericName[ja]=デスクトップ歌詞オーバーレイ
Comment=Show synchronized lyrics for the current track
Comment[zh_CN]=显示当前歌曲的同步歌词
Comment[zh_TW]=顯示目前歌曲的同步歌詞
Comment[ja]=再生中の曲の同期歌詞を表示
Exec=kotonoha
Icon=kotonoha
Terminal=false
Categories=AudioVideo;Audio;
Keywords=lyrics;music;overlay;karaoke;
Keywords[zh_CN]=歌词;音乐;悬浮窗;卡拉OK;
Keywords[zh_TW]=歌詞;音樂;懸浮視窗;卡拉OK;
Keywords[ja]=歌詞;音楽;オーバーレイ;カラオケ;
```

- [ ] **Step 4: Validate and commit the desktop entry**

```bash
uv run pytest tests/test_desktop_entry.py -q
desktop-file-validate packaging/kotonoha.desktop
git add packaging/kotonoha.desktop tests/test_desktop_entry.py
git commit -m "feat(packaging): add localized desktop entry"
```

Expected: pytest and desktop validation pass.

### Task 4: Add Debian and Fedora Package Metadata

**Files:**
- Create: `packaging/debian/control`
- Create: `packaging/debian/rules`
- Create: `packaging/debian/install`
- Create: `packaging/debian/changelog`
- Create: `packaging/fedora/kotonoha.spec`
- Create: `tests/test_native_packaging.py`

- [ ] **Step 1: Write failing static package tests**

Create `tests/test_native_packaging.py`:

```python
from pathlib import Path


def test_debian_metadata_installs_required_runtime_parts():
    control = Path("packaging/debian/control").read_text(encoding="utf-8")
    rules = Path("packaging/debian/rules").read_text(encoding="utf-8")
    install = Path("packaging/debian/install").read_text(encoding="utf-8")
    for dependency in ("python3-pyqt6", "python3-aiohttp", "python3-qasync", "python3-dbus-fast"):
        assert dependency in control
    assert "dh-sequence-python3" in control
    assert "dh $@ --buildsystem=pybuild" in rules
    assert "USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh" in rules
    assert "hatch-build-scripts" in rules
    assert "src/kotonoha/assets/icon.png" in rules
    assert "packaging/kotonoha.desktop" in install


def test_fedora_spec_installs_required_runtime_parts():
    spec = Path("packaging/fedora/kotonoha.spec").read_text(encoding="utf-8")
    for dependency in ("python3-qt6", "python3-aiohttp", "python3-qasync", "python3-dbus-fast"):
        assert dependency in spec
    assert "USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh" in spec
    assert "hatch-build-scripts" in spec
    assert "PYTHON" + "PATH" not in spec
    assert "desktop-file-validate" in spec
    assert "%{_datadir}/applications/kotonoha.desktop" in spec
    assert "%{_datadir}/pixmaps/kotonoha.png" in spec
```

- [ ] **Step 2: Run `uv run pytest tests/test_native_packaging.py -q` and verify RED**

Expected: FAIL because package metadata does not exist.

- [ ] **Step 3: Create Debian metadata**

Create `packaging/debian/control`:

```text
Source: kotonoha
Section: sound
Priority: optional
Maintainer: Locez <locez@locez.com>
Build-Depends: debhelper-compat (= 13), dh-python, dh-sequence-python3, pybuild-plugin-pyproject, python3-all, python3-hatchling, python3-aiohttp, python3-dbus-fast, python3-pyqt6, python3-qasync, liblayershellqtinterface-dev, qt6-base-dev, qt6-base-private-dev, libwayland-dev, pkg-config, g++, desktop-file-utils
Standards-Version: 4.7.0
Rules-Requires-Root: no
Homepage: https://github.com/locez/kotonoha

Package: kotonoha
Architecture: any
Depends: ${python3:Depends}, ${shlibs:Depends}, ${misc:Depends}, python3-aiohttp, python3-dbus-fast, python3-pyqt6, python3-qasync
Description: synchronized lyrics overlay for Linux desktops
 Kotonoha displays synchronized, word-timed lyrics above fullscreen and desktop
 applications using MPRIS metadata and multiple external lyric providers.
```

Create executable `packaging/debian/rules`:

```make
#!/usr/bin/make -f
export PYBUILD_NAME=kotonoha
export USE_SYSTEM_LIBS=1
PYPROJECT_BACKUP := debian/.kotonoha-pyproject.toml.orig

%:
	dh $@ --buildsystem=pybuild

override_dh_auto_configure:
	test -e $(PYPROJECT_BACKUP) || cp -p pyproject.toml $(PYPROJECT_BACKUP)
	sed -i 's/^requires = \["hatchling", "hatch-build-scripts"\]$$/requires = ["hatchling"]/' pyproject.toml
	sed -i '/^\[tool\.hatch\.build\.hooks\.build-scripts\]$$/,/^artifacts = \["src\/kotonoha\/libkoto-layer\.so"\]$$/d' pyproject.toml
	USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh
	dh_auto_configure --buildsystem=pybuild

override_dh_auto_test:
	@echo "Skipping package-build tests; the reusable GitHub test workflow runs them first."

override_dh_clean:
	rm -f src/kotonoha/libkoto-layer.so
	if [ -e $(PYPROJECT_BACKUP) ]; then mv -f $(PYPROJECT_BACKUP) pyproject.toml; fi
	dh_clean

override_dh_install:
	dh_install
	install -D -m 644 src/kotonoha/assets/icon.png debian/kotonoha/usr/share/pixmaps/kotonoha.png
```

Create `packaging/debian/install`:

```text
packaging/kotonoha.desktop usr/share/applications
```

Create `packaging/debian/changelog`:

```text
kotonoha (0.1.0-1) unstable; urgency=medium

  * Initial release.

 -- Locez <locez@locez.com>  Sat, 11 Jul 2026 00:00:00 +0800
```

- [ ] **Step 4: Create `packaging/fedora/kotonoha.spec`**

```spec
%global debug_package %{nil}

Name:           kotonoha
Version:        0.1.0
Release:        1%{?dist}
Summary:        Synchronized lyrics overlay for Linux desktops
License:        MIT
URL:            https://github.com/locez/kotonoha
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-hatchling
BuildRequires:  python3-pyproject-rpm-macros
BuildRequires:  gcc-c++
BuildRequires:  qt6-qtbase-devel
BuildRequires:  layer-shell-qt-devel
BuildRequires:  wayland-devel
BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-qt6
Requires:       python3-aiohttp
Requires:       python3-qasync
Requires:       python3-dbus-fast
Requires:       layer-shell-qt

%description
Kotonoha displays synchronized, word-timed lyrics above fullscreen and desktop
applications using MPRIS metadata and multiple external lyric providers.

%prep
%autosetup
sed -i 's/^requires = \["hatchling", "hatch-build-scripts"\]$/requires = ["hatchling"]/' pyproject.toml
sed -i '/^\[tool\.hatch\.build\.hooks\.build-scripts\]$/,/^artifacts = \["src\/kotonoha\/libkoto-layer\.so"\]$/d' pyproject.toml

%build
USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files kotonoha
install -p -D -m 644 packaging/kotonoha.desktop %{buildroot}%{_datadir}/applications/kotonoha.desktop
install -p -D -m 644 src/kotonoha/assets/icon.png %{buildroot}%{_datadir}/pixmaps/kotonoha.png

%check
desktop-file-validate packaging/kotonoha.desktop

%files -f %{pyproject_files}
%{_bindir}/kotonoha
%{_datadir}/applications/kotonoha.desktop
%{_datadir}/pixmaps/kotonoha.png
```

- [ ] **Step 5: Validate and commit native packaging metadata**

```bash
chmod +x packaging/debian/rules
uv run pytest tests/test_native_packaging.py tests/test_desktop_entry.py -q
desktop-file-validate packaging/kotonoha.desktop
git add packaging/debian packaging/fedora tests/test_native_packaging.py
git commit -m "build: add debian and fedora packaging"
```

Expected: focused tests and desktop validation pass.

### Task 5: Add the Reusable Test Workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create `.github/workflows/test.yml`**

```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_call:
    inputs:
      release_validation:
        description: Preserve this reusable validation run from ordinary CI cancellation
        required: false
        type: boolean
        default: false

permissions:
  contents: read

concurrency:
  group: test-${{ github.workflow }}-${{ inputs.release_validation && github.run_id || github.ref }}
  cancel-in-progress: ${{ ! inputs.release_validation }}

jobs:
  python:
    runs-on: ubuntu-latest
    container: ubuntu:26.04
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.10', '3.11', '3.12', '3.13', '3.14']
    steps:
      - name: Install checkout prerequisites
        run: |
          apt-get update
          apt-get install -y ca-certificates git
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: ${{ matrix.python-version }}
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6
        with:
          version: 0.11.19
          enable-cache: true
          cache-dependency-glob: uv.lock
      - name: Install Qt and Wayland dependencies
        run: |
          apt-get update
          apt-get install -y xvfb libegl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 qt6-base-dev qt6-base-private-dev libwayland-dev liblayershellqtinterface-dev pkg-config build-essential desktop-file-utils
      - name: Install Python dependencies
        run: uv sync --locked --extra test
      - name: Verify native bridge linkage
        run: |
          bridge=src/kotonoha/libkoto-layer.so
          test -f "$bridge"
          ldd "$bridge" | tee /tmp/libkoto-layer.ldd
          grep -F "libQt6Core.so" /tmp/libkoto-layer.ldd
          grep -F "libQt6Gui.so" /tmp/libkoto-layer.ldd
          grep -F "LayerShellQt" /tmp/libkoto-layer.ldd
          if grep -E "libQt5[^ ]*\\.so" /tmp/libkoto-layer.ldd; then
            echo "Qt 5 dependency detected in $bridge" >&2
            exit 1
          fi
          uv run python -c "import ctypes; ctypes.CDLL('$bridge')"
      - name: Test Python application
        run: xvfb-run -a uv run pytest
      - name: Lint Python
        run: uv run ruff check .
      - name: Type-check Python
        run: uv run ty check
      - name: Validate desktop entry
        run: desktop-file-validate packaging/kotonoha.desktop

  cider:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: plugins/cider/lyrics
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4
        with:
          version: 9.10.0
          run_install: false
      - uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6
        with:
          node-version: '20'
          cache: pnpm
          cache-dependency-path: plugins/cider/lyrics/pnpm-lock.yaml
      - name: Install Cider dependencies
        run: pnpm install --frozen-lockfile
      - name: Test Cider plugin
        run: pnpm test
      - name: Build Cider plugin
        run: pnpm build
      - name: Verify Cider outputs
        run: |
          test -f dist/dev.locez.kotonoha.cider.lyrics/plugin.js
          test -f dist/dev.locez.kotonoha.cider.lyrics/plugin.yml
```

- [ ] **Step 2: Validate workflow syntax**

Run:

```bash
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/test.yml
```

Expected: no diagnostics.

- [ ] **Step 3: Run the workflow commands locally**

```bash
uv sync --locked --extra test
ldd src/kotonoha/libkoto-layer.so
uv run python -c "import ctypes; ctypes.CDLL('src/kotonoha/libkoto-layer.so')"
uv run pytest
uv run ruff check .
uv run ty check
cd plugins/cider/lyrics
pnpm test
pnpm build
```

Expected: the bridge links to Qt6Core, Qt6Gui, and LayerShellQt without Qt 5, loads through `ctypes`, all checks pass, and both plugin output files exist.

- [ ] **Step 4: Commit the test workflow**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add python and cider validation"
```

### Task 6: Add the Package and Release Workflow

**Files:**
- Create: `.github/workflows/package.yml`

- [ ] **Step 1: Create `.github/workflows/package.yml`**

```yaml
name: Package

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  validate:
    uses: ./.github/workflows/test.yml
    with:
      release_validation: true

  version:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.release.outputs.version }}
      is_tag: ${{ steps.release.outputs.is_tag }}
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - id: release
        name: Resolve release version
        env:
          VERSION_REF_TYPE: ${{ github.event_name == 'push' && github.ref_type == 'tag' && 'tag' || 'manual' }}
          VERSION_REF_NAME: ${{ github.ref_name }}
        run: |
          python3 scripts/release_version.py \
            --ref-type "$VERSION_REF_TYPE" \
            --ref-name "$VERSION_REF_NAME" \
            --github-output "$GITHUB_OUTPUT"

  deb:
    needs: [validate, version]
    runs-on: ubuntu-latest
    container: ubuntu:26.04
    defaults:
      run:
        shell: bash
    env:
      VERSION: ${{ needs.version.outputs.version }}
    steps:
      - name: Install checkout prerequisites
        run: |
          apt-get update
          apt-get install -y git ca-certificates
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - name: Install Debian build dependencies
        run: |
          apt-get update
          apt-get install -y devscripts debhelper dh-python dh-sequence-python3 pybuild-plugin-pyproject python3-all python3-hatchling python3-aiohttp python3-dbus-fast python3-pyqt6 python3-qasync liblayershellqtinterface-dev qt6-base-dev qt6-base-private-dev libwayland-dev pkg-config build-essential python3-pip desktop-file-utils
          python3 -m pip install uv --break-system-packages
      - name: Prepare Debian source
        run: |
          uv version "$VERSION" --frozen
          cp -r packaging/debian debian
          chmod +x debian/rules
          export DEBEMAIL="actions@github.com"
          export DEBFULLNAME="GitHub Actions"
          dch -v "${VERSION}-1" -D unstable --force-distribution "Automated release build"
      - name: Build Debian package
        run: debuild -us -uc -b
      - name: Install and verify Debian package
        run: |
          mv ../kotonoha_*.deb .
          apt-get install -y ./kotonoha_*.deb
          python3 -c "import kotonoha.main"
          command -v kotonoha
          dpkg -L kotonoha | grep -F '/libkoto-layer.so'
          test -f /usr/share/applications/kotonoha.desktop
          test -f /usr/share/pixmaps/kotonoha.png
          desktop-file-validate /usr/share/applications/kotonoha.desktop
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: kotonoha-deb
          path: kotonoha_*.deb
          if-no-files-found: error

  rpm:
    needs: [validate, version]
    runs-on: ubuntu-latest
    container: fedora:43
    defaults:
      run:
        shell: bash
    env:
      VERSION: ${{ needs.version.outputs.version }}
    steps:
      - name: Install checkout prerequisites
        run: dnf install -y git
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - name: Install Fedora build dependencies
        run: |
          dnf install -y rpm-build python3-devel python3-hatchling python3-pyproject-rpm-macros python3-qt6 python3-aiohttp python3-qasync python3-dbus-fast gcc-c++ libstdc++-static qt6-qtbase-devel qt6-qtbase-private-devel layer-shell-qt-devel wayland-devel desktop-file-utils git tar python3-pip
          python3 -m pip install uv
      - name: Prepare RPM source
        run: |
          uv version "$VERSION" --frozen
          sed -i "s/^Version:.*/Version:        ${VERSION}/" packaging/fedora/kotonoha.spec
          test "$(grep -Ec '^\* .* - (0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-1$' packaging/fedora/kotonoha.spec)" -eq 1
          sed -i -E "0,/^(\* .* - )(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-1$/s//\1${VERSION}-1/" packaging/fedora/kotonoha.spec
          mkdir -p ~/rpmbuild/SOURCES
          tar --transform "s|^\.|kotonoha-${VERSION}|" --exclude='.git' -czf ~/rpmbuild/SOURCES/kotonoha-${VERSION}.tar.gz .
      - name: Build RPM
        run: rpmbuild -bb packaging/fedora/kotonoha.spec
      - name: Install and verify RPM
        run: |
          dnf install -y ~/rpmbuild/RPMS/*/kotonoha-*.rpm
          python3 -c "import kotonoha.main"
          command -v kotonoha
          rpm -ql kotonoha | grep -F '/libkoto-layer.so'
          test -f /usr/share/applications/kotonoha.desktop
          test -f /usr/share/pixmaps/kotonoha.png
          desktop-file-validate /usr/share/applications/kotonoha.desktop
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: kotonoha-rpm
          path: /github/home/rpmbuild/RPMS/**/*.rpm
          if-no-files-found: error

  wheel:
    needs: [validate, version]
    runs-on: ubuntu-latest
    container: ubuntu:26.04
    defaults:
      run:
        shell: bash
    env:
      VERSION: ${{ needs.version.outputs.version }}
    steps:
      - name: Install checkout prerequisites
        run: |
          apt-get update
          apt-get install -y ca-certificates git
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: '3.14'
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6
        with:
          version: 0.11.19
      - name: Install native build dependencies
        run: |
          apt-get update
          apt-get install -y qt6-base-dev qt6-base-private-dev qt6-wayland-dev libwayland-dev liblayershellqtinterface-dev pkg-config build-essential
      - name: Build non-pure Linux wheel
        run: |
          set -euo pipefail
          uv version "$VERSION" --frozen
          uv build --wheel
          shopt -s nullglob
          built_wheels=(dist/*.whl)
          test "${#built_wheels[@]}" -eq 1
          uvx --from wheel==0.45.1 wheel unpack --dest dist/unpacked "${built_wheels[0]}"
          unpacked_dirs=(dist/unpacked/*)
          test "${#unpacked_dirs[@]}" -eq 1
          test -d "${unpacked_dirs[0]}"
          metadata_files=("${unpacked_dirs[0]}"/*.dist-info/WHEEL)
          test "${#metadata_files[@]}" -eq 1
          python - "${metadata_files[0]}" <<'PY'
          from pathlib import Path
          import sys

          metadata_path = Path(sys.argv[1])
          contents = metadata_path.read_text(encoding="utf-8")
          lines = contents.splitlines()
          if lines.count("Root-Is-Purelib: true") != 1 or "Root-Is-Purelib: false" in lines:
              raise SystemExit("unexpected Root-Is-Purelib metadata")
          metadata_path.write_text(
              contents.replace("Root-Is-Purelib: true", "Root-Is-Purelib: false", 1),
              encoding="utf-8",
          )
          PY
          rm "${built_wheels[0]}"
          repacked_dir=dist/repacked
          test ! -e "$repacked_dir"
          mkdir "$repacked_dir"
          uvx --from wheel==0.45.1 wheel pack --dest-dir "$repacked_dir" "${unpacked_dirs[0]}"
          packed_wheels=("$repacked_dir"/*.whl)
          test "${#packed_wheels[@]}" -eq 1
          uvx --from wheel==0.45.1 wheel tags --remove --platform-tag linux_x86_64 "${packed_wheels[0]}"
          repacked_wheels=("$repacked_dir"/*.whl)
          test "${#repacked_wheels[@]}" -eq 1
          mv "${repacked_wheels[0]}" dist/
      - name: Verify wheel metadata and installation
        run: |
          set -euo pipefail
          test "$(find dist -maxdepth 1 -name '*-linux_x86_64.whl' | wc -l)" -eq 1
          test "$(find dist -maxdepth 1 -name '*-any.whl' | wc -l)" -eq 0
          python -c 'from email.parser import Parser; from zipfile import ZipFile; path=next(__import__("pathlib").Path("dist").glob("*-linux_x86_64.whl")); archive=ZipFile(path); names=[name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]; assert len(names) == 1; metadata=Parser().parsestr(archive.read(names[0]).decode()); assert metadata.get_all("Root-Is-Purelib") == ["false"]; assert metadata.get_all("Tag") == ["py3-none-linux_x86_64"]'
          uv venv /tmp/kotonoha-wheel-test
          uv pip install --python /tmp/kotonoha-wheel-test/bin/python dist/*-linux_x86_64.whl
          /tmp/kotonoha-wheel-test/bin/python -c "import kotonoha.main; from kotonoha.lyrics_loader import find_layer_shell_library; assert find_layer_shell_library()"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: kotonoha-wheel
          path: dist/*-linux_x86_64.whl
          if-no-files-found: error

  cider:
    needs: [validate, version]
    runs-on: ubuntu-latest
    env:
      VERSION: ${{ needs.version.outputs.version }}
    defaults:
      run:
        working-directory: plugins/cider/lyrics
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4
        with:
          version: 9.10.0
          run_install: false
      - uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6
        with:
          node-version: '20'
          cache: pnpm
          cache-dependency-path: plugins/cider/lyrics/pnpm-lock.yaml
      - name: Install and test Cider plugin
        run: |
          pnpm install --frozen-lockfile
          pnpm test
      - name: Build versioned Cider plugin
        run: KOTONOHA_VERSION="$VERSION" pnpm build
      - name: Stage Cider plugin
        run: |
          mkdir -p staging/dev.locez.kotonoha.cider.lyrics
          cp dist/dev.locez.kotonoha.cider.lyrics/plugin.js staging/dev.locez.kotonoha.cider.lyrics/
          cp dist/dev.locez.kotonoha.cider.lyrics/plugin.yml staging/dev.locez.kotonoha.cider.lyrics/
          grep -F "version: $VERSION" staging/dev.locez.kotonoha.cider.lyrics/plugin.yml
      - name: Create Cider ZIP
        working-directory: plugins/cider/lyrics/staging
        run: python3 -m zipfile -c "$GITHUB_WORKSPACE/kotonoha-cider-lyrics-${VERSION}.zip" dev.locez.kotonoha.cider.lyrics
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: kotonoha-cider-plugin
          path: kotonoha-cider-lyrics-*.zip
          if-no-files-found: error

  assemble:
    needs: [version, deb, rpm, wheel, cider]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8
        with:
          path: artifacts
      - name: Assemble and checksum release files
        run: python3 scripts/assemble_release.py artifacts release
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: kotonoha-release-${{ needs.version.outputs.version }}
          path: release/*
          if-no-files-found: error

  release:
    needs: [version, assemble]
    if: github.event_name == 'push' && needs.version.outputs.is_tag == 'true'
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8
        with:
          name: kotonoha-release-${{ needs.version.outputs.version }}
          path: release
      - name: Create GitHub Release
        uses: softprops/action-gh-release@718ea10b132b3b2eba29c1007bb80653f286566b # v3
        with:
          files: release/*
          fail_on_unmatched_files: true
          generate_release_notes: true
```

- [ ] **Step 2: Validate workflow syntax and references**

Run:

```bash
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/test.yml .github/workflows/package.yml
python3 scripts/release_version.py --ref-type tag --ref-name v1.2.3
python3 scripts/release_version.py --ref-type manual --ref-name v1.2.3
uv run pytest tests/test_release_scripts.py -q
```

Expected: actionlint has no diagnostics; the tag command prints `version=1.2.3` and `is_tag=true`; the forced manual command reads `project.version` and prints `is_tag=false`; and tests pass.

- [ ] **Step 3: Commit the package workflow**

```bash
git add .github/workflows/package.yml
git commit -m "ci: build linux and cider release artifacts"
```

### Task 7: Document Releases and Run Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Release packages section before Layout**

````markdown
## Release packages

Version tags in the form `vX.Y.Z` run the complete Python and Cider test suites, then publish a GitHub Release containing:

- a DEB package for Ubuntu-compatible systems;
- an RPM package for Fedora-compatible systems;
- a Linux x86_64 Python wheel;
- `kotonoha-cider-lyrics-X.Y.Z.zip`;
- `SHA256SUMS`.

The DEB and RPM install the multilingual desktop entry and default application icon. The wheel contains the native LayerShellQt bridge and therefore is Linux x86_64-specific; compatible Qt 6, Wayland, and LayerShellQt system libraries are still required.

The Cider ZIP contains the `dev.locez.kotonoha.cider.lyrics` directory. Extract it directly under Cider's plugin directory, then reload Cider. The plugin remains experimental and external lyric providers should stay enabled.

Maintainers can create a release with:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Running the Package workflow manually builds and retains the same Actions artifacts using `project.version` from `pyproject.toml`, but does not create a GitHub Release, even when a tag is selected as the workflow ref.
````

- [ ] **Step 2: Run all repository validation**

```bash
uv run pytest
uv run ruff check .
uv run ty check
desktop-file-validate packaging/kotonoha.desktop
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/test.yml .github/workflows/package.yml
cd plugins/cider/lyrics
pnpm test
pnpm build
```

Expected: Python tests/static checks, desktop validation, workflow validation, Cider tests, and Cider build all pass.

- [ ] **Step 3: Build and inspect the wheel**

```bash
uv build --wheel
python3 -m zipfile -l dist/kotonoha-*.whl
```

Expected: the listing includes `kotonoha/libkoto-layer.so`, `kotonoha/assets/icon.png`, and the selectable files under `kotonoha/assets/icons/`.

- [ ] **Step 4: Review and commit documentation**

```bash
git diff --check
git status --short
git add README.md
git commit -m "docs: describe release packages"
```

Expected: no whitespace errors and only planned files are changed before the documentation commit.

- [ ] **Step 5: Prove the hosted build before creating a release tag**

Push the implementation branch and confirm the Test workflow is green. Then run Package manually to prove Ubuntu 26.04/Fedora 43 dependency names and native package installation. Create the first `vX.Y.Z` tag only after that manual package run succeeds.
