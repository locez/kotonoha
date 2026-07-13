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
