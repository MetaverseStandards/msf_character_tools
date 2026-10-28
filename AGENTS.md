# Agent guide

Original documentation: CC-BY-SA-4.0.

This file is for coding agents. Part 1 is for an agent that uses msf-character-tools. Part 2 is for an agent that changes it. Follow the [writing style](#writing-style) in all prose.

## Part 1: Using msf-character-tools

msf-character-tools validates signal mappings and inspects glTF assets into immutable snapshots. It also evaluates vertex positions (morph targets and linear blend skinning) in binary64, with a C++ core behind a Python API for Python 3.11 and later.

### Install

- From a checkout: see "Run" in [README.md](README.md).
- From a release: download the wheel for your platform and Python, and `SHA256SUMS`, from the GitHub release. Install the wheel pinned by its hash:

```sh
echo "msf-character-tools @ file://$DIR/$WHEEL --hash=sha256:$SHA" > req.txt  # $SHA from SHA256SUMS
python -m pip install --require-hashes -r req.txt
```

The tag `v0.4.0` is on commit `ce52dfb`.

### Public surface

- `msf_character_tools.__all__` has 29 names. Use nothing else. `tests/public` uses only these names and the CLI.
- The six main operations: `validate_authoring`, `compile_pack`, `inspect_asset`, `annotate_asset`, `compile_mapping`, `evaluate_mapping`.
- The other names are helpers (such as `load_authoring`, `profile_snapshot`, `LocalResolver`, `evaluate_geometry`, `canonical_json`) and the result and record types.
- [docs/reference.md](docs/reference.md) gives every signature, the types, the byte formats and the geometry conventions. [schemas/](schemas/README.md) has the JSON schemas for the wire types.

### Results and reports

- Each operation returns a frozen `Result(value, report)`. Check `.ok` before you use `.value`.
- When there is an error, `value` is always `None`. The six operations do not raise: exceptions become diagnostics.
- `report.diagnostics` holds `Diagnostic(code, severity, ref, message, remediation)`. `report.losses` holds the declared losses (`Loss(category, effect, reason, refs, ...)`). `report.to_dict()` gives both.
- `canonical_json`, `survey_csv`, `coverage` and record `.to_dict()` / `.to_bytes()` raise instead.
- Every diagnostic code is listed in [schemas/diagnostics.toml](schemas/diagnostics.toml).

### Typical calls

Run from a directory with `examples/authoring` and `examples/samples.json` copied in:

```python
import json
from msf_character_tools import (load_authoring, compile_pack, profile_snapshot,
                       compile_mapping, evaluate_mapping, inspect_asset)

pack = compile_pack(load_authoring("authoring").value)
assert pack.ok, pack.report.to_dict()
src = profile_snapshot(pack.value, "source").value
dst = profile_snapshot(pack.value, "target").value
compiled = compile_mapping(pack.value, src, dst, "wink")
samples = json.loads(open("samples.json").read())["samples"]
result = evaluate_mapping(compiled.value, samples)
print(result.ok, result.value.to_dict())   # True {'samples': [...]}

bad = inspect_asset(b"not a glb", "glb")
print(bad.ok, bad.value, bad.report.diagnostics[0].code)   # False None E_GLB_HEADER
```

### Command line

`msf-character-tools` (or `python -m msf_character_tools`) has six commands: `check`, `inspect`, `annotate`, `geometry`, `map`, `evaluate`. Reports go to stderr as JSON. Values go to stdout or to `--output`. A failure exits nonzero. See "CLI and writes" in [docs/reference.md](docs/reference.md).

### Formats

- glTF and GLB: built in.
- FBX: built in (ufbx is compiled into the core). The `fbx` extra is empty.
- USD (`usd`, `usda`, `usdc`, `usdz`): needs the `usd` extra (`msf-character-tools[usd]`, usd-core). Without it, `inspect_asset` returns `E_FORMAT_DEPENDENCY`.
- Source formats are converted to glTF. `inspect_asset(..., isolate=True)` reads them in a separate process. The CLI does this by default.

## Part 2: Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. [docs/building.md](docs/building.md) and [docs/testing.md](docs/testing.md) have the details.

### Layout

| Path | Contents |
| --- | --- |
| `msf_character_tools/` | The Python package: API, CLI, records, sidecars, source adapters (`sources/`) |
| `core/` | The C++17 core: `src/`, `include/msf/`, `fuzz/` (libFuzzer harnesses) |
| `core/python/` | The nanobind bindings that make `msf_character_tools._core` |
| `core/third_party/` | Vendored Ryu, fast_float and ufbx |
| `tests/public/` | The frozen public gate: public API and CLI only |
| `tests/internal/` | Private modules, and the core against the 0.3.0 oracle |
| `schemas/` | JSON schemas and the diagnostics registry |
| `scripts/` | `ci_local.sh`, release builds, fuzzing, parity table |
| `docs/` | Reference, building, testing, ADRs, source lock |
| `examples/` | End-to-end scripts on real glTF, USD and FBX assets |

### Build and test

Install nanobind into the interpreter that builds, then build the core in place:

```sh
python3.12 -m pip install nanobind==3.1.0
cmake -S . -B build/core-3.12 -G Ninja -DPython_EXECUTABLE=python3.12 -DMSF_CORE_IN_PLACE=ON
cmake --build build/core-3.12
```

`scripts/ci_local.sh` is the CI (the GitHub workflow is dormant). It builds the core for 3.11 and 3.12, runs the public and internal suites and `check.py` on both, runs the public suite again with `MSF_TOOLS_PURE=1`, builds a wheel from a clean clone, and prints a summary. Tiers whose inputs are absent are skipped. The script needs bash: run `scripts/ci_local.sh` or `bash scripts/ci_local.sh`, not `sh scripts/ci_local.sh` (dash, the `sh` of Debian and Ubuntu, cannot parse it).

- MSF workspace: `MSF=$HOME/.local/share/msf scripts/ci_local.sh`. Interpreters, cmake, ninja, uv, the 0.3.0 oracle and the asset tiers come from `$MSF`. A missing oracle or usd-core fails the run.
- Outside contributor: `scripts/ci_local.sh` uses `python3.11` and `python3.12` on `PATH` (or `MSF_PY311`, `MSF_PY312`). Without `MSF_ORACLE_PYTHON`, the oracle tests skip.
- Optional tiers: `--gate`, `--sanitize`, `--fuzz`. Asset tiers use `MSF_OPENUSD_ASSETS`, `MSF_UFBX_CORPUS`, `MSF_KHRONOS_ASSETS`, `MSF_REAL_ASSETS`, `MSF_EXAMPLE_ASSETS`. See [docs/testing.md](docs/testing.md).

### Invariants

Do not break these. Each one names its check.

- `tests/public` never changes. `tests/public.sha256` pins every file. Check: `tests/internal/test_public_suite.py`. Do not run its `--write` mode unless the maintainer asks.
- Results, reports and bytes stay identical to 0.3.0, except the differences that [CHANGELOG.md](CHANGELOG.md) lists. Check: `tests/internal/test_core_*.py` against the oracle (`MSF_ORACLE_PYTHON`), the ufbx corpus tier, and `--gate`.
- Every diagnostic code is registered in `schemas/diagnostics.toml`. After you edit it, run `python3 -B tools/gen_diagnostics.py` to regenerate `core/include/msf/diagnostics.inc`. Check: `tests/internal/test_diagnostics_registry.py` and `python3 -B tools/gen_diagnostics.py --check`.
- The core (and Ryu) compile with `-ffp-contract=off -fno-fast-math`. ufbx and its shim keep `-O2` and the compiler's default contraction, as in 0.3.0. See `CMakeLists.txt`. Check: the oracle differential tests and the ufbx corpus tier.
- Record views are bound to their C++ handles by identity, so an equal copy is refused (`EvaluatedValues.samples` is compared by type and bits instead). See [ADR 0001](docs/adr/0001-record-ownership.md). Check: `tests/internal/test_record_integrity_internal.py`.
- Do not edit generated files by hand. Edit the source and run the generator:
  - `core/include/msf/diagnostics.inc`: see the registry rule above.
  - `docs/parity.md`: `python -B scripts/parity_table.py` with the asset variables set (check: `ci_local.sh` compares a fresh table when all asset inputs are present).
  - The generated fixtures and goldens in `tests/public/fixtures/`: `tests/public/make_fixtures.py` and `make_source_fixtures.py`. They must give the same bytes again (check: `tests/public.sha256`).
  - `examples/data/AnimatedMorphCube.writer.fbx`: `tests/public/make_example_fbx.py` (check: the examples tier).
  - `examples/generated/`: `python3 -B -m msf_character_tools check examples/authoring --pack examples/generated/pack.json --csv examples/generated/survey.csv --write` (check: `check.py`).
- Never commit `msf_character_tools/_build_info.json`. Builds write it, and a commit cannot hold its own hash. Check: `.gitignore` lists it; `test_build_info.py` and the build-record tier of `ci_local.sh` check the record that builds write.
- The bindings in `core/python/` must compile under `Py_LIMITED_API`, so the abi3 wheel keeps working. Use the functions that `core/python/limited_api.hpp` maps to, not CPython's unchecked macros. Check: the 3.12 in-place build in `ci_local.sh` defines `Py_LIMITED_API`, so a call outside the limited API does not compile. `check_release.sh` runs the public suite on the abi3 wheel (and on 3.13 with `MSF_PY313`).
- Check the type of every item read from a caller's Mapping or sequence before C++ uses it. Do not assume `items()` gives 2-tuples. 0.4.0 fixed a segfault of this kind (`6aabfb8`). Check: the `_Odd` cases in `tests/internal/gltf_cases.py` and the `OddItems` cases in `tests/internal/test_core_json.py`, both against the oracle; `--sanitize`.
- No runtime dependencies beyond the standard library: `dependencies = []` in `pyproject.toml`. No test checks this, so review it.
- Every vendored file under `core/third_party` is pinned by SHA-256 in `docs/source-lock.json`, and credited in [NOTICE.md](NOTICE.md) and `LICENSES/`. Check: `tests/internal/test_package_metadata.py` (pins, and that each licence file exists). Review the credits.
- Release builds use `scripts/build_release.sh OUTDIR [COMMIT]`, then `scripts/check_release.sh OUTDIR [COMMIT]`. The manylinux images are pinned by digest. Build requirements come from `scripts/build-requirements.txt` with hashes. Check: `test_package_metadata.py` keeps those pins in step with `pyproject.toml`.
- Never tag, publish a release or upload wheels without the maintainer. See [GOVERNANCE.md](GOVERNANCE.md).

### Known traps

- A `_core.cpython-312-*.so` in `msf_character_tools/` shadows `_core.abi3.so`, because Python prefers the version-specific file. A stale one in `build/core-3.12` is harmless until something copies it into `msf_character_tools/`, as the `--sanitize` restore once did (fixed in `d8265f9`: it now copies only the newest build). Delete the stray file and rebuild.
- `ci_local.sh` sets `PYTHONHASHSEED=0`. 0.3.0 checked a frame's channels in set order, so its diagnostic order depends on the hash seed. The oracle inherits the seed. Set it when you run the suites by hand.
- On macOS, `--fuzz` fails unless `MSF_LIBFUZZER` names a `libFuzzer.a`. Apple clang has no fuzzer runtime. docs/testing.md says how to build one.
- On Linux, the `docs/parity.md` check compares a fresh table with 0.3.0's table measured on the same machine (`MSF_ORACLE_SOURCE`, a `v0.3.0` checkout). The committed table is from macOS.
- CMake finds nanobind through `-DPython_EXECUTABLE`. If nanobind is not installed in that interpreter, configuration fails.

### Change workflow

1. Make small commits, one topic each.
2. Write the test first. Expected values must come from an independent calculation, not from the code under test.
3. Run `scripts/ci_local.sh` on Python 3.11 and 3.12 before you propose a change. Put its summary block in the pull request.
4. Update `CHANGELOG.md`, `docs/` and the schemas when behaviour or a contract changes.
5. Get an independent review before merge.
6. Write in plain English (see below).

## Writing style

- Write plain English in the ASD-STE100 style: short sentences, active voice, common words, one idea per sentence.
- Do not use filler, hedges or marketing words.
- Terms: in prose, one rule is a "mapping", and one `[[mappings]]` entry is a "map". API names do not change (`compile_mapping`, `mapping_id`).
