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
- **Compiled mappings.** `compile_mapping` serializes `{instructions, required_inputs, output_ids}` as JSON in Python. This is not `canonical_json`: it keeps key order and the sign of zero, which `canonical_json` drops, so the rebuilt views are identical to the pure path's. It compiles a slot program from those bytes and hands both to `_core.compile`. The record's views are then rebuilt from `handle.document()` alone. Each integrity check asserts that the same serialization of the views equals the handle's bytes. The fingerprint covers the views and the handle's bytes. `_core.compile` checks every shape in the spec it is given and reports a malformed one as `E_INTERNAL`.
- **Evaluated values.** The handle holds the frame count, the timestamps and the output values as binary64 buffers. `samples` is the view `handle.view()` builds: the same nested proxies the Python path produces. The fingerprint hashes the handle's state in place of walking the views (`_handle_views`). The consistency check compares the views with the buffers by exact type and bit pattern, so a replaced or edited view is refused.
- **The boundary.** Per call, only samples go in and a frame handle comes out. The core takes only exact lists, tuples and dicts with `str` keys, exact `float`s and `int`s up to 2^53, explicit `True` validity and in-domain values. For anything else, including every checked-arithmetic refusal, it returns `None`, and the unchanged Python path runs and reports the diagnostics. The same Python path runs when the extension is missing or `MSF_TOOLS_PURE=1` is set.
- **Arithmetic.** The core mirrors `math3d`'s checked add, subtract, product and divide, Python's `min`/`max` tie behaviour (which decides signed zeros), `bisect_right` knot lookup and sequential summation from 0.0. It is compiled with `-ffp-contract=off`, never `-ffast-math`. A test with affine scale 1+2^-30, input 1-2^-30 and offset -1 must give exactly 0.0, which an FMA would not.
- **Accepted handles.** Admission accepts only handle types fixed when `msf_tools._native` is imported. An object that merely offers `__msf_state__` is refused like any other unsupported state.

## Consequences

- At go/no-go 1, `evaluate_mapping` over 100,000 frames ran 36-38x (three rules) and 44-46x (52 outputs) faster than the 0.3.0 wheel (`scripts/bench.py`, median of 5, Apple arm64, Python 3.12). `compile_mapping` costs 15 to 27 % more for the document round trip, depending on load: 1.3 to about 1.6 ms (three rules) and 18 to about 22 ms (52 outputs).
- Evaluation semantics now exist twice. `tests/internal/test_core.py` requires bit-identical, same-typed samples and identical diagnostics from both paths. `scripts/ci_local.sh` also runs the public suite on the pure path.
- Wheels are per Python version and platform. Building from source needs a C++17 compiler and CMake 3.24 or newer.
- Fingerprints of handle-backed records hash binary buffers. Fingerprints have always been process-local and are never persisted.
- Later slices that move more state into the core follow the same rule: views are built only from the handle's export and checked against it at admission.
