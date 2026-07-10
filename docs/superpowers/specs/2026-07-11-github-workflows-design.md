# GitHub Workflows and Linux Packaging Design

## Goal

Add a release-grade GitHub Actions pipeline for Kotonoha, using BiliHUD's split test/package workflow as the baseline while accounting for Kotonoha's Cider plugin, native Wayland bridge, dynamic icon assets, and multilingual desktop integration.

The pipeline must validate both codebases on every proposed change and produce installable Linux artifacts from version tags without publishing incomplete or incorrectly labelled packages.

## Scope

This design adds:

- reusable Python and Cider continuous integration;
- DEB and RPM packaging;
- a Linux-native Python wheel;
- a directly installable Cider plugin ZIP;
- a multilingual desktop entry and packaged application icon;
- tag-driven GitHub Releases with generated notes and checksums;
- manual package builds that upload Actions artifacts without creating a release;
- documentation for CI, package installation, and releases.

It does not add automatic publishing to PyPI, distro repositories, Cider marketplaces, or container registries. The Cider plugin remains experimental.

## Workflow Architecture

Two workflows keep continuous integration separate from release orchestration.

### Test Workflow

`.github/workflows/test.yml` supports `push`, `pull_request`, and `workflow_call`.

The Python job uses an Ubuntu 26.04 container on an Ubuntu runner and a Python 3.10, 3.11, 3.12, 3.13, and 3.14 matrix. An initial root package step installs Git and CA certificates before checkout. The job then installs the Qt 6, Wayland, LayerShellQt, compiler, and virtual display dependencies needed to compile and load Kotonoha's native bridge. Each matrix member installs the project from the locked dependency graph with its test extras, inspects the generated `libkoto-layer.so` with `ldd`, requires Qt6Core, Qt6Gui, and LayerShellQt linkage, rejects Qt 5 linkage, and loads the library through `ctypes.CDLL` without calling GUI functions. The essential command sequence is:

```text
uv sync --locked --extra test
xvfb-run -a uv run pytest
uv run ruff check .
uv run ty check
```

The Cider job uses Node.js 20 and the exact pnpm release declared by the plugin's `packageManager` field. It runs:

```text
pnpm install --frozen-lockfile
pnpm test
pnpm build
```

The job then verifies that the build produced both `plugin.js` and `plugin.yml`. Python and Cider remain separate jobs so a failure clearly identifies the affected subsystem.

The workflow receives read-only repository permissions. Its `workflow_call` interface exposes a `release_validation` boolean that defaults to false. Ordinary branch, pull-request, and reusable runs use a workflow-and-ref concurrency group with cancellation enabled so obsolete CI does not consume runner time. Release callers pass `release_validation: true`, which places the run in a workflow-and-run-ID group and disables cancellation so release validation cannot collide with or be canceled by ordinary CI.

Every external action is pinned to the immutable commit behind its requested release tag, with the human-readable tag retained as an inline comment. `setup-uv` additionally installs exactly uv 0.11.19, and the Cider job continues to install exactly pnpm 9.10.0.

### Package Workflow

`.github/workflows/package.yml` supports `v*` tag pushes and `workflow_dispatch`.

Its first job invokes `test.yml` through `workflow_call` with `release_validation: true`. DEB, RPM, wheel, and Cider package jobs depend on that reusable test workflow, so a tag cannot publish artifacts without passing the same checks used for pull requests.

The four package jobs run in parallel after validation. Each uploads a separately named Actions artifact. A final assembly job downloads all artifacts, verifies the expected files, generates `SHA256SUMS`, and uploads the combined release bundle.

For a tag, a release job creates a GitHub Release with generated release notes and all verified files. The release job alone receives `contents: write`; all other jobs remain read-only. `fail_on_unmatched_files` or an equivalent explicit file check prevents a partial release.

For a manual dispatch, including one launched with a tag selected as its ref, the workflow stops after uploading the combined Actions artifact and does not create a GitHub Release. Release/tag jobs do not use cancellation concurrency.

## Version Contract

