# Reference test gates

Original documentation: CC-BY-SA-4.0.

## Executed reference gates

Final local gate:30 tests passed on Python3.12.15 and the installed Python3.11.17 wheel. The installed-package test run uses an outside working directory. Fixture regeneration is byte-identical, check.py passes, and owned public text/local-link audits report zero private references or broken local links. Remote CI/production artist acceptance are separate gates.

`python -B -m unittest discover -s tests -v` exercises actual APIs and subprocess CLI commands. Analytical fixtures use direct axis equations without imports from the evaluator. Original binary32 accessor storage is decoded into binary64; analytical authored decimal equations may differ at binary32 input precision.

| Gate | Evidence |
| --- | --- |
| Authoring | Unknown keys, duplicate IDs, metadata finiteness, references, fragment duplicates, versions, immutable validated inputs |
| Determinism | Exact checked-in pack/CSV/coverage bytes; SHA256; -0.0/Unicode settings; real CLI missing/stale/extra/reordered outputs |
| Mapping | Topological reorder, cycles, multiple writers, unit/calibration/domain constraints, approximation/loss policy, unresolved inventory refusal |
| Tracking | Signed valid input; invalid/missing/type/domain/time failures; no neutral substitution; output domain failure |
| Assets | Original GLB bytes/chunks/unknown extensions/attributes retained; malformed headers/bounds/NaN; interleaved normalized padded matrices; sparse indices/values; bounded zero accessors |
| Resource/sidecar | No remote fetch; resolver traversal/symlink/budget rejection; stale asset/resource/sparse hashes, structural destination validation, canonical idempotence |
| Geometry | Two instances; relative signed/>1 morphs before four nonzero skin influences; head/jaw/accessory/unknown joint; rest versus bind; separate morph and skin; eight influence and singular refusal |
| Curves/hierarchy | STEP, endpoints, component LINEAR, shortest quaternion slerp; duration-scaled Hermite with raw quaternion tangents; shear/singular reparent rejection |
| CLI preservation | Annotate/check output aliases, hardlinks/symlinks refused before any replacement; source bytes unchanged |

Shared combined analytical tolerance: max component absolute error <1e-6 m. Independent host fixture integration uses its declared1e-5 m position tolerance. Native agreement uses `abs1e-9 + rel1e-8` where documented by native tests. Skin weight sum tolerance1e-6 is a project acceptance choice; weights are not normalized. Quaternion authored unit-length tolerance 0.00769 (the glTF-Validator's) and affine bottom-row tolerance1e-7 for binary32 IBM are project checks, not universal equivalence promises.

## Reproduction

```sh
python3 -B -m unittest discover -s tests -v
python3 -B check.py
python3 -B tests/make_fixtures.py
python3 -B check.py
```

Fixture generation is deterministic. Regenerating fixtures must leave checked-in source/golden bytes equal; it must not derive analytical golden values from evaluator output. Installed wheel tests should run from an outside working directory with both Python3.11 and3.12. Cross-platform CI executes reference commands; native gates belong to native build integration.

`scripts/ci_local.sh` runs the same commands as `.github/workflows/check.yml` on local Python 3.11 and 3.12 environments (`$MSF/_tools/venv3.11` and `venv3.12` by default, or `MSF_PY311` / `MSF_PY312`). It also runs the native build and CTest when `cmake` and a C++ compiler are present, and otherwise reports them as SKIPPED. It ends with a summary block for pull-request descriptions and exits nonzero if any check fails. Use it while hosted CI is unavailable.

## Limits of acceptance

Numerical agreement covers the explicitly supported positions/curves and declared fixtures. It does not prove contacts, visual quality, general tracking calibration, performance on arbitrary production models, required extension support, normals or material parity. No full taxonomy completion gates geometry. Real host tests and native ownership/numerical tests have separate owners and evidence; syntax/source inspection cannot count as host execution. Later geometry formats, eight influences, DQS, geometry rewriting, simultaneous clips and universal calibration need new capabilities and tests.

## Package 0.1.1 record and diagnostic regression gate

`tests/test_record_integrity.py` adds 21 tests for S-H1. Inputs use stdlib TOML/JSON, direct binary32 packing and independent SHA256; expected scalar/one-point geometry values are literal analytic results. Tests assert the shared package import comes from this checkout. Replacement/direct-constructor, stale raw/view/hash, resource/chunk/channel/binding/instruction/dependency and cyclic hierarchy records refuse before execution/export. Whitespace variants retain their distinct raw hashes and equal geometry. Giant numeric diagnostics retain exact paths and independent authoring errors. Optional metadata validity is checked against both existing1.0 schemas using `jsonschema` as a test tool; it is not a distribution runtime dependency.

`tests/test_review_regressions.py` adds six independent review regressions. Work counts cover 3/30/60 independent rules and compile/export/evaluate boundaries; fresh-call mutation/copy/raw/stale negatives and literal declaration-wave order remain required. Unicode cases cover every optional description and both coupling shapes (442 documents), valid Unicode and numeric/boolean/opaque-metadata controls. Both complete schemas run through real Draft202012 validation with Python regex and with the pattern keyword delegated to local JavaScriptCore ECMAScript regex. This is not a standalone JavaScript schema-validator gate. A separate check tests all 82 nonblank pattern locations on 39 independently expected text cases in both regex engines. Runtime metadata cases execute even when the optional schema validator is absent. JavaScriptCore-dependent tests explicitly skip if that local engine is unavailable; no supported-platform guarantee is inferred.

The full gate contains 57 tests (30 original,21 initial hardening,6 review regressions). Review must retain exact commands, runtime identities, counts/skips and semantic RED evidence. Run `python -B check.py` to check unchanged pack/CSV/coverage/checksum bytes. Schema parity tests require the optional local `jsonschema` test dependency; missing tools must be reported as missing or explicitly skipped, never counted as a semantic RED.

## Pure numerical draft 03 gate

`tests/test_numerical_boundaries.py` adds22 independent analytical tests. Literal
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

`tests/test_numerical_branch_fixes.py` adds12 builder regression methods for the
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

`tests/test_structural_evidence.py` adds 24 methods with independent original
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
