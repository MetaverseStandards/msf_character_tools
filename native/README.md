# Strict native numerical pilot

Original MIT C++17 kernels use binary64 and STL values. The pilot provides matrix
arithmetic, affine point transforms, TRS composition/reparent validation,
shortest-path quaternion SLERP, duration-scaled Hermite, relative POSITION morphs,
four-influence mesh-local LBS and resolved scalar instructions. Asset parsing,
reports, evidence validation and authoring compilation remain in Python.

## Python surface and storage

The optional `_msf_native` module exports `identity`, `multiply`, `inverse`,
`transform_point`, `compose_trs`, `reparent_local`, `slerp`, `hermite`,
`morph_positions`, `skin_positions`, `evaluate_scalars`, `Domain`, `Instruction`
and `ScalarProgram`, plus the `Operator` enum. Hermite alone has named arguments
and `quaternion=False`; the other numerical functions take positional arguments.

Matrices are flat lists of 16 row-stored values acting on column vectors:
translation indices 3/7/11, bottom row 12..15. `multiply(a,b)` computes a*b,
applying b first. `from_gltf_column_major(values)` and
`to_gltf_column_major(values)` return detached lists with the explicit storage
conversion `row[r*4+c] = column[c*4+r]`. Neither changes transform order.
`reparent_local(new_parent_world,child_world)` is parent-first, unlike the public
Python geometry helper's child-first glTF column-storage interface.

Numeric inputs must be exact built-in int/float, excluding bool and coercible
objects/subclasses. Arrays accept list/tuple instances only. Matrices have16,
points3, quaternions4, and skin joint/weight rows4 components. All supplied
components must be finite representable binary64, including invalid scalar
placeholders, unused coefficients, zero-weight deltas and inactive palette rows.
Indices are exact nonnegative int representable as size_t; validity and quaternion
mode are exact bool. Skin requires a nonempty joint palette and equal world/IBM
counts. This count policy is narrower than the asset reference's extra IBM policy.

`Domain.minimum/maximum` accept None or strict numeric values. Reversed bounds
refuse on evaluation. `Instruction` numeric/index/enum setters and program vector
setters validate before replacing state. Program setters copy their Domain and
Instruction arguments. Program getters return detached nested value copies;
mutating these copies does not edit the program. Numeric getter/return lists are
also detached. Domain/Instruction objects remain individually mutable.

Scalar programs contain every input/intermediate/output slot. Evaluation returns
the full numeric vector, without a validity vector, timestamp or report. Finite
false output placeholders may be overwritten; a required false input refuses.
Program shape/bindings/operator/topology and all supplied values/coefficients are
validated before execution. Unused finite slots need not lie in their domains.

Failures raise `ValueError` with `code: message`. Admission uses `type`, `shape`,
`binding`, `operator` and `nonfinite`; semantic kernels also use `domain`, `cycle`,
`invalid_sample`, `influence`, `weights`, `nonaffine`, `singular`, `shear`,
`quaternion`, `fraction` and `curve`. Noninteger/negative/oversized indices refuse
with `binding`; a representable index outside the skin palette uses `influence`.
Missing arguments or unknown keywords retain Python call `TypeError`.

## Numerical policy

Every executed product/division and ordered accumulation must remain finite.
Nonzero products/quotients rounded to zero refuse `nonfinite`; representable
subnormals, exact zeros and cancellation are allowed. The ordinary binary64
operation sequence can refuse a mathematically representable final result whose
intermediate arithmetic is unsafe. There is no magnitude cap, higher precision
cancellation rescue or condition-number cutoff. Finite1.5e308 identity and signed,
above-one or huge morph weights remain valid when their operations are safe.

Generic multiply/inverse accept finite4x4 matrices. Point, reparent and skin
validate the complete affine bottom row of original matrices. Reparent computes
inverse(parent)*child and validates local TRS using finite nonzero scaled hypot
norms, normalized orthogonality and determinant magnitude. Reflection is valid.
Explicit composition permits zero scale; inverse/decomposition requires nonzero
axes/pivots. Affine/TRS tolerance stays1e-10, skin weight sum1e-6. Weights are never
silently normalized. Sheared affine POSITION palettes and singular weighted
POSITION blends do not require TRS decomposition.

SLERP normalizes both quaternions before selecting endpoints. At zero it returns
the first; at one an ordered rounded dot sign selects the second's hemisphere,
with zero ties retaining its sign. Interior arithmetic remains checked. Hermite
validates all tangents and controls; a zero raw tangent contributes zero before
coefficient*duration arithmetic. Quaternion tangents remain raw. Morph zero
weights and skin inactive influences skip arithmetic only after input validation.
Skin composes only active palettes and retains influence accumulation order.

C++ `multiply` now returns `Result<Mat4>`; callers must check success before reading
its value. Rebuild all compiled callers against the current header. This is an
intentional pilot source/signature migration, with no stable ABI assumption.

## Build and gates

```sh
cmake -S . -B build -DMSF_BUILD_NATIVE_PILOT=ON
cmake --build build
ctest --test-dir build --no-tests=error --output-on-failure
```

Bindings require Python Interpreter/Development.Module and pybind11>=3.1; enable
`MSF_BUILD_PYTHON_BINDINGS=ON`, provide the actual `Python_EXECUTABLE` and
`pybind11_DIR`. The binding build registers the C++ analytical test, public Python
agreement test and independent strict binding test. `native/tests/test_strict.py`
takes the actual module directory followed by the source root and refuses an
incorrect import origin. Its literal numerical, diagnostic and lifetime oracles
are independent; agreement is supplemental.

Local qualification is limited to the recorded macOS arm64 CPython3.11.17 and
3.12.15+meta builds. Configured CI native jobs leave bindings OFF. No release
wheel, Windows bindings, asset backend, ABI3, free-threaded/GIL/threading or
zero-copy support follows. Packaging/verifier/consumer acceptance remains a
separate gate. No production rig accuracy or device timing guarantee is supplied.
