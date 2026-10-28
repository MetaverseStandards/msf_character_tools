# Reference test gates

Original documentation: CC-BY-SA-4.0.

## Reference gates that ran

Final local gate: 30 tests passed on Python 3.12.15 and on the installed Python 3.11.17 wheel. The installed-package tests run from a working directory outside the checkout. Fixture generation gives the same bytes again, and check.py passes. Audits of the project's own public text and local links report zero private references and zero broken local links. Remote CI and production artist acceptance are separate gates.

`python -B -m unittest discover -s tests/public -v` and `python -B -m unittest discover -s tests/internal -t tests -v` run the real APIs and CLI commands in subprocesses. The analytical fixtures use direct axis equations and import nothing from the evaluator. Original binary32 accessor storage is decoded into binary64, so analytical equations written with decimal numbers can differ at binary32 input precision.

| Gate | Evidence |
| --- | --- |
| Authoring | Unknown keys, duplicate IDs, finite metadata, references, duplicates across fragments, versions, immutable validated inputs |
| Determinism | Exact checked-in pack, CSV and coverage bytes; SHA256; -0.0 and Unicode settings; real CLI runs with missing, out-of-date, extra and reordered outputs |
| Maps | Topological reorder, cycles, multiple writers, unit, calibration and domain constraints, the approximation and loss policy, refusal of unresolved inventory |
| Tracking | Signed valid input; invalid, missing, type, domain and time failures; no neutral substitution; output domain failure |
| Assets | Original GLB bytes, chunks, unknown extensions and attributes kept; malformed headers, bounds and NaN; interleaved, normalized, padded matrices; sparse indices and values; bounded zero accessors |
| Resource and sidecar | No remote fetch; resolver refuses traversal, symlinks and budget overruns; out-of-date asset, resource and sparse hashes; validation of structural destinations; canonical idempotence |
| Geometry | Two instances; relative signed morphs and morphs above 1, before four nonzero skin influences; head, jaw, accessory and unknown joint; rest versus bind; morph and skin apart; eight influences evaluated against direct equations; singular refusal |
| Curves and hierarchy | STEP, endpoints, component LINEAR, shortest quaternion slerp; duration-scaled Hermite with raw quaternion tangents; reparent refuses shear and singular transforms |
| CLI preservation | Annotate and check refuse output aliases, hard links and symlinks before any replacement; source bytes do not change |

