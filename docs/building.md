# Building

Original documentation: CC-BY-SA-4.0.

## Package and C++ core

`pyproject.toml` builds with scikit-build-core through the in-tree backend `tools/build_backend.py`, which adds the build record below. `CMakeLists.txt` compiles the C++ core, `msf_character_tools._core` (C++17, nanobind). It installs the core with every tracked `msf_character_tools/*.py` module and the build record.

Each platform (macOS arm64, Linux x86_64 and aarch64) gets two wheels:
- a `cp311` wheel;
- a `cp312-abi3` wheel, built against CPython's stable ABI for 3.12 and later. 3.12 is the oldest version that nanobind's stable-ABI build supports.

In-place builds follow the same rule, so the suites test the extension that ships. For 3.12 the file is `_core.abi3.so`. For 3.11 it is `_core.cpython-311-darwin.so` on macOS, and `_core.cpython-311-x86_64-linux-gnu.so` or `_core.cpython-311-aarch64-linux-gnu.so` on Linux. Under the limited API, the bindings use the checked C API calls instead of CPython's access macros (`core/python/limited_api.hpp`).

On macOS the backend targets macOS 11.0, the oldest release for arm64, unless `MACOSX_DEPLOYMENT_TARGET` is already set. The wheel tag follows the target. Building needs a C++17 compiler, CMake 3.26 or newer, and Ninja or Make. The build front end fetches scikit-build-core 1.1.1 and nanobind 3.1.0, pinned exactly. Release builds pin their dependencies too (see [Release builds](#release-builds)).

The core is compiled with `-ffp-contract=off` and never with `-ffast-math`, so it rounds exactly as the 0.3.0 Python reference did; see [ADR 0001](adr/0001-record-ownership.md). Everything is in the core except the CLI, TOML loading, sidecars and bindings, the USD adapter and the isolated reader process. msf-character-tools does not import without the extension.

Two paths exist twice:
- `parse_json` and `canonical_json` use the core. For input the core declines, they fall back to Python's `json`. Malformed JSON is an example: Python reports its exact errors.
- `evaluate_mapping` uses a fast path, in whole-map and in partial mode. For samples the fast path declines, it falls back to the core's exact path. In partial mode the fast path takes only samples whose inputs are each valid or absent. One bad input or failed rule in any frame sends the whole call to the exact path. Taking the good frames on the fast path, frame by frame, is a possible follow-up.

The fallbacks otherwise see only rare inputs. `MSF_TOOLS_PURE=1` sends every input down the fallbacks, and `scripts/ci_local.sh` runs the public suite that way.

To work in a checkout, build the extension in place, next to the modules. CMake finds nanobind through the interpreter you choose, so install nanobind there first (`python3.12 -m pip install nanobind`). The interpreters that `scripts/ci_local.sh` uses (`MSF_PY311`, `MSF_PY312`) need it too.

```sh
cmake -S . -B build/core-3.12 -G Ninja -DPython_EXECUTABLE=python3.12 -DMSF_CORE_IN_PLACE=ON
cmake --build build/core-3.12
```

`scripts/ci_local.sh` does this for each Python before it runs the suites. An editable install copies modules at install time, so use the in-place build instead. `-DMSF_SANITIZE=ON` builds with AddressSanitizer and UndefinedBehaviorSanitizer. `scripts/ci_local.sh --sanitize` uses it.

The core vendors Ryu, fast_float and ufbx under `core/third_party` (see NOTICE.md). ufbx and its shim are the exception to the floating-point rule above. They are compiled with `-O2` and the compiler's default contraction, as 0.3.0's cffi build compiled them. With the same compiler on the same platform, FBX conversions stay byte-identical to 0.3.0, apart from the x86_64 change for a value of exactly 2^63 that the CHANGELOG lists. Contraction defaults differ: Apple clang contracts within an expression, GCC on aarch64 across statements, and x86-64 without FMA not at all. As with 0.3.0, FBX bytes can therefore differ between platforms and toolchains. `scripts/ci_local.sh` records the platform with every run.

The core's diagnostic codes come from `core/include/msf/diagnostics.inc`. `python3 -B tools/gen_diagnostics.py` generates that file from `schemas/diagnostics.toml`. Generate it again after you edit the registry; a test fails until you do.

## Build record

Every built package contains `msf_character_tools/_build_info.json`:

```json
{
  "version": "0.6.0",
  "commit": "<40 lowercase hex digits>"
}
```

`version` is the package version, and `commit` is the Git commit the package was built from. RCEF's lock reads this file. When an install also has Git `vcs_info` in `direct_url.json`, the two commits must agree.

`tools/build_backend.py` writes the file at build time, so it is never checked in (`.gitignore` lists it). The rules are in `tools/build_info.py`:

- A build from the top of a Git checkout records `HEAD` when no tracked file has changed, and no untracked file is under `msf_character_tools/` or `core/` (where it would be built into the wheel). This covers `pip install git+...@COMMIT`, `uv pip install`, `uv build` and wheels built from a clean clone.
- Inside a Git checkout only Git counts: a stray `msf_character_tools/_build_info.json` there is never used.
- CMake installs modules from the source tree into a new staging directory for each wheel, and a module left over from an earlier build never ships under the new record.
- An sdist has no `.git`, so building an sdist writes the record into it. A wheel built from that sdist, outside any Git checkout, installs the record if its version matches.
- Any other build records no commit and leaves out the file. Examples: a build from a checkout with uncommitted changes or untracked package files, an editable install, or a source tree inside a checkout but not at its top. Non-editable builds print a warning. RCEF then refuses the install, as it does for any install without a source commit.

A checked-in file cannot work, because a commit cannot contain its own hash.

`tests/internal/test_build_info.py` covers these rules, with fake Git and scikit-build-core. `scripts/ci_local.sh` builds a real wheel from a clean clone of `HEAD`, through its sdist. It checks the record, and checks that the wheel holds exactly the tracked modules and the extension.

## Release builds

`scripts/build_release.sh OUTDIR [COMMIT]` (COMMIT is a commit or a tag) builds a release from a clean clone of the commit. It builds the sdist first, and then the `cp311` and `cp312-abi3` wheels from the unpacked sdist, outside any Git checkout, with `SOURCE_DATE_EPOCH` set to the commit's time. It writes `SHA256SUMS`. A second build of the same commit, in another directory and with the pins below, gives the same bytes.

`scripts/check_release.sh OUTDIR [COMMIT]` then checks these things:
- each wheel's contents, build record and licence files;
- that the extension links only system libraries and targets macOS 11.0;
- that each wheel installs with the `usd` extra into a new venv on its interpreter, and passes the unchanged public suite there (with `MSF_PY313`, the abi3 wheel on CPython 3.13 as well);
- the sdist's contents and licence metadata.

On Linux the same script builds `manylinux_2_28` wheels for the machine's architecture (x86_64 or aarch64). The sdist is built on the host. The wheels are built from it inside the `quay.io/pypa/manylinux_2_28_<arch>` container (`MSF_MANYLINUX_IMAGE`), with the container's `/opt/python` cp311 and cp312. `MSF_PODMAN` names the podman command, with any `--root` options. The container build is offline: first the host downloads the build requirements into a wheelhouse, through `HTTPS_PROXY` if it is set. Then `auditwheel repair --plat manylinux_2_28_<arch> --only-plat` gives each wheel that single tag, because lock files key a wheel by one tag. It vendors nothing, because the extension needs only `libstdc++`, `libgcc_s`, `libm` and `libc`, which the policy supplies.

On Linux, `check_release.sh` replaces the macOS checks with these:
- `auditwheel show` (the oldest policy the wheel meets must be 2_28 or older);
- a check that nothing was vendored and that the wheel has one tag;
- the extension's `NEEDED` libraries.

The sdist has the same bytes, whichever platform builds it.

A rebuild is byte-identical only with the same pinned inputs:

- Build requirements: scikit-build-core 1.1.1, nanobind 3.1.0 and their dependencies packaging 26.3 and pathspec 1.1.1, plus ninja 1.13.2 for the container. They come from `scripts/build-requirements.txt`, with hashes required. On the host, `uv build` takes the file as build constraints with `--require-hashes`. On Linux, `pip download --require-hashes` fills the wheelhouse, which is the only place the offline container can install from. A test keeps the file's pins in step with `pyproject.toml`.
- The Linux image, pinned by digest: `quay.io/pypa/manylinux_2_28_x86_64@sha256:e0adf18521ad35192df733a6c62d35df7801957d24e0470238aacecfab2188a3` and `quay.io/pypa/manylinux_2_28_aarch64@sha256:a3e02308c822fb6ce0d12248b0c941817ba5e1a1bc9e7bb5929f29c50eaa40a9`. It supplies the compiler (GCC 14.2.1), CMake 4.4.4, pip and auditwheel 6.8.2. `MSF_MANYLINUX_IMAGE` overrides it. `BUILD-ENV`, next to `SHA256SUMS`, records the image used, its digest and the compiler.

On macOS the compiler (Apple clang), CMake, Ninja and the interpreters come from the host and are not pinned, and macOS wheels are byte-identical only on the same toolchain. `scripts/ci_local.sh` reports the versions it used.

## Tools

CMake and Ninja come from `PATH`. In the maintainers' local workspace (`MSF`, see [testing](testing.md)) they are uv tools under `$MSF/_tools`:

```sh
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install cmake
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install ninja
```

With `MSF` set, `scripts/ci_local.sh` puts `$MSF/_tools/bin` first on `PATH`. In both cases it reports the versions of both tools. The FBX reader (ufbx in `core/third_party/ufbx` and the shim in `core/src`) is part of the same CMake build.
