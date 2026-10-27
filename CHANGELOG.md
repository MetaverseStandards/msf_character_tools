# Changelog

## 0.3.0 (unreleased)

### Added
- `schemas/diagnostics.toml` lists every diagnostic code with its severity, strict-losses rename, meaning and the release that added it. A test keeps it in step with the source. `E_OPERATOR_VERSION` is reserved for operators 1.1.

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
- Building `msf-tools-ufbx` with an interpreter whose link settings point at a missing toolchain, such as Meta's system `python3`, stops early with the remedy instead of a linker error.

## 0.1.1

Core semantic hardening; see `docs/core-hardening.md`.
