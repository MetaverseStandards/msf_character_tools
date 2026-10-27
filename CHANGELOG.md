# Changelog

## 0.2.0.dev0 (unreleased)

### Added
- USD (USDA, USDC, USDZ, through usd-core) and FBX (through ufbx 0.23.1 in `msf-tools-ufbx`) inspection. Each source becomes a generated glTF snapshot with its losses declared, read in an isolated process by default. Install with the `usd` and `fbx` extras.
- End-to-end examples for glTF, USD and FBX in `examples/`, with a walkthrough in `examples/README.md`.
- An optional tier for the 09K real-asset recipes, and a generated cross-format parity table, `docs/parity.md`.

### Changed
- Linear blend skinning uses every `JOINTS_n`/`WEIGHTS_n` set. Assets with more than four influences now evaluate instead of being refused with `E_INFLUENCE_LIMIT`. Outputs for four or fewer influences are byte-identical to 0.1.1. The geometry budget counts every influence set.
- Authored quaternions are accepted within the glTF-Validator's unit-length tolerance (0.00769) and normalized, so assets such as Khronos SimpleSkin open.
- Package licence fields are SPDX expressions; building needs setuptools 77 or newer.

### Fixed
- An FBX stack whose stop time equals its last frame in binary32 is no longer refused.
- Building `msf-tools-ufbx` with an interpreter whose link settings point at a missing toolchain, such as Meta's system `python3`, stops early with the remedy instead of a linker error.

## 0.1.1

Core semantic hardening; see `docs/core-hardening.md`.
