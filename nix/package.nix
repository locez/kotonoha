{
  lib,
  cmake,
  desktop-file-utils,
  kdePackages,
  ninja,
  pkg-config,
  python3Packages,
  qt6,
  wayland,
  wayland-scanner,
}:

let
  project = builtins.fromTOML (builtins.readFile ../pyproject.toml);
in
python3Packages.buildPythonApplication {
  inherit (project.project) version;
  pname = project.project.name;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../CMakeLists.txt
      ../LICENSE
      ../LICENSES
      ../README.md
      ../packaging
      ../pyproject.toml
      ../src
    ];
  };

  build-system = [ python3Packages.scikit-build-core ];

  nativeBuildInputs = [
    cmake
    ninja
    pkg-config
    qt6.wrapQtAppsHook
    wayland-scanner
  ];

  buildInputs = [
    kdePackages.layer-shell-qt
    qt6.qtbase
    qt6.qtsvg
    qt6.qtwayland
    wayland
  ];

  dependencies = [
    python3Packages.aiohttp
    python3Packages.dbus-fast
    python3Packages.mutagen
    python3Packages.pyqt6
    python3Packages.qasync
  ];

  # scikit-build-core owns the CMake configure/build lifecycle for the wheel.
  dontUseCmakeConfigure = true;
  cmakeFlags = [ (lib.cmakeFeature "KOTONOHA_INSTALL_DIR" "kotonoha") ];

  postInstall = ''
    install -Dm644 packaging/kotonoha.desktop \
      "$out/share/applications/kotonoha.desktop"
    install -Dm644 src/kotonoha/assets/icon.png \
      "$out/share/icons/hicolor/1024x1024/apps/kotonoha.png"
    install -Dm644 packaging/dev.locez.kotonoha.metainfo.xml \
      "$out/share/metainfo/dev.locez.kotonoha.metainfo.xml"
    install -Dm644 packaging/kotonoha.1 \
      "$out/share/man/man1/kotonoha.1"
  '';

  # Python's wrapper is a shell script, so wrapQtAppsHook does not detect it
  # automatically. Add the Qt/Wayland plugin paths after Python has wrapped it.
  postFixup = ''
    wrapQtApp "$out/bin/kotonoha"
  '';

  pythonImportsCheck = [
    "kotonoha"
    "kotonoha.platform.native"
    "PyQt6.QtCore"
    "PyQt6.QtSvg"
  ];

  doCheck = true;
  nativeCheckInputs = [ desktop-file-utils ];
  installCheckPhase = ''
    runHook preInstallCheck

    test -x "$out/bin/kotonoha"
    test -f "$out/${python3Packages.python.sitePackages}/kotonoha/libkoto-layer.so"
    desktop-file-validate "$out/share/applications/kotonoha.desktop"
    "$out/bin/kotonoha" --help >/dev/null

    runHook postInstallCheck
  '';

  meta = {
    description = project.project.description;
    homepage = "https://github.com/locez/kotonoha";
    license = with lib.licenses; [
      lgpl21Plus
      mit
    ];
    mainProgram = "kotonoha";
    platforms = lib.platforms.linux;
  };
}
