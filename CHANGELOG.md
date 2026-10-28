# Changelog

## 0.5.0 (unreleased)

The package has a new name, msf-character-tools. The behaviour does not change. Results, reports and output bytes are the same as in 0.4.0, apart from the message text below.

### Changed
- The distribution is now `msf-character-tools`. Install the extras as `msf-character-tools[usd]` and `msf-character-tools[fbx]`. Wheel and sdist files start with `msf_character_tools-`.
- The import package is now `msf_character_tools`. Replace `import msf_tools` with `import msf_character_tools`. There is no `msf_tools` alias.
- The C++ extension is now `msf_character_tools._core`. Its exceptions are `msf_character_tools._core.PathError` and `msf_character_tools._core.FbxParseError`.
- The command is now `msf-character-tools`, and `python -m msf_character_tools` runs it. Its usage text names `msf-character-tools`.
- Built packages carry the build record as `msf_character_tools/_build_info.json`. Its contents do not change.
- The `E_FORMAT_DEPENDENCY` messages and remediations name `msf-character-tools`, for example `pip install 'msf-character-tools[usd]'`. The codes, refs and severities do not change.
- `tests/public` changes only in its imports, its module paths and the expected usage line. `tests/public.sha256` lists the new hashes.

### Unchanged
- No pack, CSV, coverage, sidecar, snapshot, generated glTF or report contains the package name. These outputs are the same as in 0.4.0, byte for byte. The committed goldens do not change.

## 0.4.0 (2026-10-27)

msf-tools now runs on a C++ core, `msf_tools._core`. The public API, results and bytes are the same as in 0.3.0, apart from the two nesting differences below. There are wheels for macOS arm64 (11.0 and later) and for Linux x86_64 and aarch64 (`manylinux_2_28`). Each platform has a CPython 3.11 wheel (`cp311`) and one `cp312-abi3` wheel for CPython 3.12 and later. On each platform the results are byte-identical to 0.3.0 run on the same machine. There is one exception, on x86_64: an FBX number of exactly 2^63 (see the ufbx change below).

### Changed
- These now run in the C++ core, `msf_tools._core`: authoring validation and fragment merging, packs (canonical bytes, SHA-256, survey CSV, coverage), profile snapshots, map compilation and evaluation, and `math3d`. Their Python implementations are gone. Results, reports and bytes match 0.3.0 exactly, and the internal tests check this against 0.3.0 itself. msf-tools now needs the extension. `MSF_TOOLS_PURE=1` only makes the core skip its fast paths (JSON, and map evaluation) and use its exact paths.
- These also run in the C++ core: glTF and GLB inspection, accessor decoding, animation sampling and geometry evaluation, the source adapters' node paths, transform decomposition, skin-influence merging and GLB writer, and the FBX adapter. `gltf_semantics` is gone. `AssetSnapshot` and `GeometryValues` hold core handles behind the same frozen-record API. Results, diagnostics and bytes match 0.3.0. This is checked against 0.3.0 itself, on the whole ufbx test corpus too.
- ufbx 0.23.1 and the `msf-ufbx` shim are compiled into the core, so FBX needs nothing extra. The cffi package `msf-tools-ufbx` (`native/ufbx`) is removed. The `fbx` extra is empty, and stays so that existing install commands work.
- `canonical_json` and the JSON parser refuse containers nested more than 200 deep, with `RecursionError("JSON nesting exceeds 200 levels.")`. 0.3.0 failed with `RecursionError` at a depth that depended on the interpreter and the call stack (about 500 to 1000). This is the one intended difference from 0.3.0 in the C++ core's JSON handling. The core and the pure-Python path both behave this way. Validation still limits documents to 128 levels.
- glTF inspection shows the 200-level cap. A glTF JSON document nested more than 200 levels deep, up to about 10,000, now fails with `E_RESOURCE_LIMIT` at ref `inspect_asset` and "Input exceeds supported nesting depth.". 0.3.0 gave `E_RESOURCE_LIMIT` at the path of the first container past 128 levels (such as `/extras/0/0/...`) and "JSON nesting exceeds 128 levels.". The code is the same; the ref and message differ. A malformed document nested that deep, such as a truncated one, also gets this `E_RESOURCE_LIMIT`. 0.3.0 reported its JSON syntax error as `E_INPUT`. Past about 10,000 levels, both versions give the `inspect_asset` diagnostic.
- `scripts/build_release.sh` builds the Linux wheels (`manylinux_2_28` x86_64 and aarch64) in the manylinux container, pinned by image digest. `scripts/ci_local.sh` runs on Linux. A rebuild of a commit with the same pins gives the same bytes; see `docs/building.md`.
- Wheels for CPython 3.12 and later are one stable-ABI (`abi3`) build. CPython 3.11 has its own wheel. Building needs CMake 3.26 or newer. The build requirements are pinned exactly (scikit-build-core 1.1.1, nanobind 3.1.0). Release builds take them and their dependencies from `scripts/build-requirements.txt`, with hashes required.
- The package licence expression adds CC-BY-SA-4.0 for the documentation, schemas and README that the distributions carry. NOTICE.md credits the two committed sample meshes (CC0-1.0). `docs/source-lock.json` pins Ryu and fast_float, as it pins ufbx.
- `scripts/ci_local.sh` and the tests take their outside inputs (interpreters, the 0.3.0 oracle, RCEF, asset corpora) from environment variables. They skip tiers whose inputs are absent. `MSF` names an optional local workspace that supplies all of them.
- The vendored ufbx has one local change. Converting a number of exactly 2^63 to ufbx's int64 copy overflowed (undefined behaviour, found by libFuzzer with UBSan on Linux x86_64). It now saturates to the largest int64, as arm64 hardware already did, so arm64 results do not change. On x86_64, 0.3.0 gave the smallest int64 there. So an FBX that holds exactly 2^63 where ufbx reads an integer can convert differently from 0.3.0. No other value changes.

