# CMake Wheel Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Wayland bridge with CMake during Python wheel creation, install it as `kotonoha/libkoto-layer.so`, and preserve the existing shell-based DEB/RPM builds.

**Architecture:** CMake owns native dependency discovery, compilation, and component installation. The Hatch hook configures and builds out of source, then installs only the bridge component into `src/kotonoha` as wheel staging; the existing `force-include` mapping places it beside the Python modules. Debian and Fedora continue removing the Hatch hook and invoking `build_bridge.sh`.

**Tech Stack:** CMake, C++17, Qt 6 private CMake targets, LayerShellQt, pkg-config, Wayland, Hatchling, hatch-build-scripts, pytest, GitHub Actions.

---

### Task 1: Add the CMake bridge target and install contract

**Files:**
- Create: `CMakeLists.txt`
- Modify: `tests/test_native_packaging.py`
- Test: `tests/test_native_packaging.py`

- [ ] **Step 1: Write the failing CMake contract test**

Add the constant and test below to `tests/test_native_packaging.py`:

```python
CMAKE_PROJECT = PROJECT_ROOT / "CMakeLists.txt"


def test_cmake_builds_and_installs_native_bridge() -> None:
    cmake = read_packaging_file(CMAKE_PROJECT)

    assert_contains(
        cmake,
        (
            "project(kotonoha_native_bridge LANGUAGES CXX)",
            "find_package(Python3 REQUIRED COMPONENTS Interpreter)",
            "find_package(Qt6 REQUIRED COMPONENTS Core Gui)",
            "find_package(Qt6GuiPrivate REQUIRED)",
            "find_package(LayerShellQt CONFIG REQUIRED)",
            "pkg_check_modules(WaylandClient REQUIRED IMPORTED_TARGET wayland-client)",
            "add_library(koto-layer SHARED src/kotonoha/layer_shell_bridge.cpp)",
            "Qt6::GuiPrivate",
            "LayerShellQt::Interface",
            "PkgConfig::WaylandClient",
            'OUTPUT_NAME "koto-layer"',
            'LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}"',
            'option(KOTONOHA_STATIC_GNU_RUNTIME',
            "KOTONOHA_INSTALL_DIR",
            '"${KOTONOHA_PYTHON_PLATLIB}/kotonoha"',
            "CACHE STRING",
            "COMPONENT KotonohaBridge",
            "COMPONENT KotonohaDocumentation",
        ),
    )
    assert "src/kotonoha/build_bridge.sh" not in cmake
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run pytest \
  tests/test_native_packaging.py::test_cmake_builds_and_installs_native_bridge -q
```

Expected: FAIL with `FileNotFoundError` for `CMakeLists.txt`.

- [ ] **Step 3: Implement the root CMake project**

Create `CMakeLists.txt` with this content:

