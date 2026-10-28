# ADR 0001: Who owns record state once there is a C++ core

Original documentation: CC-BY-SA-4.0.

Status: accepted for the S0 slice, pending go/no-go 1.

## Context

In 0.3.0, every record (`CompiledMapping`, `EvaluatedValues` and the rest) is a frozen dataclass. A factory admits it: `records._admit` copies its state into immutable containers and stores a fingerprint. Every public boundary then calls `_check_integrity`, which computes the fingerprint again and runs the record's consistency check. This is the API invariant: a record that reaches a boundary was made by a factory and has not changed since.

RCEF reads the document views directly, for example `compiled.instructions[i]['evidence_status']` and `compiled.required_inputs`. So their shapes are part of the contract.

Profiling 0.3.0 on 100,000 frames of a three-rule map took about 2 s. About 70 % of that time was admission of `EvaluatedValues`: copying every frame into proxies and fingerprinting them twice. The rest was the per-frame interpreter. A faster evaluator alone cannot reach 5x. The per-frame Python state has to go too.

## Options

- **A. C++ owns the records, and Python holds proxies.** Rejected. Admission, the refusal of `dataclasses.replace`, fingerprints and every view RCEF reads would have to be built again across the boundary. That is a large surface and a second integrity model.
- **B. Python owns everything, and C++ is a stateless kernel.** Rejected. Every call would marshal the compiled program. `EvaluatedValues` would still own and fingerprint each frame in Python, which is the 70 %.
- **C. A columnar public API (arrays in, arrays out).** Not taken now. It changes the public API, and H meets the gate without it. It needs a separate decision.
- **H. Python keeps the shells, and each shell holds an immutable C++ handle built once.** Chosen.

## Decision (option H)

- `CompiledMapping` and `EvaluatedValues` stay frozen dataclasses, admitted by `_admit` and checked by `_check_integrity`. Each has a `_core` field that holds a handle from `msf_tools._core`. The field is `init=False`, so `replace` drops it. A handle cannot change after it is built.
- Compiled maps: `_core.compile_mapping` compiles the map in C++ from the pack's `Document` handle, and returns a `CompiledRules` handle. Only `handle.views()` builds the record's views (`instructions`, `required_inputs`, `output_ids`). Each integrity check asserts that the record holds exactly those view objects. The views are deeply immutable (proxies, tuples and scalars), so an equal copy is refused, the same as an edited one. The check also asserts that the handle was compiled from this record's pack handle and map ID (`mapping_id`). The fingerprint hashes the handle's state instead of the views. Validated authoring and packs follow the same rule: their `document` is the view of a `Document` handle, bound to it by identity.
- Evaluated values: the handle holds the frame count, the timestamps and the output values as binary64 buffers. `samples` is the view that `handle.view()` builds: the same nested proxies that the Python path produces. The fingerprint hashes the handle's state instead of walking the views (`_handle_views`). The consistency check compares the views with the buffers by exact type and bit pattern, so an edited view is refused. An equal copy of `samples` (same types, same bits) is accepted. This is different from the compiled views and the pack document.
- Snapshots and geometry (phase D): `inspect_asset` parses, validates and decodes in C++ (`_core.inspect_gltf`). It returns a `Snapshot` handle that holds the original bytes, the parsed document, the chunks and the consumed resource bytes. `AssetSnapshot` keeps its fields. `original_bytes`, `document`, `resources`, `chunks`, `channels`, `bindings` and `source` are handle views, bound by identity, and so are the fields of each `Resource` and `Chunk`. `format` and `sha256` stay ordinary fields that must equal the handle's. An equal copy of any view is refused. 0.3.0 accepted such copies for the bytes and the frozen containers.

  In 0.3.0, on each public call, the consistency check parsed and validated the asset again, validated the bindings again and hashed every resource. The handle makes those facts permanent, so they are checked once, at admission. Admission also runs the checks that the first consistency check could still refuse: the fingerprint's `UnicodeEncodeError` for a lone surrogate, validation against the record's own component caps when inspection used other limits, and `_check_source`. Profile snapshots are built on a `Snapshot` handle too. `GeometryValues.instances` is the view of a `Positions` handle and is bound by identity. Sidecar and binding validation, `LocalResolver` and source conversion stay in Python and read the views.
- The boundary: per call, only samples go in and a frame handle comes out. The fast path takes only exact lists, tuples and dicts with `str` keys, exact `float`s, `int`s up to 2^53, explicit `True` validity and values in their domains. For anything else, every checked-arithmetic refusal included, it returns `None`. Then the core's exact path (`evaluate_exact`, also C++) evaluates the samples and reports the diagnostics with 0.3.0's semantics. There is no Python fallback. The extension is required, and `MSF_TOOLS_PURE=1` only skips the fast path.
- Arithmetic: the core mirrors these parts of `math3d` and Python: the checked add, subtract, product and divide; the tie behaviour of Python's `min` and `max` (which decides signed zeros); `bisect_right` knot lookup; and sequential summation from 0.0. It is compiled with `-ffp-contract=off`, never with `-ffast-math`. A test with affine scale 1+2^-30, input 1-2^-30 and offset -1 must give exactly 0.0. An FMA would not give that.
- Accepted handles: admission accepts only the handle types fixed when `msf_tools._native` is imported. An object that only offers `__msf_state__` is refused like any other unsupported state.

## Consequences

- At go/no-go 1, `evaluate_mapping` over 100,000 frames ran 36-38x faster (three rules) and 44-46x faster (52 outputs) than the 0.3.0 wheel (`scripts/bench.py`, median of 5, Apple arm64, Python 3.12). `compile_mapping` cost 15 to 27 % more, for the document round trip, depending on load: 1.3 to about 1.6 ms (three rules) and 18 to about 22 ms (52 outputs). Since phase C, the core compiles the map itself with no document round trip, and `compile_mapping` is 2.3 to 2.8x faster than 0.3.0.
- Evaluation semantics exist twice, in the fast path and the exact path, both in C++. `tests/internal/test_core_mapping.py` requires both to match the 0.3.0 oracle (run out of process) exactly: samples of the same types, the same float bits and the same diagnostics. `scripts/ci_local.sh` also runs the public suite without the fast paths (`MSF_TOOLS_PURE=1`).
- Wheels are per Python version and platform. Building from source needs a C++17 compiler and CMake. At go/no-go 1 the minimum was CMake 3.24. Since the stable-ABI (`abi3`) build in 0.4.0, it is 3.26.
- Fingerprints of handle-backed records hash binary buffers. Fingerprints have always been local to the process and are never stored.
- Since phase D, `evaluate_geometry` over 30 frames of a skinned and morphed GLB with 2,500 vertices runs about 59x faster than 0.3.0, and `inspect_asset` about 14x faster (`scripts/bench.py`). `tests/internal/test_core_snapshot.py` requires inspection, decoding, sampling, geometry and bindings to match the 0.3.0 oracle on random and damaged assets.
- Later slices that move more state into the core follow the same rule: views are built only from the handle's export, and are checked against it at admission.