### Removed
- The remaining pure-Python fallbacks. msf-tools does not import without its extension, and `MSF_REQUIRE_CORE` is gone. `MSF_TOOLS_PURE=1` stays. It sends every input through the paths that the core's fast paths otherwise use only for inputs they decline: Python's `json` for `parse_json` and `canonical_json`, and the core's exact map evaluation. See `docs/building.md`.

## 0.3.0

### Added
- `schemas/diagnostics.toml` lists every diagnostic code with its severity, its rename under strict losses, its meaning and the release that added it. A test keeps it in step with the source.
- Operators 1.1: `piecewise_linear`, with monotone knots that span the input domain exactly, and no extrapolation. New diagnostic `E_KNOTS`.
- Authoring schema 1.1 adds the evidence status `calibrated_software`. Map compilation treats it as `proposed`.
- The authoring and pack JSON schemas accept versions 1.0 and 1.1.
- Built packages carry `msf_tools/_build_info.json`, `{"version": ..., "commit": ...}`, which names the source commit; see `docs/building.md`.

### Removed
- The pybind11 native numeric pilot (`native/src`, `native/include`, `native/tests`, `native/benchmark.py`, `CMakeLists.txt` and `tests/test_native_consumer.py`). The C++ core will replace it. The FBX reader in `native/ufbx` stays as it was.

### Changed
- In a document with `operator_version = "1.0"`, a rule that names `piecewise_linear` now fails with `E_OPERATOR_VERSION` alone, whatever its knots. Before, it failed with `E_UNKNOWN_KEY` for its `knots` key, or with `E_ENUM` when it had no `knots` key.
- The `E_ENUM` messages for unknown `schema_version` and `operator_version` values list `1.0, 1.1`.
- `.github/workflows/check.yml` is dormant while GitHub Actions is blocked by account billing. It no longer lists Windows or the native job. `scripts/ci_local.sh` is the CI run.
- The tests are split in two. `tests/public` uses only the public API and the CLI, and is the gate a reimplementation must pass unchanged. `tests/internal` covers private modules. `tests/public.sha256` freezes the public suite. A test fails if the public suite changes without a manifest update, or if it reaches past the public API. Fixtures moved to `tests/public/fixtures`. Run `python -m unittest discover -s tests/public` and `python -m unittest discover -s tests/internal -t tests`; see `docs/testing.md`.

### Unchanged
- 1.0 documents give the same packs, outputs and goldens, byte for byte. Every other refusal of a 1.0 document keeps its code, reference and message.

## 0.2.0.dev0 (unreleased)

### Added
- USD inspection (USDA, USDC, USDZ, through usd-core) and FBX inspection (through ufbx 0.23.1 in `msf-tools-ufbx`). Each source becomes a generated glTF snapshot with its losses declared. By default it is read in an isolated process. Install with the `usd` and `fbx` extras.
- End-to-end examples for glTF, USD and FBX in `examples/`, with a walkthrough in `examples/README.md`.
- An optional tier for the 09K real-asset recipes, and a generated cross-format parity table, `docs/parity.md`.

### Changed
- Inspection declares the geometry capability `linear_blend_skinning` in place of `four_influence_LBS`, so the bytes of every inspect output change. The schema version stays 1.0. The capability describes the Python reference evaluator. The native C++ pilot is still limited to four influences.
- Linear blend skinning uses every `JOINTS_n`/`WEIGHTS_n` set. Assets with more than four influences now evaluate, where before they were refused with `E_INFLUENCE_LIMIT`. Outputs for four or fewer influences are byte-identical to 0.1.1. The geometry budget counts every influence set.
- Authored quaternions are accepted within the glTF-Validator's unit-length tolerance (0.00769) and normalized, so assets such as Khronos SimpleSkin open.
- The package licence fields are SPDX expressions. Building needs setuptools 77 or newer.

### Fixed
- An FBX stack whose stop time equals its last frame in binary32 is no longer refused.
- An FBX file without axis settings (FBX 5000 and earlier) is no longer declared `I_AXES_CONVERTED`, because ufbx leaves such axes as they are. The shim ABI is now 5 (`msf-tools-ufbx` 0.1.6).
- When the interpreter's link settings point at a missing toolchain (such as a vendor-built `python3` whose toolchain is not installed), building `msf-tools-ufbx` now stops early and gives the remedy, instead of failing with a linker error.

## 0.1.1

Core semantic hardening; see `docs/core-hardening.md`.