```cmake
cmake_minimum_required(VERSION 3.20)

project(kotonoha_native_bridge LANGUAGES CXX)

include(GNUInstallDirs)
find_package(PkgConfig REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(Qt6GuiPrivate REQUIRED)
find_package(LayerShellQt CONFIG REQUIRED)
pkg_check_modules(WaylandClient REQUIRED IMPORTED_TARGET wayland-client)

execute_process(
  COMMAND
    "${Python3_EXECUTABLE}" -c
    "import sysconfig; print(sysconfig.get_path('platlib', vars={'base': '', 'platbase': ''}).lstrip('/'))"
  RESULT_VARIABLE KOTONOHA_PYTHON_PLATLIB_RESULT
  OUTPUT_VARIABLE KOTONOHA_PYTHON_PLATLIB
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_VARIABLE KOTONOHA_PYTHON_PLATLIB_ERROR
)
if(NOT KOTONOHA_PYTHON_PLATLIB_RESULT EQUAL 0 OR KOTONOHA_PYTHON_PLATLIB STREQUAL "")
  message(FATAL_ERROR "Unable to determine Python platlib: ${KOTONOHA_PYTHON_PLATLIB_ERROR}")
endif()
file(TO_CMAKE_PATH "${KOTONOHA_PYTHON_PLATLIB}" KOTONOHA_PYTHON_PLATLIB)

set(
  KOTONOHA_INSTALL_DIR
  "${KOTONOHA_PYTHON_PLATLIB}/kotonoha"
  CACHE STRING
  "Prefix-relative directory for the installed native bridge"
)
option(
  KOTONOHA_STATIC_GNU_RUNTIME
  "Link libstdc++ and libgcc statically when building with GNU C++"
  ON
)

add_library(koto-layer SHARED src/kotonoha/layer_shell_bridge.cpp)
target_compile_features(koto-layer PRIVATE cxx_std_17)
set_target_properties(
  koto-layer
  PROPERTIES
    CXX_EXTENSIONS OFF
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
    LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}"
    LIBRARY_OUTPUT_DIRECTORY_MINSIZEREL "${CMAKE_BINARY_DIR}"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}"
    LIBRARY_OUTPUT_DIRECTORY_RELWITHDEBINFO "${CMAKE_BINARY_DIR}"
    OUTPUT_NAME "koto-layer"
)
target_link_libraries(
  koto-layer
  PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::GuiPrivate
    LayerShellQt::Interface
    PkgConfig::WaylandClient
)

if(KOTONOHA_STATIC_GNU_RUNTIME AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
  target_link_options(koto-layer PRIVATE -static-libstdc++ -static-libgcc)
endif()

install(
  TARGETS koto-layer
  LIBRARY DESTINATION "${KOTONOHA_INSTALL_DIR}"
  COMPONENT KotonohaBridge
)
install(
  FILES "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE"
  DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/licenses/kotonoha"
  COMPONENT KotonohaDocumentation
)
```

- [ ] **Step 4: Run the contract test and verify GREEN**

Run the same focused pytest command from Step 2.

Expected: PASS.

- [ ] **Step 5: Verify a real out-of-source build and default install**

Run:

```bash
cmake_build=$(mktemp -d)
cmake_prefix=$(mktemp -d)
cmake -S . -B "$cmake_build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$(command -v python3)"
cmake --build "$cmake_build" --config Release
test -f "$cmake_build/libkoto-layer.so"
cmake --install "$cmake_build" --config Release --prefix "$cmake_prefix" --component KotonohaBridge
find "$cmake_prefix" -type f -path '*/site-packages/kotonoha/libkoto-layer.so' | grep -q .
```

Expected: configure/build/install exit 0 and one bridge exists below the temporary Python `platlib`.

- [ ] **Step 6: Commit the CMake target**

```bash
git add CMakeLists.txt tests/test_native_packaging.py
git commit -m "feat(build): add CMake native bridge target"
```

### Task 2: Make Hatch stage the CMake bridge for wheels

**Files:**
- Modify: `pyproject.toml:8-13`
- Modify: `tests/test_native_packaging.py`
- Test: `tests/test_native_packaging.py`

- [ ] **Step 1: Write the failing Hatch integration test**

Add this test to `tests/test_native_packaging.py`:

```python
def test_hatch_hook_stages_cmake_bridge_for_wheel() -> None:
    pyproject = tomllib.loads(read_packaging_file(PROJECT_ROOT / "pyproject.toml"))
    script = pyproject["tool"]["hatch"]["build"]["hooks"]["build-scripts"]["scripts"][0]

    assert script["commands"] == [
        "cmake -S . -B build/hatch-cmake -DCMAKE_BUILD_TYPE=Release -DKOTONOHA_INSTALL_DIR=src/kotonoha",
        "cmake --build build/hatch-cmake --config Release",
        'cmake --install build/hatch-cmake --config Release --prefix "$PWD" --component KotonohaBridge',
    ]
    assert script["artifacts"] == ["src/kotonoha/libkoto-layer.so"]
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "src/kotonoha/libkoto-layer.so": "kotonoha/libkoto-layer.so"
    }
    assert (PROJECT_ROOT / "src" / "kotonoha" / "build_bridge.sh").is_file()
```

- [ ] **Step 2: Run the Hatch test and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run pytest \
  tests/test_native_packaging.py::test_hatch_hook_stages_cmake_bridge_for_wheel -q
