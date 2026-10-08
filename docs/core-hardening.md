<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
# Core semantic hardening in package 0.1.1

The reference checks a selected glTF 2.0 core subset against specification commit
`8e691206fa2e981fc3b8c8bc57e671595576c971`. It inventories unknown attributes and
extensions and unresolved resources. Successful inspection is not full glTF
conformance or production rig qualification. Geometry remains POSITION, relative
morphs and four-influence LBS; later influence sets can be inspected but evaluation
refuses them. Normals/tangents, compressed behavior and extension animation targets
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
retain the project's 1e-6 effective-value policy; authored quaternion keys retain
its 1e-5 squared-length policy. These project tolerances are not physical error
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
joints and exceed the global sum. It still tests explicit four-influence refusal.

## Remaining gates

Scaled-safe affine/norm/dot/determinant math, huge identical axes/shear, reflection,
underflow/overflow intermediate checks, authored zero matrix columns versus
explicit TRS zero scale, singular weighted blends and native boundary parity are
pending. S-H2 is incomplete until those numeric cases pass independent review.
S-H3 accounting/resolution/graph work, S-H4 wrappers, S-H6 evidence policy, S-H5L
packaging and X-CONSUMER installed review remain separate gates. This draft does
not qualify installed/native artifacts, new platforms or production rigs.