A tag matching canonical `vX.Y.Z` is the authoritative version for every artifact in that release. Each component is ASCII digits and is either `0` or begins with `1`-`9`, so multi-digit components cannot have a leading zero. The leading `v` is removed before passing the version to the DEB, RPM, wheel, and Cider builds. Manual builds apply the same canonical rule to `project.version`.

For `workflow_dispatch`, the authoritative version is `project.version` from `pyproject.toml`, even when the operator selects a tag ref. Only a tag push passes `ref_type=tag` to the version resolver.

The resolved version is computed once in the package workflow and passed to all package jobs. This prevents artifact versions from diverging inside one run.

The Cider plugin's generated manifest receives the resolved release version at build time rather than retaining the development value in `src/plugin.config.ts`. Normal local builds continue to use the checked-in development version when no release version environment variable is present.

## Linux Desktop Integration

`packaging/kotonoha.desktop` is the single desktop entry installed by both native package formats. It uses localized keys matching Kotonoha's supported UI languages:

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

The exact localized file is checked with `desktop-file-validate`. Packages install it to `/usr/share/applications/kotonoha.desktop` and install `src/kotonoha/assets/icon.png` as `/usr/share/pixmaps/kotonoha.png`.

## DEB Packaging

The DEB build runs in an Ubuntu 26.04 container with Bash selected explicitly for every `run` step and adds:

- `packaging/debian/control` for build and runtime dependencies;
- `packaging/debian/rules` using `pybuild` with the PEP 517 backend;
- `packaging/debian/install` for the desktop entry and icon;
- `packaging/debian/changelog` as the checked-in base changelog.

The workflow uses the pinned `setup-uv` action with uv 0.11.19 only to run `uv version "$VERSION" --frozen`, copies `packaging/debian` to the repository-root `debian` directory, updates the changelog to the resolved version, and builds an unsigned binary package with `debuild`.

Qt 6, PyQt6, Wayland, LayerShellQt, aiohttp, qasync, and dbus-fast are represented as system build/runtime dependencies rather than bundled Qt libraries. `dh-sequence-python3` activates `dh_python3` so `${python3:Depends}` is populated. Before pybuild configures the PEP 517 backend, `debian/rules` saves the original `pyproject.toml` under `debian/`, removes the optional Hatch build-script hook from the package build tree, compiles the native bridge explicitly with `USE_SYSTEM_LIBS=1`, and then resumes the normal pybuild configure/build sequence. Its clean override removes the generated bridge and restores the original file exactly before calling `dh_clean`. This keeps the package build self-contained and links the bridge against the target distribution's Qt and LayerShellQt ABI without leaving source-tree changes behind.

After building, the container installs the generated DEB and verifies:

- `python3 -c "import kotonoha.main"` succeeds;
- the `kotonoha` executable exists;
- the installed package contains `libkoto-layer.so`;
- the desktop file and pixmap exist in their expected locations;
- `desktop-file-validate` succeeds.

Only a DEB that passes these installation checks is uploaded.

## RPM Packaging

The RPM build runs in a Fedora 43 container with Bash selected explicitly for every `run` step and adds `packaging/fedora/kotonoha.spec`.

The workflow uses the pinned `setup-uv` action with uv 0.11.19 only to run `uv version "$VERSION" --frozen`, creates a source archive named for the resolved version, updates both the spec `Version:` header and the single `%changelog` release to `${VERSION}-1`, and invokes `rpmbuild`. During `%prep`, the spec removes the optional Hatch build-script hook from the package build tree. During `%build`, it compiles the native bridge explicitly with `USE_SYSTEM_LIBS=1` before invoking Fedora's Python wheel macro. The existing wheel force-include packages the manually built library without relying on files installed outside the declared RPM build requirements.

Qt 6, PyQt6, Wayland, LayerShellQt, aiohttp, qasync, and dbus-fast are declared as system build/runtime requirements. After building, the container installs the generated RPM and performs the same import, executable, native library, desktop file, icon, and desktop validation checks as the DEB job.

Only an RPM that passes these installation checks is uploaded.

## Wheel Packaging

