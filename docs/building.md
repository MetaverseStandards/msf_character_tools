# Building

Original documentation: CC-BY-SA-4.0.

## Package and C++ core

`pyproject.toml` builds with scikit-build-core through the in-tree backend `tools/build_backend.py`, which adds the build record below. `CMakeLists.txt` compiles the C++ core, `msf_tools._core` (C++17, nanobind), and installs it with every tracked `msf_tools/*.py` module and the build record. Wheels are therefore per Python version and platform. On macOS the backend targets macOS 11.0, the oldest release for arm64, unless `MACOSX_DEPLOYMENT_TARGET` is already set; the wheel tag follows it. Building needs a C++17 compiler, CMake 3.24 or newer and Ninja or Make; the build front end fetches scikit-build-core and nanobind.

The core is compiled with `-ffp-contract=off` and never with `-ffast-math`, so it rounds exactly as the Python reference does; see [ADR 0001](adr/0001-record-ownership.md). Authoring, packs, mappings and `math3d` exist only in the core, so msf-tools needs the extension; `MSF_TOOLS_PURE=1` skips the core's fast paths (JSON, and mapping evaluation) in favour of its exact paths and the remaining Python reference paths.

For work in a checkout, build the extension in place next to the modules:

```sh
cmake -S . -B build/core-3.12 -G Ninja -DPython_EXECUTABLE=$MSF/_tools/venv3.12/bin/python -DMSF_CORE_IN_PLACE=ON
cmake --build build/core-3.12
```

`scripts/ci_local.sh` does this for each Python before running the suites. An editable install copies modules at install time, so prefer the in-place build. `-DMSF_SANITIZE=ON` builds with AddressSanitizer and UndefinedBehaviorSanitizer; `scripts/ci_local.sh --sanitize` uses it.

The core vendors Ryu, fast_float and ufbx under `core/third_party` (see NOTICE.md). ufbx and its shim are the exception to the floating-point rule above: they are compiled with `-O2` and the compiler's default contraction, as 0.3.0's cffi build compiled them, so FBX conversions stay byte-identical to 0.3.0 built with the same compiler on the same platform. Contraction defaults differ (Apple clang contracts within an expression, GCC on aarch64 across statements, and x86-64 without FMA not at all), so FBX bytes can differ between platforms and toolchains, as they could with 0.3.0; `scripts/ci_local.sh` records the platform with every run. The core's diagnostic codes come from `core/include/msf/diagnostics.inc`, which `python3 -B tools/gen_diagnostics.py` generates from `schemas/diagnostics.toml`; regenerate it after editing the registry, and a test fails until you do.

## Build record

Every built package contains `msf_tools/_build_info.json`:

```json
{
  "version": "0.3.0",
  "commit": "<40 lowercase hex digits>"
}
```

`version` is the package version and `commit` the Git commit the package was built from. RCEF's lock reads this file, and when an install also has Git `vcs_info` in `direct_url.json`, the two commits must agree.

`tools/build_backend.py` writes the file at build time, so it is never checked in (`.gitignore` lists it). The rules are in `tools/build_info.py`:

- A build from the top of a Git checkout records `HEAD` when no tracked file has changed and no untracked file sits under `msf_tools/` or `core/`, where it would be built into the wheel. This covers `pip install git+...@COMMIT`, `uv pip install`, `uv build` and wheels built from a clean clone.
- Inside a Git checkout only Git counts: a stray `msf_tools/_build_info.json` there is never used.
- CMake installs modules from the source tree into a fresh staging directory for each wheel, so a module left over from an earlier build is never shipped under the new record.
- An sdist has no `.git`, so building one writes the record into the sdist. A wheel built from that sdist outside any Git checkout installs it if its version matches.
- Any other build, such as one from a checkout with uncommitted changes or untracked package files, an editable install, or a source tree inside a checkout but not at its top, records no commit and omits the file; non-editable builds print a warning. RCEF then refuses the install, as it does for any install without a source commit.

A checked-in file cannot work, because a commit cannot contain its own hash.

`tests/internal/test_build_info.py` covers these rules with Git and scikit-build-core faked. `scripts/ci_local.sh` builds a real wheel from a clean clone of `HEAD` through its sdist, checks the record, and checks that the wheel holds exactly the tracked modules and the extension.

## Tools

CMake and Ninja for the C++ core are installed as uv tools under `$MSF/_tools`:

```sh
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install cmake
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install ninja
```

`scripts/ci_local.sh` puts `$MSF/_tools/bin` first on `PATH` and reports both versions. The FBX reader (ufbx in `core/third_party/ufbx` and the shim in `core/src`) is part of the same CMake build.
