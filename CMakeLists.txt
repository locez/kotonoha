cmake_minimum_required(VERSION 3.20)

project(kotonoha_native_bridge LANGUAGES C CXX)

include(GNUInstallDirs)
find_package(PkgConfig REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(Qt6GuiPrivate REQUIRED)
find_package(LayerShellQt CONFIG REQUIRED)
pkg_check_modules(WaylandClient REQUIRED IMPORTED_TARGET wayland-client)

# Optional: generate client bindings for the KWin blur protocol (frosted-glass
# panel) when wayland-scanner is available. The protocol XML is vendored so no
# plasma-wayland-protocols dependency is needed; when the tool is absent the
# bridge still builds and blur is simply a no-op, so packaging never breaks.
find_program(WAYLAND_SCANNER wayland-scanner)
set(KOTONOHA_BLUR_SOURCES "")
if(WAYLAND_SCANNER)
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
if(WAYLAND_SCANNER)
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
install(
  FILES "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE"
  DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/licenses/kotonoha"
  COMPONENT KotonohaDocumentation
)
