# Reference test gates

Original documentation: CC-BY-SA-4.0.

## Executed reference gates

Final local gate:30 tests passed on Python3.12.15 and the installed Python3.11.17 wheel. The installed-package test run uses an outside working directory. Fixture regeneration is byte-identical, check.py passes, and owned public text/local-link audits report zero private references or broken local links. Remote CI/production artist acceptance are separate gates.

`python -B -m unittest discover -s tests/public -v` and `python -B -m unittest discover -s tests/internal -t tests -v` exercise actual APIs and subprocess CLI commands. Analytical fixtures use direct axis equations without imports from the evaluator. Original binary32 accessor storage is decoded into binary64; analytical authored decimal equations may differ at binary32 input precision.

| Gate | Evidence |
| --- | --- |
| Authoring | Unknown keys, duplicate IDs, metadata finiteness, references, fragment duplicates, versions, immutable validated inputs |
| Determinism | Exact checked-in pack/CSV/coverage bytes; SHA256; -0.0/Unicode settings; real CLI missing/stale/extra/reordered outputs |
| Mapping | Topological reorder, cycles, multiple writers, unit/calibration/domain constraints, approximation/loss policy, unresolved inventory refusal |
| Tracking | Signed valid input; invalid/missing/type/domain/time failures; no neutral substitution; output domain failure |
| Assets | Original GLB bytes/chunks/unknown extensions/attributes retained; malformed headers/bounds/NaN; interleaved normalized padded matrices; sparse indices/values; bounded zero accessors |
| Resource/sidecar | No remote fetch; resolver traversal/symlink/budget rejection; stale asset/resource/sparse hashes, structural destination validation, canonical idempotence |
| Geometry | Two instances; relative signed/>1 morphs before four nonzero skin influences; head/jaw/accessory/unknown joint; rest versus bind; separate morph and skin; eight influences evaluated against direct equations; singular refusal |
| Curves/hierarchy | STEP, endpoints, component LINEAR, shortest quaternion slerp; duration-scaled Hermite with raw quaternion tangents; shear/singular reparent rejection |
| CLI preservation | Annotate/check output aliases, hardlinks/symlinks refused before any replacement; source bytes unchanged |

