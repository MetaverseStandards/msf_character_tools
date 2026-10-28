# SPDX-License-Identifier: MIT
# msf_tools._core, the C++ core behind the Python API. scikit-build-core drives
# this for wheels; scripts/ci_local.sh builds it in place for the test suites.
cmake_minimum_required(VERSION 3.26)
project(msf_tools_core LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Development.SABIModule (Python 3.12+) lets nanobind build against the stable ABI, in place as in wheels.
find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module OPTIONAL_COMPONENTS Development.SABIModule)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
                OUTPUT_VARIABLE nanobind_ROOT OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
find_package(nanobind CONFIG REQUIRED)

option(MSF_SANITIZE "Build with AddressSanitizer and UndefinedBehaviorSanitizer (scripts/ci_local.sh --sanitize)" OFF)
# GCC's undefined group leaves out float-cast-overflow; clang's includes it.
if(MSF_SANITIZE)
  add_compile_options(-fsanitize=address,undefined,float-cast-overflow -fno-sanitize-recover=all -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=address,undefined,float-cast-overflow)
endif()
# libFuzzer harnesses (core/fuzz), on an ASan and UBSan core. Compilers without
# the fuzzer runtime (Apple clang) take a libFuzzer.a built from compiler-rt
# sources as MSF_LIBFUZZER; see docs/testing.md.
option(MSF_FUZZ "Build the libFuzzer harnesses in core/fuzz" OFF)
set(MSF_LIBFUZZER "" CACHE FILEPATH "libFuzzer.a, for compilers without -fsanitize=fuzzer")
if(MSF_FUZZ)
  add_compile_options(-fsanitize=address,undefined,float-cast-overflow -fno-sanitize-recover=all -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=address,undefined,float-cast-overflow)
  if(MSF_LIBFUZZER)
    add_compile_options(-fsanitize-coverage=inline-8bit-counters,trace-cmp,pc-table)
  else()
    add_compile_options(-fsanitize=fuzzer-no-link)
  endif()
endif()

# Vendored; see NOTICE.md.
add_library(ryu STATIC core/third_party/ryu/ryu/d2s.c)
target_include_directories(ryu PUBLIC core/third_party/ryu)
add_library(fast_float INTERFACE)
target_include_directories(fast_float INTERFACE core/third_party/fast_float/include)
# Vendored ufbx and our C shim over it, compiled as 0.3.0's msf-tools-ufbx 0.1.6 cffi build compiled them
# (-O2, the compiler's default floating-point contraction), so FBX conversions stay byte-identical.
add_library(msfufbx STATIC core/third_party/ufbx/ufbx.c core/src/msf_ufbx_shim.c)
target_include_directories(msfufbx PUBLIC core/third_party/ufbx core/src)
target_compile_definitions(msfufbx PRIVATE UFBX_NO_STDIO UFBX_NO_FORMAT_OBJ UFBX_NO_GEOMETRY_CACHE UFBX_NO_SUBDIVISION
                           UFBX_NO_TESSELLATION NDEBUG)
target_compile_options(msfufbx PRIVATE $<$<NOT:$<C_COMPILER_ID:MSVC>>:-O2 -fno-strict-overflow>)

add_library(msfcore STATIC core/src/authoring.cpp core/src/bigint.cpp core/src/diagnostics.cpp core/src/fbx.cpp core/src/glb_writer.cpp core/src/gltf_binary.cpp core/src/gltf_document.cpp core/src/gltf_geometry.cpp
            core/src/json.cpp core/src/math3d.cpp core/src/mapping.cpp core/src/pack.cpp core/src/paths.cpp core/src/program.cpp
            core/src/sha256.cpp core/src/source_helpers.cpp)
target_include_directories(msfcore PUBLIC core/include)
target_link_libraries(msfcore PRIVATE ryu fast_float msfufbx)
set_target_properties(msfcore ryu msfufbx PROPERTIES POSITION_INDEPENDENT_CODE ON)

# STABLE_ABI applies only where nanobind supports it, Python 3.12 and later; 3.11 gets a version-specific build.
nanobind_add_module(_core STABLE_ABI NOMINSIZE core/python/module.cpp core/python/authoring_module.cpp core/python/json_module.cpp
                    core/python/math_module.cpp core/python/snapshot_module.cpp core/python/sources_module.cpp)
target_link_libraries(_core PRIVATE msfcore msfufbx)

# Output bytes must match the Python reference: no fused multiply-add, never fast-math.
target_compile_options(ryu PRIVATE $<$<NOT:$<C_COMPILER_ID:MSVC>>:-ffp-contract=off -fno-fast-math>)
foreach(target msfcore _core)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4 /fp:precise)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -ffp-contract=off -fno-fast-math)
  endif()
endforeach()

if(MSF_FUZZ)
  foreach(harness gltf data_uri paths fbx)
    add_executable(fuzz_${harness} core/fuzz/fuzz_${harness}.cpp)
    target_link_libraries(fuzz_${harness} PRIVATE msfcore msfufbx)
    if(MSF_LIBFUZZER)
      target_link_libraries(fuzz_${harness} PRIVATE "${MSF_LIBFUZZER}")
    else()
      target_link_options(fuzz_${harness} PRIVATE -fsanitize=fuzzer)
    endif()
  endforeach()
endif()

install(TARGETS _core LIBRARY DESTINATION msf_tools)
install(DIRECTORY msf_tools/ DESTINATION msf_tools FILES_MATCHING PATTERN "*.py" PATTERN "__pycache__" EXCLUDE)
if(MSF_BUILD_INFO_FILE)
  install(FILES "${MSF_BUILD_INFO_FILE}" DESTINATION msf_tools RENAME _build_info.json)
endif()

option(MSF_CORE_IN_PLACE "Copy the built extension into msf_tools/ for running tests from the checkout" OFF)
if(MSF_CORE_IN_PLACE)
  # Python prefers a version-specific extension to abi3, so an older one for this interpreter must go.
  add_custom_command(TARGET _core POST_BUILD
                     COMMAND ${CMAKE_COMMAND} -E rm -f "${CMAKE_SOURCE_DIR}/msf_tools/_core.${Python_SOABI}${CMAKE_SHARED_MODULE_SUFFIX}"
                     COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:_core>" "${CMAKE_SOURCE_DIR}/msf_tools/")
endif()
