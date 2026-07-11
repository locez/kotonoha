# Release Package CI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the Ubuntu DEB, Fedora RPM, and Linux wheel jobs produce installable artifacts and verify their real runtime dependency contracts.

**Architecture:** Keep distro packages linked to distro Qt. Bundle only Fedora's missing pure-Python qasync dependency inside the RPM, with a pinned PyPI URL/hash and explicit bundled provider. Keep the Linux wheel tied to the Ubuntu build image's Qt minor ABI by rewriting its PyQt requirements during repacking; retain the clean-environment native load test.

**Tech Stack:** GitHub Actions, Bash, RPM spec macros, Python wheel metadata, `email`/`packaging`, pytest, Qt 6/PyQt6.

---

### Task 1: Encode the failing package contracts

**Files:**
- Modify: `tests/test_native_packaging.py`
- Create: `tests/test_wheel_metadata.py`

- [x] **Step 1: Add failing DEB and RPM assertions**

Assert that the DEB workflow installs `./${debs[0]}`, Fedora uses `python3-pyqt6`, and qasync 0.28.0 is fetched by its locked URL/SHA-256 and declared as a bundled RPM provider rather than an unavailable Fedora requirement.

- [x] **Step 2: Add failing wheel metadata tests**

Create a temporary unpacked wheel with `Root-Is-Purelib: true` and `Requires-Dist: PyQt6`, invoke `patch_linux_wheel_metadata()`, and assert:

```text
Root-Is-Purelib: false
Requires-Dist: PyQt6<6.11,>=6.10
Requires-Dist: PyQt6-Qt6<6.11,>=6.10
```

Also reject malformed Qt versions, duplicate metadata files, and missing PyQt6 requirements.

- [x] **Step 3: Run the focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_native_packaging.py tests/test_wheel_metadata.py -q`

Expected: failures for the current DEB path, Fedora dependency declarations, and missing wheel metadata helper.

### Task 2: Fix DEB and make Fedora RPM self-contained

**Files:**
- Modify: `.github/workflows/package.yml`
- Modify: `packaging/fedora/kotonoha.spec`

- [x] **Step 1: Fix local package installation paths**

Install DEB and RPM artifacts through explicit local paths (`./...`) so apt/dnf do not interpret them as repository package names.

- [x] **Step 2: Correct Fedora's PyQt package name**

Replace `python3-qt6` with Fedora 43's `python3-pyqt6` in workflow dependencies and RPM runtime requirements.

- [x] **Step 3: Stage and verify qasync**

Download `qasync-0.28.0-py3-none-any.whl` from the URL already locked in `uv.lock`, verify SHA-256 `21faba8d047c717008378f5ac29ea58c32a8128528629e4afd57c59b768dba0f`, and place it in RPM `SOURCES`.

- [x] **Step 4: Bundle qasync in the RPM**

Add the wheel as `Source1`, extract it under `%{python3_sitelib}` during `%install`, list its package/dist-info files, preserve its license, remove the unavailable `python3-qasync` requirement, and declare:

```spec
Provides:       bundled(python3dist(qasync)) = 0.28.0
```

- [x] **Step 5: Run focused packaging tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_native_packaging.py -q`

Expected: all native packaging tests pass.

### Task 3: Bind the Linux wheel to its Qt minor ABI

**Files:**
- Create: `scripts/patch_linux_wheel_metadata.py`
- Modify: `.github/workflows/package.yml`
- Test: `tests/test_wheel_metadata.py`

- [x] **Step 1: Implement structured metadata rewriting**

Parse `major.minor.patch`, derive the next minor boundary, require exactly one `WHEEL` and `METADATA`, change `Root-Is-Purelib` to false, replace the single PyQt6 requirement, and add a matching PyQt6-Qt6 requirement while preserving all unrelated dependencies.

- [x] **Step 2: Use the build image Qt version**

Read `qmake6 -query QT_VERSION` in the wheel job and run the helper against the unpacked wheel before repacking and retagging.

- [x] **Step 3: Strengthen clean-environment verification**

After installation, assert PyQt's `QT_VERSION_STR` has the same major/minor as the build Qt before loading `libkoto-layer.so` with `ctypes.CDLL`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_wheel_metadata.py -q`

Expected: all metadata rewrite and validation cases pass.

### Task 4: Document and validate release contracts

**Files:**
- Modify: `README.md`

- [x] **Step 1: Document RPM bundling and wheel ABI scope**

State that the Fedora RPM bundles pinned qasync because Fedora does not package it, and that the wheel is tied to the Qt minor version used by Ubuntu 26.04 rather than generic system Qt 6.

- [x] **Step 2: Run complete verification**

Run:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ty check
actionlint .github/workflows/package.yml
git diff --check
```

Expected: 0 failures. If `actionlint` is unavailable, parse the workflow as YAML and report that limitation explicitly.

- [x] **Step 3: Commit the release fixes**

```bash
git add .github/workflows/package.yml packaging/fedora/kotonoha.spec scripts/patch_linux_wheel_metadata.py tests/test_native_packaging.py tests/test_wheel_metadata.py README.md docs/superpowers/plans/2026-07-11-release-package-ci-fixes.md
git commit -m "fix(release): make native packages installable"
```
