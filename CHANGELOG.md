# Changelog

## 0.4.0 (2026-10-27)

msf-tools now runs on a C++ core, `msf_tools._core`, with the same public API, results and bytes as 0.3.0 apart from the two nesting differences below. Wheels for macOS arm64 (11.0 and later) and Linux x86_64 and aarch64 (`manylinux_2_28`): CPython 3.11 (`cp311`) and one `cp312-abi3` wheel for CPython 3.12 and later. On each platform the results are byte-identical to 0.3.0 run on the same machine.

### Changed
- Authoring validation and fragment merging, packs (canonical bytes, SHA-256, survey CSV, coverage), profile snapshots, mapping compilation and evaluation, and `math3d` run in the C++ core, `msf_tools._core`, and their Python implementations are gone. Results, reports and bytes match 0.3.0 exactly; the internal tests check this against 0.3.0 itself. msf-tools now needs the extension, and `MSF_TOOLS_PURE=1` only skips the core's fast paths (JSON, and mapping evaluation) in favour of its exact paths.
- glTF and GLB inspection, accessor decoding, animation sampling and geometry evaluation, the source adapters' node paths, transform decomposition, skin-influence merging and GLB writer, and the FBX adapter run in the C++ core. `gltf_semantics` is gone; `AssetSnapshot` and `GeometryValues` hold core handles behind the same frozen-record API. Results, diagnostics and bytes match 0.3.0, checked against 0.3.0 itself, including the whole ufbx test corpus.
- ufbx 0.23.1 and the `msf-ufbx` shim are compiled into the core, so FBX needs nothing extra. The cffi package `msf-tools-ufbx` (`native/ufbx`) is removed, and the `fbx` extra is empty and kept so existing install commands work.
- `canonical_json` and the JSON parser refuse containers nested more than 200 deep with `RecursionError("JSON nesting exceeds 200 levels.")`, where 0.3.0 failed with `RecursionError` at a depth that depended on the interpreter and the call stack (about 500 to 1000). This is the one intended difference from 0.3.0 in the C++ core's JSON handling, and both the core and the pure-Python path behave this way. Documents are still limited to 128 levels by validation.
- glTF inspection shows the 200-level cap. A glTF JSON document nested more than 200 levels deep, up to about 10,000, now fails with `E_RESOURCE_LIMIT` at ref `inspect_asset` and "Input exceeds supported nesting depth.", where 0.3.0 gave `E_RESOURCE_LIMIT` at the path of the first container past 128 levels (such as `/extras/0/0/...`) and "JSON nesting exceeds 128 levels.". The code is the same; the ref and message differ. A malformed document nested that deep, such as a truncated one, also gets this `E_RESOURCE_LIMIT`, where 0.3.0 reported its JSON syntax error as `E_INPUT`. Past about 10,000 levels both give the `inspect_asset` diagnostic.
- Linux wheels (`manylinux_2_28` x86_64 and aarch64) are built reproducibly in the manylinux container by `scripts/build_release.sh`, and `scripts/ci_local.sh` runs on Linux.
- Wheels for CPython 3.12 and later are one stable-ABI (`abi3`) build; CPython 3.11 has its own. Building needs CMake 3.26 or newer, and the build requirements are pinned exactly (scikit-build-core 1.1.1, nanobind 3.1.0).
- The package licence expression adds CC-BY-SA-4.0 for the documentation, schemas and README the distributions carry; NOTICE.md credits the two committed sample meshes (CC0-1.0), and `docs/source-lock.json` pins Ryu and fast_float as it pins ufbx.
- `scripts/ci_local.sh` and the tests take their outside inputs (interpreters, the 0.3.0 oracle, RCEF, asset corpora) from environment variables and skip tiers whose inputs are absent; `MSF` names an optional local workspace that supplies them all.

- The vendored ufbx has one local change: converting a number of exactly 2^63 to ufbx's int64 copy overflowed (undefined behaviour, found by libFuzzer with UBSan on Linux x86_64). It now saturates, as arm64 hardware already did; on x86_64 an FBX holding exactly 2^63 where ufbx reads an integer may convert differently from 0.3.0.

