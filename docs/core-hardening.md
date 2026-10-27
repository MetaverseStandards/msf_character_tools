<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
# Core semantic hardening in package 0.1.1

The reference checks a selected glTF 2.0 core subset against specification commit
`8e691206fa2e981fc3b8c8bc57e671595576c971`. It inventories unknown attributes and
extensions and unresolved resources. Successful inspection is not full glTF
conformance or production rig qualification. Geometry remains POSITION, relative
morphs and LBS over every influence set (four-influence LBS until N-influence
skinning was approved in W6). Normals/tangents, compressed behavior and extension animation targets
are not evaluated. Required unsupported extensions refuse evaluation.

## Compatibility

Scalar wire, schemas, operators and bindings stay 1.0. Package version stays 0.1.1;
there are no new wire keys. Pin this package and exact source/data hashes when
updating consumers. Existing valid scalar exports and analytical geometry goldens
retain their bytes and identities.

Inspection now rejects malformed available core attributes, topology cardinality,
reserved indices, unpaired/gapped/malformed indexed semantics, duplicate positive
joint weights, bad weight sums, missing or inaccurate POSITION bounds, malformed
morph targets, disconnected skins, invalid skeleton/scene relationships, bad extra
inverse bind matrices and bad animation layouts/cubic cardinality. These requests
could previously survive inspection or fail only when evaluated. Unavailable bytes
receive structural checks and an explicit unconsumed-resource warning; their
numeric contents are unknown.

Bounds match actual extrema after sparse overrides when base or sparse bytes are
supplied. Per specification1509, an accessor with neither bufferView nor sparse is
a format descriptor: its bounds may be arbitrary representable values, while
bound shape, component range and min/max order remain validated. Floating JSON
bounds are rounded to binary32 and compared exactly; integer bounds describe raw
integers, including normalized accessors. Exact source parsing rejects fractional
integer bounds even when binary64 would round them to an integer; integral
decimal/exponent syntax remains valid. There is no enclosure tolerance. Integer weight sums are exactly 255 or
65535 for homogeneous normalized unsigned components. Floating/mixed weight sums
retain the project's 1e-6 effective-value policy; authored quaternions must be
within 0.00769 of unit length, the Khronos glTF-Validator's limit. These project tolerances are not physical error
budgets. Authored weights are never silently renormalized.

Mixed morphless/targeted primitives work in any order, with zero delta for each
morphless primitive. Extra inverse bind rows are validated but only the first
ordered joint-count rows form the palette. Matrix nodes permit weights animation
and refuse TRS animation. Each primitive used by a skinned node requires paired
JOINTS_0/WEIGHTS_0 even when its bytes are unavailable. Every animation target
requires a string path before extension handling. No-node core channels are ignored; unknown targets
remain inventory. Available known data is checked independently of unknown or
unavailable channels. Rotation/morph keys support normalized signed/unsigned byte
and short encodings. Core integer properties accept integral decimal/exponent
syntax in a normalized execution view, while original asset bytes/hash and opaque
JSON fields are preserved. Authoring/sample/override integer policies stay strict.

The native generated agreement fixture was invalid because its base and morph
POSITION accessors lacked bounds. Both now have literal exact bounds without
changing binary geometry or analytical expectations. The eight-influence fixture
now uses zero weights for its later set; copying positive weights would duplicate
joints and exceed the global sum. Since N-influence skinning it evaluates exactly like
`combined.gltf`; `eight-weighted.gltf` covers eight nonzero influences.

## Pure Python numerical hardening

All math helpers require built-in finite int/float components with exact shapes;
booleans and coercible objects refuse. Matrices contain row tuples internally;
`matrix` reads glTF column-major values and `column_major` returns a detached
column-major list. Generic multiply/inverse retain generic 4x4 semantics.
Position transforms validate the whole affine bottom row before using the point.
Reparent validates both original affine inputs and computes
`inverse(new_parent_world) * child_world` before validating local TRS.

Authored and overridden node matrices require nonzero columns, normalized axis
orthogonality and normalized determinant magnitude near one. Reflections are
accepted with signed scale. Axis lengths use scaled `hypot`; zero and infinite
lengths refuse. The normalized determinant avoids raw huge/tiny determinant
products. Explicit TRS zero scale is accepted until an inverse is required.
World products and skin palettes can contain shear; a singular weighted POSITION
blend is accepted when no inverse/decomposition is needed.

