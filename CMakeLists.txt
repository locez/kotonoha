cmake_minimum_required(VERSION 3.20)

project(kotonoha_native_bridge LANGUAGES C CXX)

include(GNUInstallDirs)
find_package(PkgConfig REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Qt6 REQUIRED COMPONENTS Core Gui)
message(STATUS "koto-layer linking Qt ${Qt6_VERSION}")  # eyeball the Qt<->PyQt6 ABI match
find_package(Qt6GuiPrivate REQUIRED)
find_package(LayerShellQt CONFIG REQUIRED)
pkg_check_modules(WaylandClient REQUIRED IMPORTED_TARGET wayland-client)

# KWin blur protocol (frosted-glass panel). The client bindings are generated
# from a vendored protocol XML, so no plasma-wayland-protocols dependency is
# needed. Rather than silently degrade when wayland-scanner is missing (an
# "automagic" dependency — the feature's presence would depend on the build host,
# which distro packagers rightly reject), this is an explicit option that hard-
# errors when requested without the tool. It defaults ON: the build already
# hard-requires the wayland-client dev package (below), which ships
# wayland-scanner, so ON adds no real dependency. Packagers who want it off pass
# -DKOTONOHA_ENABLE_BLUR=OFF (blur then compiles to a no-op; the translucent
# fill still renders, just unblurred).
option(KOTONOHA_ENABLE_BLUR "Compile KWin org_kde_kwin_blur support (LGPL-2.1+)" ON)
set(KOTONOHA_BLUR_SOURCES "")
if(KOTONOHA_ENABLE_BLUR)
  find_program(WAYLAND_SCANNER wayland-scanner)
  if(NOT WAYLAND_SCANNER)
    message(FATAL_ERROR
      "KOTONOHA_ENABLE_BLUR=ON requires wayland-scanner (dev-util/wayland-scanner). "
      "Pass -DKOTONOHA_ENABLE_BLUR=OFF to build without frosted-glass blur.")
  endif()
  set(KOTONOHA_BLUR_XML "${CMAKE_CURRENT_SOURCE_DIR}/src/kotonoha/protocols/blur.xml")
  set(KOTONOHA_BLUR_HEADER "${CMAKE_CURRENT_BINARY_DIR}/blur-client-protocol.h")
  set(KOTONOHA_BLUR_CODE "${CMAKE_CURRENT_BINARY_DIR}/blur-protocol.c")
  add_custom_command(
    OUTPUT "${KOTONOHA_BLUR_HEADER}"
    COMMAND "${WAYLAND_SCANNER}" client-header "${KOTONOHA_BLUR_XML}" "${KOTONOHA_BLUR_HEADER}"
    DEPENDS "${KOTONOHA_BLUR_XML}"
    VERBATIM
  )
  add_custom_command(
    OUTPUT "${KOTONOHA_BLUR_CODE}"
    COMMAND "${WAYLAND_SCANNER}" private-code "${KOTONOHA_BLUR_XML}" "${KOTONOHA_BLUR_CODE}"
    DEPENDS "${KOTONOHA_BLUR_XML}"
    VERBATIM
  )
  set(KOTONOHA_BLUR_SOURCES "${KOTONOHA_BLUR_HEADER}" "${KOTONOHA_BLUR_CODE}")
endif()

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
  OFF
)

add_library(koto-layer SHARED src/kotonoha/layer_shell_bridge.cpp ${KOTONOHA_BLUR_SOURCES})
target_include_directories(koto-layer PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(koto-layer PRIVATE cxx_std_17)
if(KOTONOHA_ENABLE_BLUR)
  target_compile_definitions(koto-layer PRIVATE KOTONOHA_HAVE_BLUR)
endif()
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
# Wheel/platlib builds set this OFF: scikit-build-core already ships LICENSE in
# .dist-info/licenses/, so staging a second copy under site-packages/share/
# licenses/ would litter the wheel. Distro CMake installs (deb/rpm/ebuild) leave
# it ON to land the license under the system datadir.
option(KOTONOHA_INSTALL_LICENSE "Install the LICENSE file (off for wheel/platlib builds)" ON)
if(KOTONOHA_INSTALL_LICENSE)
  install(
    FILES "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE"
    DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/licenses/kotonoha"
    COMPONENT KotonohaDocumentation
  )
endif()
