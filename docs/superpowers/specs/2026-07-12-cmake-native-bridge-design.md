# CMake Native Bridge Wheel Build Design

## Goal

Build `libkoto-layer.so` with CMake when producing the Python wheel, package it beside the `kotonoha`
Python modules, and make an installed wheel directly usable on compatible Linux systems. Preserve
`src/kotonoha/build_bridge.sh` for the existing DEB/RPM builds and as a manual fallback.

## Scope

The change adds:

- a root `CMakeLists.txt` for the existing `src/kotonoha/layer_shell_bridge.cpp` source;
- an out-of-source build that produces `build/cmake/libkoto-layer.so`;
- relocatable CMake install rules for the bridge and project license;
- a Hatch build hook that builds with CMake and stages the bridge at
  `src/kotonoha/libkoto-layer.so` for wheel collection;
- README instructions for configuring, building, installing, and building a wheel with CMake;
- CI checks for the CMake build, CMake install, wheel contents, and clean wheel installation.

The change does not modify the bridge API, Python loading behavior, wheel platform compatibility,
or the existing DEB/RPM build commands. The shell build script remains executable and unchanged.

## CMake Target

The root project defines one shared-library target from `src/kotonoha/layer_shell_bridge.cpp`. Its
output name is `libkoto-layer.so`, matching the existing shell build, wheel layout, and Python loader
contract.

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
Setting the option to `OFF` produces the dynamic GNU runtime linkage used by native distribution
packages.

## Build And Install Layout

The normal CMake build is out of source:

```bash
cmake -S . -B build/cmake
cmake --build build/cmake
```

The compiled artifact remains at `build/cmake/libkoto-layer.so`. CMake does not place compiler output
or object files in `src/kotonoha`.

For standalone installation, the bridge is private platform-dependent Python package data. Its default
destination is the selected interpreter's relative `platlib` directory plus `kotonoha`. CMake finds a
Python interpreter and asks `sysconfig` for the prefix-relative `platlib` path. Python 3.14 commonly
yields:

```text
lib/python3.14/site-packages/kotonoha/libkoto-layer.so
```

The relative destination preserves `cmake --install --prefix`, `DESTDIR`, and packaging staging.
`KOTONOHA_INSTALL_DIR` is a cache variable so build integrations and distributions can override the
interpreter-derived default. When installing into a virtual environment, configuration selects that
environment's interpreter:

```bash
cmake -S . -B build/cmake -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/cmake
cmake --install build/cmake --prefix "$PWD/.venv"
```

The bridge install belongs to the `KotonohaBridge` component. The project `LICENSE` installs under
`${CMAKE_INSTALL_DATAROOTDIR}/licenses/kotonoha` in a separate `KotonohaDocumentation` component.

## Hatch And Wheel Integration

The Hatch build hook replaces its direct shell-script command with three CMake stages:

1. configure `build/cmake` as a Release build with `KOTONOHA_INSTALL_DIR=src/kotonoha`;
2. build `build/cmake/libkoto-layer.so`;
3. install only the `KotonohaBridge` component with the repository root as the install prefix.

The third stage copies the finished library to `src/kotonoha/libkoto-layer.so`. This is a packaging
staging artifact, not compiler output. The existing Hatch mapping remains:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/kotonoha/libkoto-layer.so" = "kotonoha/libkoto-layer.so"
```

The resulting wheel therefore contains exactly `kotonoha/libkoto-layer.so`. After pip installs the
wheel, the library is adjacent to `lyrics_loader.py`, so the current package-directory lookup works
without a new search path. Installing a prebuilt wheel does not require CMake, a compiler, or development
headers; the target system still needs compatible Qt, Wayland, and LayerShellQt runtime libraries as
described by the existing Linux wheel compatibility contract.

## Existing Shell And Native Package Paths

`src/kotonoha/build_bridge.sh` remains executable and unchanged. Debian and Fedora continue to remove
the Hatch build hook from `pyproject.toml`, invoke the script with `USE_SYSTEM_LIBS=1`, and place its
`src/kotonoha/libkoto-layer.so` output into their packages. Their build and install layouts do not move.

The Python build-system requirements remain `hatchling` and `hatch-build-scripts`. CMake is a system
build prerequisite for source-tree Python builds and is installed explicitly in CI; it is not a runtime
Python dependency and is not required when installing a prebuilt wheel.

## Validation

Focused Python packaging tests assert the stable contract:

- the CMake target sources and imported dependencies;
- the output name, runtime-link option, and component install rules;
- the prefix-relative default Python install destination;
- the Hatch configure/build/install commands and unchanged wheel `force-include` destination;
- preservation of the shell script and the DEB/RPM hook-removal paths.

The Python CI job installs CMake. Its normal `uv sync` exercises the Hatch CMake hook, after which the
existing `ldd` and `ctypes.CDLL` checks validate the staged library. A separate CMake install smoke test
uses a temporary prefix to verify the default `platlib/kotonoha` destination.

The release wheel job verifies that the built archive contains one `kotonoha/libkoto-layer.so`, installs
that wheel into a clean virtual environment, locates the installed bridge through the existing loader,
and loads it with `ctypes.CDLL`. These checks prove both package placement and direct post-install use on
the supported Linux ABI.
