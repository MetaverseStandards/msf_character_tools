# ADR 0001: Who owns record state once there is a C++ core

Original documentation: CC-BY-SA-4.0.

Status: accepted for the S0 slice, pending go/no-go 1.

## Context

In 0.3.0, every record (`CompiledMapping`, `EvaluatedValues` and the rest) is a frozen dataclass. A factory admits it: `records._admit` copies its state into immutable containers and stores a fingerprint. Every public boundary then calls `_check_integrity`, which recomputes the fingerprint and runs the record's consistency check. This is the API invariant: a record reaching a boundary is one a factory made, unchanged.

RCEF reads the document views directly, for example `compiled.instructions[i]['evidence_status']` and `compiled.required_inputs`, so their shapes are part of the contract.

Profiling 0.3.0 on 100,000 frames of a three-rule mapping took about 2 s. About 70 % of that was admission of `EvaluatedValues`: copying every frame into proxies and fingerprinting them twice. The rest was the per-frame interpreter. A faster evaluator alone cannot reach 5x; the per-frame Python state has to go too.

## Options

- **A. C++ owns the records; Python holds proxies.** Rejected. Admission, `dataclasses.replace` refusal, fingerprints and every view RCEF reads would have to be reimplemented across the boundary, which means a large surface and a second integrity model.
- **B. Python owns everything; C++ is a stateless kernel.** Rejected. The compiled program would be marshalled on every call. `EvaluatedValues` would still own and fingerprint each frame in Python, which is the 70 %.
- **C. A columnar public API (arrays in, arrays out).** Not taken now. It changes the public API, and H meets the gate without it. It needs a separate decision.
- **H. Python keeps the shells; each holds an immutable C++ handle built once.** Chosen.

## Decision (option H)

- `CompiledMapping` and `EvaluatedValues` stay frozen dataclasses, admitted by `_admit` and checked by `_check_integrity`. Each has a `_core` field (`init=False`, so `replace` drops it) holding a handle from `msf_tools._core`. A handle cannot be changed after it is built.
- **Compiled mappings.** `_core.compile_mapping` compiles the mapping in C++ from the pack's `Document` handle and returns a `CompiledRules` handle. The record's views (`instructions`, `required_inputs`, `output_ids`) are built only by `handle.views()`. Each integrity check asserts that the record holds exactly those view objects. The views are deeply immutable (proxies, tuples and scalars), so an equal copy is refused just like an edited one. It also asserts that the handle was compiled from this record's pack handle and mapping ID. The fingerprint hashes the handle's state in place of the views. Validated authoring and packs follow the same rule: their `document` is the view of a `Document` handle, bound to it by identity.
- **Evaluated values.** The handle holds the frame count, the timestamps and the output values as binary64 buffers. `samples` is the view `handle.view()` builds: the same nested proxies the Python path produces. The fingerprint hashes the handle's state in place of walking the views (`_handle_views`). The consistency check compares the views with the buffers by exact type and bit pattern, so an edited view is refused. Unlike the compiled views and the pack document, an equal copy of `samples` (same types, same bits) is accepted.
- **The boundary.** Per call, only samples go in and a frame handle comes out. The fast path takes only exact lists, tuples and dicts with `str` keys, exact `float`s and `int`s up to 2^53, explicit `True` validity and in-domain values. For anything else, including every checked-arithmetic refusal, it returns `None`, and the core's exact path (`evaluate_exact`, also C++) evaluates the samples and reports the diagnostics with 0.3.0's semantics. There is no Python fallback: the extension is required, and `MSF_TOOLS_PURE=1` only skips the fast path.
- **Arithmetic.** The core mirrors `math3d`'s checked add, subtract, product and divide, Python's `min`/`max` tie behaviour (which decides signed zeros), `bisect_right` knot lookup and sequential summation from 0.0. It is compiled with `-ffp-contract=off`, never `-ffast-math`. A test with affine scale 1+2^-30, input 1-2^-30 and offset -1 must give exactly 0.0, which an FMA would not.
- **Accepted handles.** Admission accepts only handle types fixed when `msf_tools._native` is imported. An object that merely offers `__msf_state__` is refused like any other unsupported state.

## Consequences

- At go/no-go 1, `evaluate_mapping` over 100,000 frames ran 36-38x (three rules) and 44-46x (52 outputs) faster than the 0.3.0 wheel (`scripts/bench.py`, median of 5, Apple arm64, Python 3.12). `compile_mapping` costs 15 to 27 % more for the document round trip, depending on load: 1.3 to about 1.6 ms (three rules) and 18 to about 22 ms (52 outputs). Since phase C the core compiles the mapping itself with no document round trip, and `compile_mapping` is 2.3 to 2.8x faster than 0.3.0.
- Evaluation semantics exist twice, in the fast and exact paths, both C++. `tests/internal/test_core_mapping.py` requires both to match the 0.3.0 oracle (out of process) exactly: same-typed samples, float bits and diagnostics. `scripts/ci_local.sh` also runs the public suite without the fast paths (`MSF_TOOLS_PURE=1`).
- Wheels are per Python version and platform. Building from source needs a C++17 compiler and CMake 3.24 or newer.
- Fingerprints of handle-backed records hash binary buffers. Fingerprints have always been process-local and are never persisted.
- Later slices that move more state into the core follow the same rule: views are built only from the handle's export and checked against it at admission.