```

Expected: FAIL because the current hook command is `bash src/kotonoha/build_bridge.sh`.

- [ ] **Step 3: Replace the Hatch command with CMake staging commands**

Change the existing build hook in `pyproject.toml` to:

```toml
[tool.hatch.build.hooks.build-scripts]
[[tool.hatch.build.hooks.build-scripts.scripts]]
commands = [
  "cmake -S . -B build/hatch-cmake -DCMAKE_BUILD_TYPE=Release -DKOTONOHA_INSTALL_DIR=src/kotonoha",
  "cmake --build build/hatch-cmake --config Release",
  "cmake --install build/hatch-cmake --config Release --prefix \"$PWD\" --component KotonohaBridge",
]
artifacts = ["src/kotonoha/libkoto-layer.so"]
```

Do not change the `force-include` mapping or build-system requirements.

- [ ] **Step 4: Verify Hatch and native-package compatibility**

Run:

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run pytest tests/test_native_packaging.py -q
```

Expected: all tests pass, including the Debian/Fedora tests that remove the Hatch hook and retain the
shell-built `src/kotonoha/libkoto-layer.so` path.

- [ ] **Step 5: Verify the hook stages a real CMake artifact**

Run:

```bash
wheel_dir=$(mktemp -d)
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv build --wheel --out-dir "$wheel_dir"
test -f src/kotonoha/libkoto-layer.so
WHEEL_DIR="$wheel_dir" python3 - <<'PY'
import os
from pathlib import Path
from zipfile import ZipFile

wheel = next(Path(os.environ["WHEEL_DIR"]).glob("*.whl"))
with ZipFile(wheel) as archive:
    assert archive.namelist().count("kotonoha/libkoto-layer.so") == 1
PY
```

Expected: wheel build succeeds and contains exactly one bridge at the package-relative path.

- [ ] **Step 6: Commit the Hatch integration**

```bash
git add pyproject.toml tests/test_native_packaging.py
git commit -m "build(python): stage CMake bridge for wheels"
```

### Task 3: Document and enforce the CMake wheel path in CI

**Files:**
- Modify: `README.md:22-55`
- Modify: `.github/workflows/test.yml:53-97`
- Modify: `.github/workflows/package.yml:242-356`
- Modify: `tests/test_native_packaging.py`
- Test: `tests/test_native_packaging.py`

- [ ] **Step 1: Write the failing documentation and CI contract test**

Add `TEST_WORKFLOW` beside `PACKAGE_WORKFLOW`, then add this test:

```python
TEST_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "test.yml"


def test_cmake_is_documented_and_verified_by_ci() -> None:
    readme = read_packaging_file(PROJECT_ROOT / "README.md")
    test_workflow = read_packaging_file(TEST_WORKFLOW)
    package_workflow = read_packaging_file(PACKAGE_WORKFLOW)

    assert "cmake -S . -B build/cmake" in readme
    assert "cmake --build build/cmake" in readme
    assert "cmake --install build/cmake --config Release" in readme
    assert "build_bridge.sh" in readme
    assert "Verify standalone CMake install" in test_workflow
    assert "-DCMAKE_BUILD_TYPE=Release" in test_workflow
    assert 'cmake --build "$cmake_build" --config Release' in test_workflow
    assert 'cmake --install "$cmake_build" --config Release' in test_workflow
    assert "--component KotonohaBridge" in test_workflow
    assert test_workflow.count("            cmake \\") >= 1
    assert package_workflow.count("            cmake \\") >= 1
    assert 'archive.namelist().count("kotonoha/libkoto-layer.so")' in package_workflow
```

- [ ] **Step 2: Run the CI contract test and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run pytest \
  tests/test_native_packaging.py::test_cmake_is_documented_and_verified_by_ci -q
