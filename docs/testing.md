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

Shared combined analytical tolerance: max component absolute error <1e-6 m. Independent host fixture integration uses its declared1e-5 m position tolerance. Native agreement uses `abs1e-9 + rel1e-8` where documented by native tests. Skin weight sum tolerance1e-6 is a project acceptance choice; weights are not normalized. Quaternion authored unit tolerance1e-5 and affine bottom-row tolerance1e-7 for binary32 IBM are project checks, not universal equivalence promises.

## Reproduction

```sh
python3 -B -m unittest discover -s tests -v
python3 -B check.py
python3 -B tests/make_fixtures.py
python3 -B check.py
```

Fixture generation is deterministic. Regenerating fixtures must leave checked-in source/golden bytes equal; it must not derive analytical golden values from evaluator output. Installed wheel tests should run from an outside working directory with both Python3.11 and3.12. Cross-platform CI executes reference commands; native gates belong to native build integration.

## Limits of acceptance

Numerical agreement covers the explicitly supported positions/curves and declared fixtures. It does not prove contacts, visual quality, general tracking calibration, performance on arbitrary production models, required extension support, normals or material parity. No full taxonomy completion gates geometry. Real host tests and native ownership/numerical tests have separate owners and evidence; syntax/source inspection cannot count as host execution. Later geometry formats, eight influences, DQS, geometry rewriting, simultaneous clips and universal calibration need new capabilities and tests.
