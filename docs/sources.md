# Public source evidence

Original documentation: CC-BY-SA-4.0. Claims about sources are limited to the contracts this project implements and to cited format behaviour. [source-lock.json](source-lock.json) records the digests of the bytes that were fetched, and the retrieval date. Fixture data reproduces no external standards text.

| Public source | Pin | Used for |
| --- | --- | --- |
| [glTF2 specification](https://github.com/KhronosGroup/glTF/blob/8e691206fa2e981fc3b8c8bc57e671595576c971/specification/2.0/Specification.adoc) | 8e691206fa2e981fc3b8c8bc57e671595576c971 | Binary layout, sparse accessors, morphs, skins, nodes, animation and GLB chunks |
| [CPython JSON documentation](https://github.com/python/cpython/blob/v3.11.17/Doc/library/json.rst) | v3.11.17 | Exact serializer options and the finite JSON contract |
| [CPython CSV documentation](https://github.com/python/cpython/blob/v3.11.17/Doc/library/csv.rst) | v3.11.17 | Minimal quoting and LF writer settings |
| [RCSF baseline](https://github.com/MetaverseStandards/RCSF/tree/f6c3ea8a00d4901496326b4a6fe6a24913a563c6) | f6c3ea8a00d4901496326b4a6fe6a24913a563c6 | The consumer boundary and inherited survey licensing; no baseline rows are copied into shared fixtures |
| [CC BY-SA 4.0 legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en) | Licence version 4.0 | Terms for original documentation, data and fixtures |

The first three source files were fetched from pinned raw URLs, and their SHA-256 digests recorded. The Creative Commons website refused a direct plain-text fetch of the legal code, so the bundled licence text comes from the official Creative Commons source repository. The RCSF evidence is a pinned reference. It does not claim that RCSF's runtime, or all of its semantics, have passed this library's tests.

The original fixtures and mathematical oracles are this project's own work. Their expected values use analytical rotations, Hermite basis coefficients and simple affine sums. The numeric fixture tolerances are acceptance choices of this project. Full visual and artist contact acceptance, support for more formats and provider calibration are separate evidence gaps.
