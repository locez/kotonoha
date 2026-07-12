# Optional CMake Native Bridge Design

## Goal

Add a supported CMake build and install path for `libkoto-layer.so` without removing or replacing
`src/kotonoha/build_bridge.sh`. The existing Hatch, DEB, and RPM build paths remain unchanged.

## Scope

The change adds:

- a root `CMakeLists.txt` for the existing `src/kotonoha/layer_shell_bridge.cpp` source;
- an out-of-source build that produces `build/cmake/libkoto-layer.so`;
- a relocatable install rule that places the bridge beside the installed `kotonoha` Python package;
- README instructions for configuring, building, and installing with CMake;
- a CI smoke test that configures, builds, installs, and loads the CMake-produced library.

The change does not modify the bridge API, Python loading behavior, Hatch build hook, native package
builds, or the existing shell build script.

## CMake Target

The root project defines one shared-library target from `src/kotonoha/layer_shell_bridge.cpp`. Its
output name is `libkoto-layer.so`, matching the existing shell build and Python loader contract.

The target uses C++17 without compiler extensions and links imported targets for:

- `Qt6::Core`;
- `Qt6::Gui`;
- `Qt6::GuiPrivate`, which supplies the versioned private GUI headers;
- `LayerShellQt::Interface`;
- the `wayland-client` pkg-config module.

Configuration fails with the dependency-specific diagnostics supplied by CMake, Qt, LayerShellQt,
or pkg-config. CMake does not reproduce the shell script's distribution package suggestions.

## GNU Runtime Linking

The cache option `KOTONOHA_STATIC_GNU_RUNTIME` defaults to `ON`, matching the shell script's default
`-static-libstdc++ -static-libgcc` behavior. Those flags are applied only when the compiler is GNU.
Setting the option to `OFF` produces the dynamic runtime linkage used by native distribution packages.

## Build And Install Layout

The documented build is out of source:

```bash
cmake -S . -B build/cmake
cmake --build build/cmake
```

The uninstalled artifact remains in `build/cmake/libkoto-layer.so`; CMake never writes build output
into `src/kotonoha`.

The bridge is private platform-dependent Python package data, so its final install destination is the
selected interpreter's relative `platlib` directory plus `kotonoha`. CMake finds a Python interpreter
and asks `sysconfig` for the prefix-relative `platlib` path. For example, Python 3.14 commonly yields:

```text
lib/python3.14/site-packages/kotonoha/libkoto-layer.so
```

The relative destination preserves `cmake --install --prefix`, `DESTDIR`, and packaging staging.
`KOTONOHA_INSTALL_DIR` is a cache variable so a distribution can override the interpreter-derived
default. When the install prefix is a virtual environment, configuration must select that environment's
interpreter so the Python version and install scheme match. These commands install the bridge into the
project virtual environment:

```bash
cmake -S . -B build/cmake -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/cmake
cmake --install build/cmake --prefix "$PWD/.venv"
```

The CMake install also places the project `LICENSE` under the conventional
`${CMAKE_INSTALL_DATAROOTDIR}/licenses/kotonoha` directory.

## Existing Build Paths

`src/kotonoha/build_bridge.sh` remains executable and unchanged. `pyproject.toml` continues to call
it through `hatch-build-scripts`; Debian and Fedora continue to invoke it with `USE_SYSTEM_LIBS=1`.
The CMake path is an additional developer and integrator interface, not a packaging backend migration.

## Validation

The Python packaging tests assert the stable CMake contract: target inputs, imported dependencies,
output name, relative Python install destination, runtime option, and preservation of the shell path.

The Python CI job installs CMake and performs a smoke test after the existing shell-built bridge check:

1. configure into a temporary build directory;
2. build `libkoto-layer.so`;
3. verify Qt, Wayland, and LayerShellQt linkage with `ldd`;
4. install into a temporary prefix;
5. locate the installed bridge under that prefix and load it with `ctypes.CDLL`.

This validates the optional path without changing release artifacts or compiling CMake output into the
source package.