Existing Python role tolerances remain: point affine1e-7, node affine1e-12,
reparent affine/axis orthogonality1e-9, exact IBM bottom row, floating skin sum1e-6,
authored quaternion length within 0.00769 of one (glTF-Validator). Authored matrix orthogonality and
normalized determinant magnitude use1e-9, the same decomposition role as
reparent. These are project acceptance choices; no physical or universal
conditioning budget follows. The primary glTF matrix conditions are at pinned
specification831–846 (commit above), including the absolute normalized determinant
and distinction between authored zero columns and explicit zero scale.

Selected value arithmetic in helpers, interpolation, hierarchy, morph, skin
and scalar execution checks every binary64 product/division and ordered
accumulation intermediate. Overflow/nonfinite results and nonzero products/quotients rounded to zero
refuse `E_NONFINITE`. Representable subnormal results, exact zero and cancellation
remain valid. Partial-pivot inverse rejects exact zero pivots; there is no new
condition-number cutoff or cancellation rescue using higher precision. This
policy can refuse an exact mathematical result whose selected intermediate
sequence is unrepresentable. It does not certify accuracy for ill-conditioned
inputs. Signed huge morph weights and unbounded1.5e308 scalar identity remain
valid when actual operations are representable.

Quaternion helpers continue to normalize nonunit finite inputs; authored
node/override/animation quaternions retain the existing unit check. No new strict
unit mode or wire policy is added. Component LINEAR and duration-scaled Hermite
retain ordered binary64 arithmetic; raw cubic quaternion tangents are preserved.
Fractions must be in[0,1], Hermite duration positive, quaternion mode exact bool.

Branch selection follows complete input validation. STEP selects its preceding
key before duration/fraction arithmetic. LINEAR selects exact validated endpoints
before subtraction. SLERP normalizes both inputs first; at zero it returns the
first input, and at one it returns the second input in the hemisphere selected by
an ordered binary64 dot sign. A rounded-zero dot tie retains the second input's
sign. Certain rounded-zero products are omitted using their binary64 exponents;
remaining endpoint dot products use binary64 rounding solely to select a sign.
Interior interpolation retains checked overflow/underflow and operation order.
Zero Hermite raw tangents contribute literal zero before coefficient*duration
work. Skin palettes are composed only for positive influences and zero weights
skip point arithmetic; every original matrix, all IBM rows including extras, and
all four indices/weights remain validated. Active influence order and mesh-local
four-influence POSITION semantics remain unchanged.
Plain math helpers raise `Fault` with explicit type/shape/numeric/transform/curve
codes; public decorated APIs translate these to `Result` diagnostics. Output
containers own detached values.

Package0.1.1, scalar wire/schema/operator1.0 and ordinary valid scalar/geometry
golden bytes remain unchanged. Consumers should pin exact source/artifact hashes
when adopting the stricter malformed/unsafe-input refusals.

## Strict native numerical pilot

Removed in 0.3.0; the C++ core will replace it. This section records the pilot as it stood in 0.1.1. Its sources and contract are in Git history, last at commit 746a5fe.

The native pilot now validates original Python numeric/bool/index/list inputs
before conversion, including mutable program setters. Program getters return
detached nested Domain/Instruction copies. Every supplied scalar value remains
finite even for a false output placeholder. Checked binary64 arithmetic follows
the pure reference's representability policy and branch choices. Full original
affine rows, finite normalized axes/determinants and active skin arithmetic are
validated without widening affine/TRS1e-10 or weight1e-6 tolerances.

Named native/glTF storage adapters make the row/column conversion explicit;
multiply computes a*b (b first). C++ multiply intentionally returns Result<Mat4>,
requiring callers to rebuild and check success. The native contract (`native/README.md` at 746a5fe)
gave the exact surface, error codes, ownership and numerical policy. Independent
literal binding oracles and supplemental agreement run on actual local bindings
ON builds for macOS arm64 CPython 3.11.17 and 3.12.15 (a vendor-patched build). Fresh independent review
of this candidate remains required before root commits it.

## Remaining gates

S-H3 accounting/resolution/graph work, S-H6 evidence policy, S-H5L packaging and
X-CONSUMER installed review remain separate gates. Local native builds do not
qualify a six-API backend, release wheel, additional platforms, ABI3,
free-threaded Python, zero-copy/GIL behavior or production rigs.