### Removed
- The remaining pure-Python fallbacks: msf-tools does not import without its extension, and `MSF_REQUIRE_CORE` is gone. `MSF_TOOLS_PURE=1` stays, to run every input through the paths the core's fast paths leave to inputs they decline (Python's `json` for `parse_json` and `canonical_json`, and the core's exact mapping evaluation); see `docs/building.md`.

## 0.3.0

### Added
- `schemas/diagnostics.toml` lists every diagnostic code with its severity, strict-losses rename, meaning and the release that added it. A test keeps it in step with the source.
- Operators 1.1: `piecewise_linear`, with monotone knots spanning the input domain exactly and no extrapolation; new diagnostic `E_KNOTS`.
- Authoring schema 1.1 adds the evidence status `calibrated_software`, which mapping compilation treats as `proposed`.
- The authoring and pack JSON schemas accept versions 1.0 and 1.1.
- Built packages carry `msf_tools/_build_info.json`, `{"version": ..., "commit": ...}`, naming the source commit; see `docs/building.md`.

### Removed
- The pybind11 native numerical pilot (`native/src`, `native/include`, `native/tests`, `native/benchmark.py`, `CMakeLists.txt` and `tests/test_native_consumer.py`). The C++ core will replace it. The FBX reader in `native/ufbx` is unchanged.

### Changed
- A rule naming `piecewise_linear` in a document with `operator_version = "1.0"` now fails with `E_OPERATOR_VERSION` alone, whatever its knots. It used to fail with `E_UNKNOWN_KEY` for its `knots` key, or `E_ENUM` without one.
- The `E_ENUM` messages for unknown `schema_version` and `operator_version` values list `1.0, 1.1`.
- `.github/workflows/check.yml` is dormant while GitHub Actions is blocked by account billing; it no longer lists Windows or the native job. `scripts/ci_local.sh` is the CI run.
- Tests are split into `tests/public`, which uses only the public API and the CLI and is the gate a reimplementation must pass unchanged, and `tests/internal`, which covers private modules. `tests/public.sha256` freezes the public suite, and a test fails if it changes without updating the manifest or reaches past the public API. Fixtures moved to `tests/public/fixtures`. Run `python -m unittest discover -s tests/public` and `python -m unittest discover -s tests/internal -t tests`; see `docs/testing.md`.

### Unchanged
- 1.0 documents give the same packs, outputs and goldens byte for byte, and every other refusal of a 1.0 document keeps its code, reference and message.

## 0.2.0.dev0 (unreleased)

### Added
- USD (USDA, USDC, USDZ, through usd-core) and FBX (through ufbx 0.23.1 in `msf-tools-ufbx`) inspection. Each source becomes a generated glTF snapshot with its losses declared, read in an isolated process by default. Install with the `usd` and `fbx` extras.
- End-to-end examples for glTF, USD and FBX in `examples/`, with a walkthrough in `examples/README.md`.
- An optional tier for the 09K real-asset recipes, and a generated cross-format parity table, `docs/parity.md`.

### Changed
- Inspection declares the geometry capability `linear_blend_skinning` in place of `four_influence_LBS`, so the bytes of every inspect output change. The schema version stays 1.0. The capability describes the Python reference evaluator; the native C++ pilot is still limited to four influences.
- Linear blend skinning uses every `JOINTS_n`/`WEIGHTS_n` set. Assets with more than four influences now evaluate instead of being refused with `E_INFLUENCE_LIMIT`. Outputs for four or fewer influences are byte-identical to 0.1.1. The geometry budget counts every influence set.
- Authored quaternions are accepted within the glTF-Validator's unit-length tolerance (0.00769) and normalized, so assets such as Khronos SimpleSkin open.
- Package licence fields are SPDX expressions; building needs setuptools 77 or newer.

### Fixed
- An FBX stack whose stop time equals its last frame in binary32 is no longer refused.
- An FBX file without axis settings (FBX 5000 and earlier) is no longer declared `I_AXES_CONVERTED`: ufbx leaves such axes as they are. The shim ABI is now 5 (`msf-tools-ufbx` 0.1.6).
- Building `msf-tools-ufbx` with an interpreter whose link settings point at a missing toolchain, such as a vendor-built `python3` whose toolchain is not installed, stops early with the remedy instead of a linker error.

## 0.1.1

Core semantic hardening; see `docs/core-hardening.md`.
