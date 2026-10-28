<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
# Core semantic hardening in package 0.1.1

This page records package 0.1.1, when the reference was pure Python. Since 0.4.0 the C++ core implements the inspection and math rules described here. Its results match 0.3.0, apart from the differences the CHANGELOG lists.

The reference checks a selected subset of the glTF 2.0 core against specification commit
`8e691206fa2e981fc3b8c8bc57e671595576c971`. It lists unknown attributes, unknown
extensions and unresolved resources as inventory. A successful inspection does not
mean full glTF conformance, or that a rig is qualified for production. Geometry is
still POSITION, relative morphs and LBS over every influence set. (It was
four-influence LBS until N-influence skinning was approved in W6.) Normals, tangents,
compressed behaviour and extension animation targets are not evaluated. Required
extensions that are not supported make evaluation refuse.

## Compatibility

The scalar wire format, schemas, operators and bindings stay at 1.0. The package
version stays 0.1.1, and there are no new wire keys. When you update consumers, pin
this package and the exact source and data hashes. Existing valid scalar exports and
analytical geometry goldens keep their bytes and identities.

Inspection now refuses these problems:
- malformed core attributes that are available;
- bad topology cardinality;
- reserved indices;
- indexed semantics that are unpaired, have gaps or are malformed;
- duplicate positive joint weights, and bad weight sums;
- POSITION bounds that are missing or not accurate;
- malformed morph targets;
- disconnected skins;
- invalid skeleton or scene relationships;
- bad extra inverse bind matrices;
- bad animation layouts, and bad cubic cardinality.

Before, these inputs could get through inspection, or fail only at evaluation.
Unavailable bytes get structural checks and an explicit warning that the resource
was not consumed. Their numeric contents are unknown.

When base or sparse bytes are supplied, bounds must match the actual extremes after
sparse overrides. Per specification line 1509, an accessor with neither bufferView
nor sparse is a format descriptor. Its bounds may be any representable values. The
bound shape, the component range and the min/max order are still validated.
Floating-point JSON bounds are rounded to binary32 and compared exactly. Integer
bounds describe raw integers, normalized accessors included. Exact source parsing
refuses fractional integer bounds, even when binary64 would round them to an integer.
Integral decimal and exponent syntax stays valid. There is no tolerance on how the
bounds enclose the values.

For homogeneous normalized unsigned components, integer weight sums must be exactly
255 or 65535. Floating-point and mixed weight sums keep the project's 1e-6 policy on
effective values. Authored quaternions must be within 0.00769 of unit length, the
Khronos glTF-Validator's limit. These project tolerances are not physical error
budgets. Authored weights are never renormalized silently.

Primitives with and without morph targets can be mixed in any order. Each primitive
without morph targets gets a zero delta. Extra inverse bind rows are validated, but
only the first rows, as many as there are joints, in order, form the palette. Matrix
nodes allow weights animation and refuse TRS animation. Each primitive used by a
skinned node needs paired JOINTS_0/WEIGHTS_0, even when its bytes are unavailable.
Every animation target needs a string path before extension handling. Core channels
with no node are ignored. Unknown targets stay in the inventory. Known data that is
available is checked independently of unknown or unavailable channels. Rotation and
morph keys support normalized signed and unsigned byte and short encodings. Core
integer properties accept integral decimal and exponent syntax in a normalized
execution view. The original asset bytes, the hash and opaque JSON fields are kept.
The integer rules for authoring, samples and overrides stay strict.

The generated native agreement fixture was invalid, because its base and morph
POSITION accessors had no bounds. Both now have exact literal bounds. The binary
geometry and the analytical expectations did not change. The eight-influence fixture
now uses zero weights for its later set. Copying positive weights would duplicate
joints and go over the global sum. Since N-influence skinning, it evaluates exactly
like `combined.gltf`. `eight-weighted.gltf` covers eight nonzero influences.

## Pure Python numeric hardening

All math helpers need built-in finite int or float components, with exact shapes.
Booleans and objects that can be coerced are refused. Internally, matrices hold row
tuples. `matrix` reads glTF column-major values, and `column_major` returns a
detached column-major list. Generic multiply and inverse keep generic 4x4
semantics. Position transforms validate the whole affine bottom row before they use
the point. Reparent validates both original affine inputs and computes
`inverse(new_parent_world) * child_world` before it validates the local TRS.

Authored and overridden node matrices need nonzero columns, normalized axis
orthogonality, and a normalized determinant magnitude near one. Reflections are
accepted, with signed scale. Axis lengths use scaled `hypot`. Zero and infinite
lengths are refused. The normalized determinant avoids raw determinant products
that are huge or tiny. An explicit TRS zero scale is accepted until an inverse is
needed. World products and skin palettes can contain shear. A singular weighted
POSITION blend is accepted when no inverse or decomposition is needed.