Tolerances:
- Shared combined analytical fixture: largest absolute component error < 1e-6 m.
- Independent host fixture integration: its declared 1e-5 m position tolerance.
- Skin weight sum: 1e-6, a project acceptance choice. Weights are not normalized.
- Authored quaternion unit length: 0.00769 (the glTF-Validator's tolerance).
- Affine bottom row of a binary32 IBM: 1e-7.

The last two are project checks, not promises of universal equivalence.

## Public and internal suites

`tests/public` uses only the 29 names in `msf_character_tools.__all__` and the `msf-character-tools` command line, through `cli.main`. It is the gate that a reimplementation must keep passing unchanged. The C++ core in 0.4.0 passed it unchanged. In 0.5.0 only the package name changed in it: its imports, module paths and the `msf-character-tools` usage line. One comment also names a commit by its hash in the rewritten history. Its helpers and fixtures are inside it, and `tests/public.sha256` lists a SHA-256 for every file under it. It names no package version. It finds optional FBX and USD support by asking `inspect_asset`, not by package name, so a new release or core can pass it as it is. If a format has no working reader, its tests skip, unless `MSF_REQUIRE_FORMATS` names that format; in that case a missing or broken reader fails the suite. `scripts/ci_local.sh` sets `fbx`, or `fbx,usd` when `MSF` is set.

`tests/internal` covers private modules:
- record admission;
- the C++ core against the 0.3.0 oracle (an interpreter with msf-tools 0.3.0 installed, named by `MSF_ORACLE_PYTHON`, run out of process; see `tests/internal/oracle.py`):
  - authoring, fragment merging and pack outputs (`test_core_authoring.py`);
  - maps and samples (`test_core_mapping.py`);
  - `math3d`, also against CPython's `math.hypot` and `math.fsum` (`test_core_math3d.py`);
  - glTF and GLB inspection, accessors, sampling and geometry (`test_core_snapshot.py`);
  - the source adapters' path grammar, transforms, influences and GLB writer (`test_core_sources.py`);
  - in the corpus tier, every ufbx corpus file through the FBX adapter;
- JSON against the Python path, bit for bit (`test_core_json.py`);
- the source adapters' worker;
- the ufbx shim, through the core's test hooks;
- the diagnostics registry;
- the build record.

Internal tests may import public helpers. The public suite never imports internal code. A reimplementation deletes the internal tests together with the modules they cover.

`tests/internal/test_public_suite.py` fails when any file under `tests/public` differs from the manifest, and when a public test reaches past the public API. After you change the public suite on purpose, refresh the manifest:

```sh
python3 -B tests/internal/test_public_suite.py --write
```

## Reproduction

```sh
python3 -B -m unittest discover -s tests/public -v
python3 -B -m unittest discover -s tests/internal -t tests -v
python3 -B check.py
python3 -B tests/public/make_fixtures.py
python3 -B check.py
```

Fixture generation is deterministic. When fixtures are generated again, the checked-in source and golden bytes must stay equal. Analytical golden values must not come from evaluator output. Run the installed-wheel tests from a working directory outside the checkout, with both Python 3.11 and 3.12. Cross-platform CI runs the reference commands. Native gates belong to the native build integration.

`scripts/ci_local.sh` is the CI run while `.github/workflows/check.yml` is dormant (GitHub Actions is blocked by account billing). Use it while hosted CI is unavailable. It does these steps:
- It builds the C++ core in place for each Python, because msf-character-tools does not import without it.
- It runs the public and internal suites and `check.py` on local Python 3.11 and 3.12 environments (`MSF_PY311` / `MSF_PY312`, by default `python3.11` and `python3.12` on `PATH`), then the optional asset tiers.
- It runs the public suite once more without the core's fast paths (`MSF_TOOLS_PURE=1`, see [building](building.md)).
- It builds a wheel from a clean clone of HEAD, and checks the wheel's build record and contents.
- It reports the cmake and ninja versions (see [building](building.md)).
- It ends with a summary block for pull-request descriptions, and exits nonzero if any check fails.

Differential tests skip without the oracle, unless `MSF_REQUIRE_ORACLE=1`. The summary says which. The script sets `PYTHONHASHSEED=0`, because 0.3.0 checked a frame's channels in set order. The oracle inherits the setting.

Environment variables name the inputs that are outside the repository. A tier whose inputs are absent is skipped, and the summary lists it as skipped. The variables are `MSF_ORACLE_PYTHON`, `MSF_RCEF_ROOT` (gate tier), `MSF_OPENUSD_ASSETS`, `MSF_UFBX_CORPUS`, `MSF_KHRONOS_ASSETS`, `MSF_REAL_ASSETS`, `MSF_EXAMPLE_ASSETS` and `MSF_LIBFUZZER`. `MSF_REQUIRE_FORMATS` defaults to `fbx`, which is compiled in. Add `usd` to fail, instead of skip, when usd-core is not installed.

`MSF` names the maintainers' optional local workspace. When it is set, the interpreters and every input except `MSF_LIBFUZZER` default to places in it: `$MSF/_tools/venv3.11` and `venv3.12`, `$MSF/_tools/bin` for cmake and ninja, `$MSF/_tools/boot/bin/uv`, `$MSF/_tools/oracle-venv`, `$MSF/RCEF` and `$MSF/_viz/assets/...`. Also, `MSF_REQUIRE_ORACLE` and `MSF_REQUIRE_FORMATS=fbx,usd` default to on, so a missing oracle or USD reader fails the run.

`--gate` adds the gate tier, on both interpreters:
- 10^7 random float64 values against `repr`;
- wider JSON and Unicode fuzzing;
- 10^6 vectors per arity against `math.hypot`;
- 10^5 `math3d` cases;
- against the oracle: 10^4 glTF assets, and 2x10^4 each of node paths, matrices, influence sets and GLB scenes;
- every JSON file in RCEF at `MSF_RCEF_COMMIT` (default 96ac4be), read from `MSF_RCEF_ROOT` with Git.

`--sanitize` builds the core again, ufbx included, with ASan and UBSan, and runs the core tests, the FBX tests and the public suite on that build. `--fuzz` runs `scripts/fuzz.sh` for `MSF_FUZZ_SECONDS` (default 300) per harness.

On Linux (checked on CentOS Stream 9, x86_64 and aarch64), `scripts/ci_local.sh` runs the same tiers natively. The 0.3.0 oracle is built on the same machine: msf-tools at `v0.3.0` and its `native/ufbx` cffi package, installed into an interpreter named by `MSF_ORACLE_PYTHON`. If usd-core is installed there too and `MSF_ORACLE_SOURCE` names the `v0.3.0` checkout, the `docs/parity.md` check compares a new table with the table 0.3.0 gives on that machine. This is needed because usd-core's own arithmetic differs from the macOS build that measured the committed table.

More Linux and macOS notes:
- The sanitizer tier preloads the compiler's ASan runtime with `LD_PRELOAD`. Where GCC's `libasan` is not installed, `MSF_SANITIZE_CC` / `MSF_SANITIZE_CXX` select a clang and its runtime instead.
- The fuzz tier needs a clang with the fuzzer runtime (`MSF_FUZZ_CC` / `MSF_FUZZ_CXX`), such as an unpacked LLVM release, which needs no root access.
- Two public tests need JavaScriptCore and skip on systems other than macOS. One of them also needs jsonschema, so it skips wherever jsonschema is not installed.
- Apple clang has no libFuzzer, so on macOS the fuzz tier fails unless `MSF_LIBFUZZER` names one.

`scripts/fuzz.sh [SECONDS]` builds the libFuzzer harnesses in `core/fuzz` on an ASan and UBSan core in `build/fuzz`, and runs them side by side. The harnesses cover:
- glTF and GLB inspection, then every accessor, every animation and a geometry evaluation of what is admitted (`fuzz_gltf`);
- `data:` URIs;
- node paths and target keys, which must round-trip and sort antisymmetrically;
- FBX conversion through ufbx, then inspection of the generated GLB, which must be clean.

A harness fails on a sanitizer report, on an exception that the core does not document, or on anything that the Python boundary would report as `E_INTERNAL`. `MSF_FUZZ_ALLOW_INTERNAL=1` lets `E_INTERNAL` through. Apple clang has no fuzzer runtime, so build `libFuzzer.a` from compiler-rt's sources (`lib/fuzzer`, from the same LLVM release as the compiler): run `clang++ -O2 -g -fsanitize=address -std=c++17 -c` on each file, then `ar rcs`. Pass the result as `MSF_LIBFUZZER`. The ASan flag keeps container annotations consistent with the instrumented core.

## Real-asset recipe tier

`tests/public/test_real_assets.py` has one test per case in the `CASE_MATRIX.json` of the 09K real-asset harness plan. It runs when `MSF_REAL_ASSETS` names a local copy of the plan, the pinned Fox, RobotExpressiveHead and RobotExpressive assets, and the independent Decimal oracles (see the module docstring for the layout). Otherwise it skips. None of these files are committed. Exact bytes are compared with the plan's frozen pack, exports, sidecar, map, evaluated samples and refusal reports. Geometry is compared with the oracles at the tolerances in their `EXPECTATION_SPEC.json`. Some cases need installed artifacts, consumer repositories, DCC hosts or cost literals frozen elsewhere. These are skipped, with the reason.

N-influence skinning replaces two expectations. The eight-influence item in GEOMETRY-STRICT-TWINS now checks that the twin evaluates. H-INSPECT expects the geometry capability `linear_blend_skinning`, where the plan froze `four_influence_LBS`.

`python -B scripts/parity_table.py` generates `docs/parity.md` from new measurements. The table has independent references and consistency checks:
- Independent references: each synthetic USD scene against usd-core, the real glTF assets against the Decimal oracles, Kenney's FBX and GLB exports of one character against each other, and the DCC reference frames grouped by exporter.
- Consistency checks only: round trips through msf-character-tools' own FBX writer, for the USD scenes and the Khronos assets.

When all the inputs are present, `scripts/ci_local.sh` generates the table again and fails if the committed file differs.

## Examples tier

`tests/public/test_examples.py` runs the scripts in `examples/` (see `examples/README.md`) as a user would, in subprocesses. It uses the assets that `examples/fetch_assets.py` downloads at pinned revisions. The expected values do not come from msf-character-tools:
- asset hashes, counts and licence text;
- GLB data read with `struct`, with a morph delta applied by hand;
- usd-core's `BakeSkinning`;
- ufbx's own skinning of the Kenney character, and ufbx's evaluation of the writer-made FBX cube at each mapped shape-key weight;
- Kenney's separate GLB export of the character, within 1e-3 of the bounding-box diagonal;
- the Fox Decimal oracle, when `MSF_REAL_ASSETS` is set.

The check that the command line rebuilds the cube's files byte for byte is a reproducibility check only. The tier runs when `MSF_EXAMPLE_ASSETS` names the download folder.

## USD strict tier and demo

`tests/public/test_source_strict.py` reads each synthetic USD fixture in `tests/public/fixtures/source` (written by `python -B tests/public/make_source_fixtures.py`) three ways: as USDA, as USDC exported by usd-core, and as a stored USDZ. All three must give the same glTF document, and the declared losses or refusal listed for the case. The answers come from usd-core, which opens the fixture itself:
- triangles from its face counts, holes and orientation;
- world-space points at every authored time code, through `ComputeLocalToWorldTransform` or, for skinned meshes, `BakeSkinning` in linear-blend mode;
- normalized skin weights.

Positions must agree within 1e-5 of the bounding-box diagonal, and weights within 1e-6. The tests skip when usd-core is not installed.

`tests/public/test_source_openusd.py` is an optional tier on OpenUSD's own UsdSkel test scenes and tutorial assets (TOST-1.0, never committed here). It runs when `MSF_OPENUSD_ASSETS` names a local checkout that holds `pxr/usd/usdSkel/testenv` and `extras/usd/tutorials`, with OpenUSD's `LICENSE.txt`. Otherwise it skips. When those assets are present (`MSF_OPENUSD_ASSETS`, or `$MSF/_viz/assets/openusd` in a workspace), `scripts/ci_local.sh` runs this tier separately from the fast suite. Each asset must inspect, or be refused with its listed code. Its meshes must match usd-core's world-space points, as in the strict tier.

`tests/public/test_source_fbx.py` reads ASCII FBX files written by `tests/public/support/fbx_ascii.py`. Pivots, offsets, pre- and post-rotation and the three FBX inherit types are checked against two references: an independent implementation of the FBX SDK transform formula, and the archived Codex affine witness points. Skinned points, static and animated, are checked against ufbx's own skinning.

`tests/internal/test_source_fbx_corpus.py` is an optional tier over ufbx's test corpus (`MSF_UFBX_CORPUS`). Every file loads, except the expected failures. Every file inspects, or is refused with a mapped code.

`tests/internal/test_source_fbx_dcc.py` is in the same tier. It compares msf-character-tools' world-space points with the OBJ frames that Blender, Maya, 3ds Max and MotionBuilder exported together with the corpus files. It uses the pairings, frame times and per-file tolerances from ufbx's own tests. It does not rely on how ufbx or msf-character-tools read FBX. The expected axis rotation and unit come from the file's own GlobalSettings, which `tests/public/support/fbx_header.py` reads from its bytes. msf-character-tools' declared unit and axis conversion must agree with them.

A pairing that disagrees is explained only mesh by mesh:
- Every mesh with unmatched points must carry a declared loss that changes points (`W_SUBDIV_CAGE`, `W_POINTS_ANIMATION_DROPPED`, `W_INBETWEENS_DROPPED`, `W_INBETWEEN_PARTIAL`, `W_SKINNING_METHOD`).
- An OBJ point counts against the mesh of its nearest msf-character-tools point.
- Each explained row's match fractions are recorded in `tests/public/fixtures/dcc_differs.json`, and a row that gets worse fails.
- The only accepted refusal is a singular transform.

Skinned meshes at rest are compared too. They are skipped only when they differ and the rest pose differs from the bind pose that the OBJ holds. These are skipped altogether:
- OBJ files in skin bind space. To compare them needs the FBX bind pose of the mesh node, which the generated glTF does not carry.
- Frames that ufbx evaluates without extrapolation.

`tests/public/test_source_twins.py` is an optional tier (`MSF_KHRONOS_ASSETS`). It re-authors Khronos sample assets as FBX with the same nodes, meshes, skins, morph targets and first animation, and compares every primitive's world-space points with the glTF original at the keyframe times. `scripts/ci_local.sh` runs these tiers when the assets are present.

`python -B scripts/demo_fbx.py [file.fbx ...]` does the same for an ASCII rig made by the test writer and for any FBX files you give it (for example, binary files from the ufbx corpus). It prints the declared losses, the morph binding and the mesh at three animation times.

`python -B scripts/demo_usd.py` runs the skinned, animated rig fixture through an isolated reader as USDA, USDC and USDZ. It binds the fixture's blend shape, and prints the pose at 0, 0.5 and 1 seconds.

## Limits of acceptance

Numeric agreement covers the positions and curves that are explicitly supported, and the declared fixtures. It does not prove contacts, visual quality, general tracking calibration, performance on arbitrary production models, support for required extensions, normals or material parity. Geometry does not wait for a complete taxonomy. Real host tests and native ownership and numeric tests have separate owners and evidence. Inspecting syntax or source cannot count as running on a host. Later geometry formats, DQS, geometry rewriting, simultaneous clips and universal calibration need new capabilities and tests.

## Package 0.1.1 record and diagnostic regression gate

`tests/public/test_record_integrity.py` adds 21 tests for S-H1:
- Inputs use standard-library TOML and JSON, direct binary32 packing and an independent SHA256. The expected scalar values and one-point geometry values are literal analytic results.
- The tests assert that the shared package import comes from this checkout.
- Records that were replaced, constructed directly, out of date or tampered with are refused before execution or export. This covers stale raw data, views and hashes; changed resource, chunk, channel, binding, instruction and dependency records; and cyclic hierarchy records.
- Whitespace variants keep their distinct raw hashes and equal geometry.
- Diagnostics for giant numbers keep exact paths and independent authoring errors.
- Optional metadata validity is checked against both existing 1.0 schemas, with `jsonschema` as a test tool. It is not a runtime dependency of the distribution.

`tests/public/test_review_regressions.py` adds six independent review regressions:
- Work counts cover 3, 30 and 60 independent rules, at the compile, export and evaluate boundaries. The negative tests for mutation, copies, raw data and out-of-date data on fresh calls, and the literal order of declaration waves, are still required.
- Unicode cases cover every optional description and both coupling shapes (442 documents), valid Unicode, and numeric, boolean and opaque-metadata controls.
- Both complete schemas run through real Draft202012 validation twice: with Python regex, and with the pattern keyword given to the local JavaScriptCore ECMAScript regex. This is not a gate for a standalone JavaScript schema validator.
- A separate check tests all 82 nonblank pattern locations on 39 independently expected text cases, in both regex engines.
- Runtime metadata cases run even when the optional schema validator is absent.
- Tests that depend on JavaScriptCore skip explicitly if that local engine is unavailable. This does not imply a guarantee for any supported platform.

The full gate has 57 tests: 30 original, 21 from the first hardening and 6 review regressions. Review must keep the exact commands, runtime identities, counts and skips, and the semantic RED evidence. Run `python -B check.py` to check that the pack, CSV, coverage and checksum bytes do not change. Schema parity tests need the optional local `jsonschema` test dependency. Report missing tools as missing, or skip them explicitly. Never count them as a semantic RED.

## Pure numeric draft 03 gate

`tests/public/test_numerical_boundaries.py` adds 22 independent analytical tests. They test these cases through helpers and public callers:
- literal matrix, storage and point results, and noncommuting reparent results;
- reflected and explicit zero-scale controls;
- huge and tiny axes, overflow and underflow;
- strict bool, type and shape;
- role tolerance boundaries;
- signed huge morphs;
- singular POSITION blends;
- scalar identity and cancellation.

The expected values are written directly. The fixture bytes use direct binary32 packing. Agreement between native code and the reference is supplemental.

The builder correction gates ran these tests:
- 126 tests on Python 3.11.17 (two optional jsonschema skips) and on Python 3.12.15, a vendor-patched build (zero skips);
- 34 targeted tests on each;
- a check.py run that preserves bytes.

New separate builds with bindings ON passed 2 CTests each: the native analytical executable and seven agreement tests. These native gates test compatibility with the pure changes. Strict native types, setters, ownership and lifetime of nested getters, and native intermediate safety are still pending S-H4. Independent review of the draft is pending. A builder GREEN result is not acceptance.

`tests/public/test_numerical_branch_fixes.py` adds 12 builder regression methods for the four numeric review findings:
- Literal unchanged `(2,3,4)` skin positions cover both inactive palette overflow and inactive point overflow.
- Tests cover STEP at `2**-1074`, exact LINEAR and SLERP endpoints, and the declared sign of the endpoint hemisphere.
- They cover constant Hermite with a tiny duration and zero raw tangents, and signed raw tangents.
- They cover active ordered contributions, and admission of the original unused and extra inputs.

The saved tests from before the production change gave 16 semantic assertion failures on both real runtimes, with zero errors and zero skips (after a fixture-name correction). The original runs are still saved. The original 22 targeted methods and all 114 existing methods are kept.

The new builds with bindings ON from the numeric draft still apply. The native files, exported signatures, bridge and ordinary native callers did not change. This correction adds Python branch selection only. The exact native source hashes and the earlier build, log and artifact hashes come with the shared correction evidence. The Python gates do not imply a native rebuild or host qualification. Before acceptance, a new, independent, clean process must close the exact corrected tree. The earlier review's exit0 with error_event=true is not acceptance.

## Structural evidence draft 05 gate

`tests/public/test_structural_evidence.py` adds 24 methods. They use independent original storage documents and the corrected RCEF synthetic derivation literals:
- A static table of 27 rows (current, proposed, unresolved) admits five combinations and refuses 22.
- Twelve own-reference rows run at each of rule, source and target.
- Twelve mixed-reference negative tests use both list orders. Each has positive tests with all-current references and with an unreferenced bad reference.
- More cases cover every bad reference, current endpoints inside proposed rules, isolation of multiple inputs and of virtual intermediates, zero-weight inputs, the presence, value and null of identity metadata, and exact diagnostics.

Signed affine and the bilateral mean keep their explicit derivation and losses. The standalone proposed composite fixture keeps the literal document of the corrected design, and its independently expected values `.375,.625,.25,.75`. Exact arithmetic on one basis stays legal with empty assumptions. A different basis, or a declared approximation or loss, needs assumptions. Changes only to quality, or only to the target basis, can keep the numeric scope with opt-in and losses. Domain entailment is reviewed separately. These tests do not qualify RCEF source literals, providers or capture.

Before the compiler edit, both real runtimes saved 113 semantic assertion failures and zero errors. The legacy test that expected a manufactured loss now asserts a refusal when there is no authored annotation, and then that a supplied annotation is kept. That changed segment also saved one failure on each runtime. The original authoring data and generated goldens do not change. Schema and runtime tests keep known incompatible and empty inventory, without new schema keys or versions.

Builder GREEN results:
- 24 targeted methods and 150 full tests on Python 3.11.17 (one targeted and three full optional jsonschema skips);
- the same on Python 3.12.15, a vendor-patched build (zero skips, real Draft202012 schema validation);
- `check.py` passes on both.

Native and host gates that this change does not affect were not run again. The saved commands, source and test hashes, and the links from cases to RED results were recorded outside this repository. A new, independent review of the exact tree is still required. A builder GREEN result is not acceptance.
