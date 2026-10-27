# SPDX-License-Identifier: MIT
# msf_tools._core, the C++ core behind the Python API. scikit-build-core drives
# this for wheels; scripts/ci_local.sh builds it in place for the test suites.
cmake_minimum_required(VERSION 3.24)
project(msf_tools_core LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
                OUTPUT_VARIABLE nanobind_ROOT OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
find_package(nanobind CONFIG REQUIRED)

# Vendored; see NOTICE.md.
add_library(ryu STATIC core/third_party/ryu/ryu/d2s.c)
target_include_directories(ryu PUBLIC core/third_party/ryu)
add_library(fast_float INTERFACE)
target_include_directories(fast_float INTERFACE core/third_party/fast_float/include)

add_library(msfcore STATIC core/src/diagnostics.cpp core/src/json.cpp core/src/program.cpp)
target_include_directories(msfcore PUBLIC core/include)
target_link_libraries(msfcore PRIVATE ryu fast_float)
set_target_properties(msfcore ryu PROPERTIES POSITION_INDEPENDENT_CODE ON)

nanobind_add_module(_core NOMINSIZE core/python/module.cpp core/python/json_module.cpp)
target_link_libraries(_core PRIVATE msfcore)

# Output bytes must match the Python reference: no fused multiply-add, never fast-math.
target_compile_options(ryu PRIVATE $<$<NOT:$<C_COMPILER_ID:MSVC>>:-ffp-contract=off -fno-fast-math>)
foreach(target msfcore _core)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4 /fp:precise)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -ffp-contract=off -fno-fast-math)
  endif()
endforeach()

install(TARGETS _core LIBRARY DESTINATION msf_tools)
install(DIRECTORY msf_tools/ DESTINATION msf_tools FILES_MATCHING PATTERN "*.py" PATTERN "__pycache__" EXCLUDE)
if(MSF_BUILD_INFO_FILE)
  install(FILES "${MSF_BUILD_INFO_FILE}" DESTINATION msf_tools RENAME _build_info.json)
endif()

option(MSF_CORE_IN_PLACE "Copy the built extension into msf_tools/ for running tests from the checkout" OFF)
if(MSF_CORE_IN_PLACE)
  add_custom_command(TARGET _core POST_BUILD
                     COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:_core>" "${CMAKE_SOURCE_DIR}/msf_tools/")
endif()