Shared combined analytical tolerance: max component absolute error <1e-6 m. Independent host fixture integration uses its declared1e-5 m position tolerance. Skin weight sum tolerance1e-6 is a project acceptance choice; weights are not normalized. Quaternion authored unit-length tolerance 0.00769 (the glTF-Validator's) and affine bottom-row tolerance1e-7 for binary32 IBM are project checks, not universal equivalence promises.

## Public and internal suites

`tests/public` uses only the 29 names in `msf_tools.__all__` and the `msf-tools` command line, through `cli.main`. It is the gate a reimplementation, such as the planned C++ core, must keep passing unchanged. Its helpers and fixtures live inside it, and `tests/public.sha256` lists a SHA-256 for every file under it. It names no package version and finds optional FBX and USD support by asking `inspect_asset`, not by package name, so a new release or core can pass it as it stands. A format without a working reader makes its tests skip, unless `MSF_REQUIRE_FORMATS` names it (`scripts/ci_local.sh` sets `fbx,usd`); then a missing or broken reader fails the suite.

`tests/internal` covers private modules: checked maths in `math3d`, record admission, the C++ core against the pure-Python path (`test_core.py` for mappings and `test_core_json.py` for JSON, bit for bit), the source adapters' worker, GLB writer and path grammar, the ufbx shim through cffi, the diagnostics registry and the build record. Its tests may import public helpers; the public suite never imports internal code. A reimplementation deletes internal tests along with the modules they cover.

`tests/internal/test_public_suite.py` fails when any file under `tests/public` differs from the manifest, and when a public test reaches past the public API. After a deliberate change to the public suite, refresh the manifest:

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

Fixture generation is deterministic. Regenerating fixtures must leave checked-in source/golden bytes equal; it must not derive analytical golden values from evaluator output. Installed wheel tests should run from an outside working directory with both Python3.11 and3.12. Cross-platform CI executes reference commands; native gates belong to native build integration.

`scripts/ci_local.sh` is the CI run while `.github/workflows/check.yml` is dormant (GitHub Actions is blocked by account billing). It runs the public and internal suites and `check.py` on local Python 3.11 and 3.12 environments (`$MSF/_tools/venv3.11` and `venv3.12` by default, or `MSF_PY311` / `MSF_PY312`), then the optional asset tiers. It first builds the C++ core in place for each Python and sets `MSF_REQUIRE_CORE=1`, so core tests fail rather than skip without it, and it runs the public suite once more on the pure-Python path (`MSF_TOOLS_PURE=1`). It also builds a wheel from a clean clone of HEAD and checks its build record and contents, and reports the cmake and ninja versions under `$MSF/_tools/bin` (see [building](building.md)). It ends with a summary block for pull-request descriptions and exits nonzero if any check fails. Use it while hosted CI is unavailable.

`--gate` adds the gate tier: 10^7 random float64 values against `repr`, wider JSON and Unicode fuzzing, and every JSON file in RCEF at `MSF_RCEF_COMMIT` (default 0d90172) read from `MSF_RCEF_ROOT` with Git. `--sanitize` rebuilds the core with ASan and UBSan and runs the core tests and the public suite on it.

## Real-asset recipe tier

`tests/public/test_real_assets.py` has one test per case in the 09K real-asset harness plan's `CASE_MATRIX.json`. It runs when `MSF_REAL_ASSETS` names a local copy of the plan, the pinned Fox, RobotExpressiveHead and RobotExpressive assets and the independent Decimal oracles (see the module docstring for the layout), and skips otherwise; none of it is committed. Exact bytes are compared with the plan's frozen pack, exports, sidecar, mapping, evaluated samples and refusal reports, and geometry with the oracles at the tolerances in their `EXPECTATION_SPEC.json`. Cases that need installed artifacts, consumer repositories, DCC hosts or cost literals frozen elsewhere are skipped with the reason. Two expectations are superseded by N-influence skinning. The eight-influence item in GEOMETRY-STRICT-TWINS now checks that the twin evaluates. H-INSPECT expects the geometry capability `linear_blend_skinning` where the plan froze `four_influence_LBS`.

`docs/parity.md` is generated by `python -B scripts/parity_table.py` from fresh measurements. Independent references: each synthetic USD scene against usd-core, the real glTF assets against the Decimal oracles, Kenney's FBX and GLB exports of one character against each other, and the DCC reference frames grouped by exporter. Consistency checks only: round trips through msf-tools' own FBX writer, for the USD scenes and the Khronos assets. `scripts/ci_local.sh` regenerates it when all the inputs are present and fails if the committed file differs.

## Examples tier

`tests/public/test_examples.py` runs the scripts in `examples/` (see `examples/README.md`) as a user would, in subprocesses, on the assets `examples/fetch_assets.py` downloads at pinned revisions. The expected values do not come from msf-tools:
- asset hashes, counts and licence text;
- GLB data read with `struct`, with a morph delta applied by hand;
- usd-core's `BakeSkinning`;
- ufbx's own skinning of the Kenney character, and ufbx's evaluation of the writer-made FBX cube at each mapped shape-key weight;
- Kenney's separate GLB export of the character, within 1e-3 of the bounding-box diagonal;
- the Fox Decimal oracle, when `MSF_REAL_ASSETS` is set.

The check that the command line rebuilds the cube's files byte for byte is a reproducibility check only. The tier runs when `MSF_EXAMPLE_ASSETS` names the download folder.

## USD strict tier and demo

`tests/public/test_source_strict.py` reads each synthetic USD fixture in `tests/public/fixtures/source` (written by `python -B tests/public/make_source_fixtures.py`) as USDA, as USDC exported by usd-core and as a stored USDZ. All three must give the same glTF document and the declared losses or refusal listed for the case. The answers come from usd-core opening the fixture itself: triangles from its face counts, holes and orientation; world-space points at every authored time code, through `ComputeLocalToWorldTransform` or, for skinned meshes, `BakeSkinning` in linear-blend mode; and normalized skin weights. Positions must agree within 1e-5 of the bounding-box diagonal and weights within 1e-6. The tests skip when usd-core is not installed.

`tests/public/test_source_openusd.py` is an optional tier on OpenUSD's own UsdSkel test scenes and tutorial assets (TOST-1.0, never committed here). It runs when `MSF_OPENUSD_ASSETS` names a local checkout holding `pxr/usd/usdSkel/testenv` and `extras/usd/tutorials` with OpenUSD's `LICENSE.txt`, and skips otherwise. `scripts/ci_local.sh` runs it separately from the fast suite when `$MSF/_viz/assets/openusd` exists. Each asset must inspect, or be refused with its listed code, and its meshes must match usd-core's world-space points as in the strict tier.

`tests/public/test_source_fbx.py` reads ASCII FBX files written by `tests/public/support/fbx_ascii.py`. Pivots, offsets, pre/post rotation and the three FBX inherit types are checked against an independent implementation of the FBX SDK transform formula and against the archived Codex affine witness points; skinned points, static and animated, are checked against ufbx's own skinning. `tests/internal/test_source_fbx_corpus.py` is an optional tier over ufbx's test corpus (`MSF_UFBX_CORPUS`): every file loads except the expected failures, and every file inspects or is refused with a mapped code. `tests/internal/test_source_fbx_dcc.py`, in the same tier, compares msf-tools' world-space points with the OBJ frames that Blender, Maya, 3ds Max and MotionBuilder exported alongside the corpus files, using the pairings, frame times and per-file tolerances from ufbx's own tests; it does not rely on ufbx's or msf-tools' reading of FBX. The expected axis rotation and unit come from the file's own GlobalSettings, read from its bytes by `tests/public/support/fbx_header.py`; msf-tools' declared unit and axis conversion must agree with them. A pairing that disagrees is explained only mesh by mesh. Every mesh with unmatched points must carry a declared loss that changes points (`W_SUBDIV_CAGE`, `W_POINTS_ANIMATION_DROPPED`, `W_INBETWEENS_DROPPED`, `W_INBETWEEN_PARTIAL`, `W_SKINNING_METHOD`); an OBJ point counts against the mesh of its nearest msf-tools point. Each explained row's match fractions are recorded in `tests/public/fixtures/dcc_differs.json`, and a row that gets worse fails. The only accepted refusal is a singular transform. Skinned meshes at rest are compared too. They are skipped only when they differ and the rest pose differs from the bind pose the OBJ holds. Skipped altogether: OBJ files in skin bind space (comparing them needs the FBX bind pose of the mesh node, which the generated glTF does not carry), and frames ufbx evaluates without extrapolation. `tests/public/test_source_twins.py` is an optional tier (`MSF_KHRONOS_ASSETS`) that re-authors Khronos sample assets as FBX with the same nodes, meshes, skins, morph targets and first animation, and compares every primitive's world-space points with the glTF original at the keyframe times. `scripts/ci_local.sh` runs these tiers when the assets are present.

`python -B scripts/demo_fbx.py [file.fbx ...]` does the same for an ASCII rig made by the test writer and any FBX files given (for example binary files from the ufbx corpus), printing declared losses, the morph binding and the mesh at three animation times.

`python -B scripts/demo_usd.py` runs the skinned, animated rig fixture through an isolated reader as USDA, USDC and USDZ, binds its blend shape, and prints the pose at 0, 0.5 and 1 seconds.

## Limits of acceptance

Numerical agreement covers the explicitly supported positions/curves and declared fixtures. It does not prove contacts, visual quality, general tracking calibration, performance on arbitrary production models, required extension support, normals or material parity. No full taxonomy completion gates geometry. Real host tests and native ownership/numerical tests have separate owners and evidence; syntax/source inspection cannot count as host execution. Later geometry formats, DQS, geometry rewriting, simultaneous clips and universal calibration need new capabilities and tests.

## Package 0.1.1 record and diagnostic regression gate

`tests/public/test_record_integrity.py` adds 21 tests for S-H1. Inputs use stdlib TOML/JSON, direct binary32 packing and independent SHA256; expected scalar/one-point geometry values are literal analytic results. Tests assert the shared package import comes from this checkout. Replacement/direct-constructor, stale raw/view/hash, resource/chunk/channel/binding/instruction/dependency and cyclic hierarchy records refuse before execution/export. Whitespace variants retain their distinct raw hashes and equal geometry. Giant numeric diagnostics retain exact paths and independent authoring errors. Optional metadata validity is checked against both existing1.0 schemas using `jsonschema` as a test tool; it is not a distribution runtime dependency.

`tests/public/test_review_regressions.py` adds six independent review regressions. Work counts cover 3/30/60 independent rules and compile/export/evaluate boundaries; fresh-call mutation/copy/raw/stale negatives and literal declaration-wave order remain required. Unicode cases cover every optional description and both coupling shapes (442 documents), valid Unicode and numeric/boolean/opaque-metadata controls. Both complete schemas run through real Draft202012 validation with Python regex and with the pattern keyword delegated to local JavaScriptCore ECMAScript regex. This is not a standalone JavaScript schema-validator gate. A separate check tests all 82 nonblank pattern locations on 39 independently expected text cases in both regex engines. Runtime metadata cases execute even when the optional schema validator is absent. JavaScriptCore-dependent tests explicitly skip if that local engine is unavailable; no supported-platform guarantee is inferred.

The full gate contains 57 tests (30 original,21 initial hardening,6 review regressions). Review must retain exact commands, runtime identities, counts/skips and semantic RED evidence. Run `python -B check.py` to check unchanged pack/CSV/coverage/checksum bytes. Schema parity tests require the optional local `jsonschema` test dependency; missing tools must be reported as missing or explicitly skipped, never counted as a semantic RED.

## Pure numerical draft 03 gate

`tests/public/test_numerical_boundaries.py` adds22 independent analytical tests. Literal
matrix/storage/point and noncommuting reparent results, reflected and explicit
zero-scale controls, huge/tiny axes, overflow/underflow, strict bool/type/shape,
role tolerance boundaries, signed huge morphs, singular POSITION blends and
scalar identity/cancellation are tested through helpers and public callers.
Expected values are authored directly; fixture bytes use direct binary32 packing.
Native/reference agreement is supplemental.

Builder correction gates run126 tests on Python3.11.17 (two optional jsonschema skips) and
Python3.12.15+meta (zero skips), plus34 targeted tests each and byte-preserving
check.py. Fresh separate bindings ON builds pass2 CTests each: native analytical
executable and seven agreement tests. These native gates test compatibility with
the pure changes; strict native types, setters, nested getter ownership/lifetime
and native intermediate safety remain pending S-H4. Independent draft review is
pending; builder GREEN is not acceptance.

`tests/public/test_numerical_branch_fixes.py` adds12 builder regression methods for the
four numerical review findings. Literal unchanged `(2,3,4)` skin positions cover
both inactive palette overflow and inactive point overflow. Tests cover STEP at
`2**-1074`, exact LINEAR/SLERP endpoints, the declared endpoint hemisphere sign,
constant Hermite with tiny duration and zero raw tangents, signed raw tangents,
active ordered contributions and original unused/extra input admission. The
saved pre-production tests produced16 semantic assertion failures on both actual
runtimes, zero errors/skips after a fixture-name correction; original runs remain
saved. The original22 targeted methods and all114 existing methods are retained.

Fresh bindings ON compatibility builds from the numerical draft remain applicable:
native files, exported signatures, bridge and ordinary native callers are unchanged.
This correction adds Python branch selection only. Exact native source hashes and
prior build/log/artifact hashes accompany the shared correction evidence. No
native rebuild or host qualification is inferred from the Python gates. A new
fresh independent clean process must close the exact corrected tree before
acceptance; the earlier review's exit0 with error_event=true is not acceptance.

## Structural evidence draft 05 gate

`tests/public/test_structural_evidence.py` adds 24 methods with independent original
storage documents and the corrected RCEF synthetic derivation literals. A static
27-row current/proposed/unresolved table admits five combinations and refuses
22. Twelve own-reference rows run at each of rule/source/target. Twelve mixed
reference negatives use both list orders, each with all-current and unreferenced
bad-reference positives. Additional cases cover every bad reference, current
endpoints inside proposed rules, multi-input and virtual-intermediate isolation,
zero-weight inputs, identity metadata presence/value/null and exact diagnostics.

Signed affine and bilateral mean preserve their explicit derivation and losses.
The standalone proposed composite fixture preserves the corrected design's
literal document and independently expected `.375,.625,.25,.75`. Exact arithmetic
on one basis remains legal with empty assumptions; distinct basis or declared
approximation/loss needs assumptions. Quality-only and target-basis-only changes
can retain numerical scope with opt-in/losses. Domain entailment is separately
reviewed. These tests do not qualify RCEF source literals, providers or capture.

Both actual runtimes saved 113 semantic assertion failures, zero errors, before
the compiler edit. The legacy test that expected a manufactured loss now asserts
refusal without an authored annotation, then retention of a supplied annotation;
that changed segment also saved one failure on each runtime. Original authoring
data and generated goldens remain unchanged. Schema/runtime tests preserve
known incompatible/empty inventory without adding schema keys or versions.

Builder GREEN: 24 targeted methods and 150 full tests on Python3.11.17 (one
targeted and three full optional jsonschema skips), and Python3.12.15+meta (zero
skips, actual Draft202012 schema validation). `check.py` passes on both. No
unaffected native/host gate was rerun. Saved commands/source/test hashes and
case-to-RED links accompany the private draft handoff. Fresh independent exact
tree review remains required; builder GREEN is not acceptance.