The wheel job runs in an Ubuntu 26.04 container with Bash selected explicitly, Python 3.14, the pinned `setup-uv` action at uv 0.11.19, and the native bridge build requirements. It applies the resolved version with `uv version "$VERSION" --frozen`, builds the project, and includes `libkoto-layer.so` and all application icon assets.

Because the wheel contains a native Linux shared library, it must be both non-pure and platform-specific. With pinned wheel 0.45.1, the job unpacks the sole Hatch wheel, requires exactly one unpacked distribution and one `.dist-info/WHEEL`, changes the single `Root-Is-Purelib: true` field to `Root-Is-Purelib: false`, removes the original wheel, and repacks it into a clean output directory so `RECORD` is regenerated. It then retags the repacked wheel with `wheel tags --remove --platform-tag linux_x86_64`, moves only that final wheel to the artifact directory, requires exactly one `linux_x86_64` wheel and no `any` wheel, and verifies both the non-pure field and platform tag in `WHEEL`. It also inspects the bridge with `ldd`, requires Qt 6 and LayerShellQt linkage, and rejects Qt 5 linkage.

The job installs the wheel and its dependencies into a clean virtual environment, imports PyQt6's QtCore and QtGui modules before importing Kotonoha, locates the installed bridge, and loads it with `ctypes.CDLL`. The artifact is deliberately a Linux x86_64 wheel, not a manylinux compatibility claim and not a Windows or macOS package.

## Cider Plugin Package

The Cider package job installs dependencies from the committed lockfile, injects the resolved version, runs the plugin tests, and performs a production Vite build.

It verifies `plugin.js` and `plugin.yml`, then creates:

```text
kotonoha-cider-lyrics-X.Y.Z.zip
└── dev.locez.kotonoha.cider.lyrics/
    ├── plugin.js
    └── plugin.yml
```

This layout allows users to extract the archive directly into Cider's `plugins` directory. No source files, dependency tree, or Vite output outside the installable plugin directory are included.

## Artifact Assembly

The release assembly expects exactly these artifact classes:

- one DEB;
- one RPM;
- one Linux x86_64 wheel;
- one versioned Cider ZIP.

It computes SHA-256 checksums over the final files and writes `SHA256SUMS`. Missing or duplicate expected artifact classes fail the workflow before release creation.

Actions artifacts use descriptive names such as `kotonoha-deb`, `kotonoha-rpm`, `kotonoha-wheel`, and `kotonoha-cider-plugin`. The final combined artifact is retained for manual runs as well as tag runs.

## Documentation

The root README gains a Release Packages section that explains:

- which artifacts are produced;
- how tag versions and manual versions are selected;
- how to install DEB and RPM files;
- that the wheel is Linux x86_64 and still requires compatible system Qt/LayerShellQt libraries;
- how to extract the Cider ZIP;
- that the Cider integration remains experimental;
- how maintainers trigger a release with a `vX.Y.Z` tag or run a package build manually.

## Failure Policy

The workflow fails early on dependency installation, bridge compilation, lint, type checking, tests, plugin output validation, package installation, desktop validation, wheel platform validation, or missing release artifacts.

No job silently downgrades a failed check to a warning. No GitHub Release is created unless every required artifact was successfully built, installed or inspected as appropriate, assembled, and checksummed.

## Acceptance Criteria

- A pull request runs Python 3.10-3.14 validation and Cider validation.
- A failing Python or Cider test prevents package jobs from starting.
- A `vX.Y.Z` tag produces version-consistent DEB, RPM, Linux wheel, Cider ZIP, and `SHA256SUMS` files.
- A manual dispatch, including one run against a tag ref, uses `project.version`, produces the same Actions artifacts, and does not create a GitHub Release.
- The DEB and RPM install successfully in their build containers and expose the application command, bridge, desktop file, and icon.
- Desktop metadata is valid and localized for English, Simplified Chinese, Traditional Chinese, and Japanese.
- The Cider ZIP can be extracted directly under Cider's plugin directory.
- The wheel is not labelled as a platform-independent package.
- Release creation is skipped when any required validation or artifact is missing.