```

Expected: FAIL because README and workflows do not yet mention the CMake path.

- [ ] **Step 3: Add CMake to source-build prerequisites**

Add `cmake` to the apt dependency lists in the Python test job and Linux wheel job. Update README package
commands to install CMake on every documented distribution:

```bash
# Arch
sudo pacman -S cmake qt6-base qt6-wayland layer-shell-qt
# Fedora
sudo dnf install cmake qt6-qtbase-devel layer-shell-qt-devel wayland-devel gcc-c++
# Debian/Ubuntu
sudo apt install cmake qt6-base-dev qt6-base-private-dev libwayland-dev liblayershellqt-dev build-essential
# Gentoo
sudo emerge -a dev-build/cmake kde-plasma/layer-shell-qt dev-qt/qtwayland
```

- [ ] **Step 4: Document build, install, wheel, and fallback commands**

Replace the README statement that Hatch invokes `build_bridge.sh`. State that `uv sync` uses CMake and
that prebuilt wheels do not require build tools. Include:

```bash
cmake -S . -B build/cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/cmake --config Release
cmake --install build/cmake --config Release --prefix "$PWD/.venv" --component KotonohaBridge
uv build --wheel
```

Keep `bash src/kotonoha/build_bridge.sh` documented as the manual fallback.

- [ ] **Step 5: Add the standalone CMake install smoke test**

After the existing native linkage check in `.github/workflows/test.yml`, add:

```yaml
      - name: Verify standalone CMake install
        run: |
          set -euo pipefail
          cmake_build=$(mktemp -d)
          cmake_prefix=$(mktemp -d)
          cmake -S . -B "$cmake_build" \
            -DCMAKE_BUILD_TYPE=Release \
            -DPython3_EXECUTABLE="$(command -v python)"
          cmake --build "$cmake_build" --config Release
          cmake --install "$cmake_build" --config Release \
            --prefix "$cmake_prefix" \
            --component KotonohaBridge
          mapfile -t bridges < <(
            find "$cmake_prefix" -type f \
              -path '*/site-packages/kotonoha/libkoto-layer.so' -print
          )
          test "${#bridges[@]}" -eq 1
          uv run python -c "import ctypes; ctypes.CDLL('${bridges[0]}')"
```

- [ ] **Step 6: Assert the final wheel contains the bridge**

Inside the existing `ZipFile` block in the wheel verification Python snippet, add:

```python
              if archive.namelist().count("kotonoha/libkoto-layer.so") != 1:
                  raise SystemExit("wheel must contain exactly one kotonoha/libkoto-layer.so")
```

- [ ] **Step 7: Run the focused test and verify GREEN**

Run:

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run pytest tests/test_native_packaging.py -q
```

Expected: all native packaging tests pass.

- [ ] **Step 8: Commit docs and CI coverage**

```bash
git add README.md .github/workflows/test.yml .github/workflows/package.yml tests/test_native_packaging.py
git commit -m "test(build): verify CMake wheel installation"
```

### Task 4: Run end-to-end verification

**Files:**
- Verify only; no planned file changes.

- [ ] **Step 1: Run the complete Python quality suite**

```bash
UV_CACHE_DIR=/tmp/kotonoha-uv-cache xvfb-run -a uv run pytest
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv run ty check
```

Expected: all tests, lint checks, and type checks pass.

- [ ] **Step 2: Build a fresh wheel and inspect its installed layout**

```bash
wheel_dir=$(mktemp -d)
venv_dir=$(mktemp -d)
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv build --wheel --out-dir "$wheel_dir"
wheel=$(find "$wheel_dir" -maxdepth 1 -name '*.whl' -print -quit)
test -n "$wheel"
python3 - "$wheel" <<'PY'
import sys
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as archive:
    assert archive.namelist().count("kotonoha/libkoto-layer.so") == 1
PY
python3 -m venv "$venv_dir"
UV_CACHE_DIR=/tmp/kotonoha-uv-cache uv pip install --no-deps --python "$venv_dir/bin/python" "$wheel"
"$venv_dir/bin/python" - <<'PY'
import ctypes
from pathlib import Path

import kotonoha
from kotonoha.lyrics_loader import find_layer_shell_library

bridge = find_layer_shell_library(Path(kotonoha.__file__).parent)
assert bridge is not None
ctypes.CDLL(bridge)
PY
```

Expected: the wheel contains one bridge, installation succeeds without build tools, and the installed
bridge loads from the package directory.

- [ ] **Step 3: Review the final diff and repository state**

```bash
git diff --check
git status --short
git log -6 --oneline
```

Expected: no uncommitted implementation changes and three focused implementation commits.