The existing Python tolerances for each role stay the same:
- point affine: 1e-7;
- node affine: 1e-12;
- reparent affine and axis orthogonality: 1e-9;
- IBM bottom row: exact;
- floating-point skin sum: 1e-6;
- authored quaternion length: within 0.00769 of one (glTF-Validator).

Authored matrix orthogonality and the normalized determinant magnitude use 1e-9,
because they have the same decomposition role as reparent. These are project
acceptance choices. They do not give a physical or universal conditioning budget.
The main glTF matrix conditions are at lines 831–846 of the pinned specification
(commit above). They include the absolute normalized determinant, and the
difference between authored zero columns and explicit zero scale.

Selected value arithmetic is checked in helpers, interpolation, hierarchy, morph,
skin and scalar execution. Every binary64 product and division, and every
intermediate of an ordered accumulation, is checked. These are refused with
`E_NONFINITE`: overflow, nonfinite results, and nonzero products or quotients that
round to zero. Representable subnormal results, exact zero and cancellation stay
valid. The partial-pivot inverse refuses exact zero pivots. There is no new
condition-number cutoff, and no higher-precision rescue from cancellation. This
policy can refuse an exact mathematical result when its selected sequence of
intermediates cannot be represented. It does not certify accuracy for
ill-conditioned inputs. Signed huge morph weights and an unbounded 1.5e308 scalar
identity stay valid when the actual operations can be represented.

Quaternion helpers still normalize finite inputs that are not unit length. Authored
node, override and animation quaternions keep the existing unit check. There is no
new strict unit mode or wire policy. Component LINEAR and duration-scaled Hermite
keep ordered binary64 arithmetic. Raw cubic quaternion tangents are kept as they
are. Fractions must be in [0,1], Hermite duration must be positive, and quaternion
mode must be an exact bool.

Branch selection comes after complete input validation:
- STEP selects its preceding key before any duration or fraction arithmetic.
- LINEAR selects exact validated endpoints before subtraction.
- SLERP normalizes both inputs first. At zero it returns the first input. At one it
  returns the second input, in the hemisphere that the sign of an ordered binary64
  dot product selects. When the dot rounds to zero, the second input keeps its sign.
  Some products that are known to round to zero are left out, by their binary64
  exponents. The other endpoint dot products use binary64 rounding only to select a
  sign.
- Interior interpolation keeps checked overflow and underflow, and the order of
  operations.
- Zero raw Hermite tangents contribute a literal zero before any coefficient*duration
  work.

Skin palettes are composed only for positive influences, and zero weights skip
point arithmetic. Every original matrix, all IBM rows (extras included) and all four
indices and weights are still validated. The order of active influences and the
mesh-local four-influence POSITION semantics do not change.

Plain math helpers raise `Fault` with explicit codes for type, shape, numeric,
transform and curve errors. Public decorated APIs turn these into `Result`
diagnostics. Output containers own detached values.

Package 0.1.1, the scalar wire, schema and operator 1.0, and ordinary valid scalar
and geometry golden bytes do not change. When consumers adopt the stricter refusals
of malformed or unsafe input, they should pin exact source and artifact hashes.

## Strict native numeric pilot

Removed in 0.3.0. Since 0.4.0, the C++ core, `msf_character_tools._core`, has taken its place. This section records the pilot as it was in 0.1.1. Its sources and contract are in Git history, last at commit 746a5fe.

The native pilot now validates the original Python numeric, bool, index and list
inputs before conversion, mutable program setters included. Program getters return
detached nested copies of Domain and Instruction. Every supplied scalar value must
be finite, even for a false output placeholder. Checked binary64 arithmetic follows
the representability policy and the branch choices of the pure reference. Full
original affine rows, finite normalized axes and determinants, and active skin
arithmetic are validated without widening the affine/TRS tolerance (1e-10) or the
weight tolerance (1e-6).

Named native and glTF storage adapters make the row/column conversion explicit.
Multiply computes a*b (b first). C++ multiply returns Result<Mat4> on purpose, so
callers must rebuild and check for success. The native contract (`native/README.md`
at 746a5fe) gave the exact surface, error codes, ownership and numeric policy.
Independent literal binding oracles and supplemental agreement tests ran on real
local builds with bindings ON, for macOS arm64 CPython 3.11.17 and 3.12.15 (a
vendor-patched build). A new independent review of this candidate was still needed
before root committed it.

## Remaining gates

These stay separate gates: S-H3 accounting, resolution and graph work, the S-H6
evidence policy, S-H5L packaging and the X-CONSUMER installed review. Local native
builds do not qualify any of these: a six-API backend, a release wheel, more
platforms, ABI3, free-threaded Python, zero-copy or GIL behaviour, or production
rigs.
