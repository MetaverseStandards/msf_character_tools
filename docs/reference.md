# Version one reference

Original documentation: CC-BY-SA-4.0. This reference describes project contracts; the pinned [glTF specification](sources.md) defines the external format.

## Results and reports

All six public functions and helpers decorated with `@public` return dataclass `Result[T]` with `.value: T | None`, `.report: Report` and `.ok: bool`. Report has `schema_version="1.0"`, diagnostics and losses. Each diagnostic has `code`, `severity`, singular `ref`, `message`, `remediation`; losses have `category`, `effect`, `reason`, `refs` and optional `units`, `bound`. A report containing any error has no value. Exceptions at decorated Result APIs become diagnostics; plain serialization/helpers (`canonical_json`, record `.to_dict()`/`.to_bytes()`, `survey_csv`, `coverage`) raise exceptions, including `Fault` for inconsistent records; callers must check `.ok` before using values. Records are validated independently so a failing operation reports multiple defects where collection remains meaningful; dependent decoding stops when structure is unsafe.

## Record ownership in package 0.1.1

Create records with `validate_authoring`/`load_authoring`, `compile_pack`, `inspect_asset`, `profile_snapshot`, `compile_mapping`, `annotate_asset`, `evaluate_mapping` and `evaluate_geometry`. Public dataclass constructors retain their signatures for compatibility, but direct construction, copying and `dataclasses.replace` do not produce admitted records. Recreate a record with its public factory. This stricter constructor policy affects programmatic record replacement; existing wire inputs and factory call shapes stay the same.

Factories recursively copy containers, freeze mappings/arrays, copy nested data records and retain immutable byte values. Admitted nested executable records may share owned immutable state. At compilation, binding, sampling, evaluation and record export, checks require factory admission, recompute a typed digest of every stored state field, validate nested records and check source consistency. A token or frozen outer dataclass alone does not provide these invariants. Changed or unadmitted records fail `E_RECORD_INTEGRITY`; Result APIs return no value, and plain exporters raise `Fault`. This is an API consistency contract for callers using the public interface, not isolation from arbitrary Python code or private internals.

Pack identity hashes canonical pack bytes. Asset identity hashes exact original bytes, including whitespace and opaque GLB chunks. Snapshot checks parse the original source and compare it with the owned evaluation view, verify consumed byte/resource digests and declarations, and derive channels from validated bindings. Whitespace-equivalent assets have equivalent views and distinct raw identities. External resource bytes are bound to the bytes returned by the explicit resolver; source text does not authenticate remote contents. Profile selection/channels and compiled instructions/dependencies remain bound to the supplied pack. Compilation checks each full profile once at entry and once during compiled-record admission, using a shared signal index for each boundary; per-channel checks compare declarations without rebuilding profiles. Each later operation checks current stored state afresh. Checks traverse stored state and hash consumed bytes; asset checks also parse the raw document. Nested dependencies can cause several complete asset hashes/parses per operation; this fixed-multiple cost is material for repeated-frame consumers. It is not a wall-time or heap guarantee; general resource budgets beyond the documented limits are future work.

Hardening release 0.1.1 keeps schema, wire and scalar operator 1.0, with no new wire keys or deterministic valid-byte changes. Scalars must fit finite binary64, excluding booleans; huge integers produce precise numeric diagnostics instead of an overflow exception. Authoring collects independent row/version diagnostics after JSON numeric refusal. Descriptions require nonblank strings, and coupling arrays require unique nonblank entries (empty arrays remain valid). Runtime and portable authoring/pack schemas use one explicit blank-character set: U+0009–000D, U+001C–0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF. A string must contain at least one character outside that set; text is preserved without trimming or normalization. This retains the prior control-whitespace rejects and additionally rejects blank-only U+FEFF. Other nonempty Unicode text remains valid. Schema patterns use explicit codepoints rather than engine-dependent whitespace classes; opaque metadata strings are not description fields. Finite binary64 range and structural references remain runtime additions to JSON Schema.

## Authoring and packs

```python
validate_authoring(document) -> Result[ValidatedAuthoring]
compile_pack(validated_authoring) -> Result[Pack]
```

Authoring is a JSON-compatible mapping, usually loaded from TOML. Required top keys are `schema_version="1.0"`, `data_version` (independent semantic version), `operator_version="1.0"`, `id`, `license`, `signals`, `profiles`, `mappings`, `evidence`. Pack wire bytes contain the same validated document. `.document` is deeply immutable; `.to_dict()` returns a detached ordinary JSON value. `.to_bytes()` gives deterministic UTF-8; `.sha256` hashes those exact bytes. Raw dicts cannot be passed to `compile_pack`.

Required signal keys: `id`, `label`, `value_type="scalar"`, `units`, `domain={min?,max?}`, explicit `calibration`, `disposition`, `evidence` IDs, `evidence_status`. Optional keys: `region`, `side`, `neutral`, `native_default`, `coupling`, `native_id`, `surface`, `validity`, `confidence`, `time`, `metadata`. Neutral and storage default are independently optional values within domain. Units/calibration are explicit nonempty strings; identity mappings require the same calibration basis. Scalars exclude bool and all nonfinite values. Unbounded domains are `{}`. Survey text is never executable.

Disposition: `mapped|unsupported|unresolved|excluded`. Evidence status: `verified_current|proposed|unresolved`. Coupling is a description or array of descriptions; confidence is a description or scalar in [0,1]; validity is bool or a description; time is a description. Format-specific inventoried structures belong inside explicit `metadata` objects. Unknown keys elsewhere fail.

Profiles require `id,label,signal_ids` with optional evidence and metadata. Evidence requires `id,claim,status`; public evidence has `url` (HTTPS), at least one of `revision,retrieved,sha256`, and `locator`. Original fixture evidence uses `license,authorship`. Optional evidence keys are exactly `url,revision,retrieved,sha256,locator,license,authorship`.

Mappings require `id,rules`. A rule has `id,inputs,outputs,operator,disposition,assumptions,evidence,evidence_status,loss_annotations`, optional `coupling`, and `mapping_quality=exact|approximate` when mapped. Rule IDs are globally unique; inventory IDs are unique within each category. References and duplicate array entries are checked. Operators:

| Operator | Coefficients | Arity | Numeric operation |
| --- | --- | --- | --- |
| identity | none | one scalar in/out | y=x |
| affine | explicit finite scale, offset | one scalar in/out | y=scale*x+offset |
| weighted_sum | explicit ordered finite weights | N scalar inputs, one output | y=sum(weights[i]*inputs[i]) in declared order |

Unary/weighted output domain is checked during evaluation. Identity requires equal declared domains. Compatible units are required; explicit affine unit conversion needs stated assumptions. No clamp, inverse, neutral substitution, bilateral expansion or synthesis is implied. Unresolved inventory compiles into a pack, but requesting an unresolved rule fails mapping compilation.

### Fragment loader

`load_authoring(path) -> Result[ValidatedAuthoring]` accepts one TOML file or directory containing `pack.toml`. Directory TOML fragments are recursively sorted by relative path, excluding any `generated` directory and all hidden file/directory components (names beginning with `.`). Exclusion uses relative paths: a deliberately hidden authoring root is still allowed. Hidden virtual environments and CI checkouts are pruned before traversal. Array categories concatenate in that order; metadata keys cannot occur twice even if values match. Symlinks, reserved device filenames and case-insensitive path collisions fail. Fragments are opened without blocking, so a FIFO or other non-regular `.toml` entry fails `E_FRAGMENT_PATH` instead of hanging. TOML datetime values must be quoted when stored as strings; arbitrary non-JSON objects fail.

### Deterministic outputs

`canonical_json(value) -> bytes` recursively normalizes -0.0 to 0.0, then uses exactly `json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)+"\n"`, UTF-8. Array order is preserved. This is the project byte convention, not RFC8785 certification. No timestamps or absolute machine paths are injected. Caller-authored metadata remains caller data.

`survey_csv(pack) -> bytes` writes UTF-8 LF, `csv.QUOTE_MINIMAL`, header `id,label,value_type,units,disposition,evidence_status` then profile IDs in declared order; membership is `1` or empty. Existing independently owned CRLF survey formats must use their original checker; this new CSV does not rewrite them.

`coverage(pack) -> dict` includes signal disposition/reason/profile/rule uses; complete evidence including unused/unresolved entries; rule quality partitions; aggregate totals; per-profile partitions/counts and original metadata. SHA256SUMS hashes pack, CSV and coverage exact bytes, in that order, using `digest + "  " + basename + LF`. Four output basenames must be distinct.

## Snapshots and sidecars

```python
inspect_asset(bytes, /, format, resolver=None, sidecar=None, *,
              isolate=False, limits=None, options=None) -> Result[AssetSnapshot]
annotate_asset(snapshot, annotations) -> Result[Sidecar]
```

Supported format strings: `gltf`, `glb` (also `json`/`gltf2` JSON aliases). Input is immutable bytes, passed positionally: `bytes` is positional-only, so `inspect_asset(bytes=...)` is refused with `E_INPUT`. Snapshot retains `.original_bytes`, `.sha256`, deeply immutable `.document`, `.chunks` with original payload bytes, `.resources` with URI/declared byte length/digest/consumed data, `.channels` and `.bindings`. `.to_dict()` publishes complete document/inventory/capabilities without embedding duplicate binary payloads. Hashes are source byte identities; names are display only.

No default remote or local external fetch. Embedded base64 and BIN are explicitly consumed. Unconsumed external buffers produce warning/inventory; decoding them fails `E_RESOURCE_UNAVAILABLE`. Images are inventoried; external images are consumed only with explicit resolver. Unknown required extensions and extension-defined animation targets may be inspected, but requested evaluation applies the stricter capability gate.

`LocalResolver(root,max_resource_bytes=64MiB,max_total_bytes=256MiB)` is a callable. Root must be canonical, without symlink ancestors (`Path(root).resolve()` is explicit). URI paths are relative, percent-decoded, no traversal, query, fragment or remote scheme. Each directory/file is opened with no-follow, nonblocking descriptors to reject symlink traversal and substitution. Regular files only: FIFOs, devices and sockets fail `E_RESOURCE_TYPE` without waiting on the open. Budgets accumulate over resolver lifetime; create a new resolver for a new budget. Custom callables are explicit caller capability and must return bytes.

Inspection limits: 64MiB input, 64MiB/resource, 256MiB total consumed resources, 1,000,000 decoded components/accessor, 4,000,000 total declared accessor components, 100,000 objects/category, 128 JSON nesting levels. These checks precede zero-backed/sparse allocation; custom resolvers must bound their own allocation before returning. JSON parser recursion failures are diagnostics. Large production assets need a separately reviewed limit revision; limits are not a streaming guarantee.

Accessors support all core component types, matrix column padding, offsets, interleaving, normalized byte/short values and strictly increasing sparse overrides. Bounds and finite decoded floats are checked. Zero-backed accessors are supported within the same budgets. Binary geometry/animation roles receive further type/shape checks when evaluated.

### Sidecar wire

```json
{
  "schema_version": "1.0",
  "asset_sha256": "<source SHA256>",
  "resource_hashes": {"/buffers/0": "<consumed resource SHA256>"},
  "bindings": [{
    "id": "output.wink", "value_type": "scalar", "units": "1",
    "domain": {"min": -1.0, "max": 2.0},
    "calibration": "explicit fixture basis",
    "ref": {
      "asset_sha256": "<source SHA256>",
      "locator": "/nodes/5/weights/0", "node": 5, "mesh": 0, "target": 0,
      "resource_sha256": "<optional consumed target digest>"
    }
  }],
  "metadata": {"original_annotations": "opaque inventoried data"}
}
```

`annotate_asset` accepts `{bindings:[...],metadata?:{...}}`; output is a canonical, idempotent sidecar. Every reuse verifies source hash, the complete consumed resource hash inventory, structural indices and locator agreement. Sparse index, sparse value and base buffer digests are all bound by the sidecar. Optional `ref.resource_sha256` must identify a consumed target resource. Binding IDs/destinations are unique. Initial version supports scalar morph weights per mesh instance; other channel binding shapes need an explicit revision.

`morph_binding(snapshot, signal, node, target) -> Result[immutable binding]` creates a structural binding from a pack signal, including its single target resource digest when applicable. Multiple buffers remain fully bound in `resource_hashes`. `decode_accessor(snapshot,index)` returns `Result[tuple[tuple[number,...],...]]`.

### Source formats

`format` may also be `usd`, `usda`, `usdc`, `usdz` or `fbx`. The leading bytes must match: `#usda`, `PXR-USDC`, a ZIP header for `usdz`, and for `fbx` the binary magic or text that starts with a letter or `;`. `usd` accepts USDA or USDC and records which one it found. A mismatch is `E_FORMAT_MISMATCH`, and an unknown format is `E_ASSET_TYPE`. Reading needs the format's adapter and its reader library; without them the result is `E_FORMAT_DEPENDENCY`. The message says whether this build lacks the adapter altogether or only the optional reader, which `msf-tools[usd]` or `msf-tools[fbx]` installs. The adapters themselves are added separately; this section describes the shared contract.

An adapter converts the source into an in-memory GLB with one glTF vertex per source point. The unchanged glTF inspector then admits it, and `original_bytes`, `sha256` and `format="glb"` describe that GLB. `source` records:
- `format`, `sha256` and `byte_length` of the source; the source bytes are not kept;
- `adapter`, `adapter_version` and `reader`;
- `options_sha256`, the digest of the canonical options with defaults filled in;
- `node_order="path-sorted-v2"`;
- `node_paths`, one per glTF node, and `target_keys`, one list per glTF mesh in target order;
- `dependencies` (`uri`, `sha256`, `byte_length`, sorted by URI) and `losses` (warning or info diagnostics, which are also in the report).

The GLB bytes are deterministic for a fixed source, dependency set, adapter version, reader version and options, but not across reader versions, so no hash of them is persisted. Every recorded hash is the source sha256 instead:
- snapshot `asset_sha256` (`to_dict` adds `generated_sha256` and `source`);
- sidecar and binding `asset_sha256`;
- geometry golden `asset_sha256`;
- compiled-mapping `source_sha256` and `target_sha256`.

Goldens and compiled mappings add a summary of how the snapshot was produced (`source`, or `source_adapter` / `target_adapter`). Sidecar `resource_hashes` lists the source dependencies. In a generated snapshot's `to_dict`, `generated_sha256`, `document`, `resources` and `chunks` describe the generated GLB and can change when the reader version changes. Only `asset_sha256` and `source` identify the source.

Node paths escape `%`, `/`, `#`, `[`, `]`, `:` and control characters in each component. `[k]` tells apart duplicate siblings, and `#helper:geometry` or `#helper:scale` marks reader-made helper nodes. glTF node `i` is the `i`-th path in order of unescaped components. A generated-snapshot binding must carry `ref.source_locator = <node path>#<target key>`, which is authoritative. The stored `node`, `mesh`, `target` and `locator` are hints:
- if a different reader version moved them, the binding is admitted with the resolved indices and a `W_BINDING_REINDEXED` warning;
- if the locator names nothing in the source, it is `E_STALE_SOURCE`;
- `resource_sha256` is refused.

glTF bindings never use `source_locator`.

`options` is a mapping with these keys only:
- `influences`: `"faithful"` (default) or `"top4"`;
- `losses`: `"declare"` (default) or `"strict"`;
- `animation`: a stack name or a nonnegative index;
- `sample_rate`: FBX only.

Any other key or value is `E_SOURCE_OPTIONS`. Under `"strict"`, every warning loss refuses with its paired error code (`W_X` becomes `E_X`; `W_SHEAR_BAKED` becomes `E_SHEAR_UNSUPPORTED` and `W_INBETWEENS_DROPPED` becomes `E_INBETWEEN_UNSUPPORTED`). Info losses never refuse. Reader rejections are `E_SOURCE_PARSE`, truncated to 512 characters.

`limits` is a `msf_tools.sources.SourceLimits` of positive integers (`E_RESOURCE_LIMIT` when exceeded):

| Field | Default | Notes |
| --- | --- | --- |
| `max_source_bytes` | 512 MiB | At most 4 GiB. |
| `max_dependency_bytes`, `max_dependencies` | 1 GiB, 1,000 | |
| `max_usdz_members` | 10,000 | Checked by the USD adapter. |
| `max_generated_bytes` | 512 MiB | Replaces the 64 MiB glTF input limit for the GLB. |
| `max_accessor_components`, `max_total_accessor_components` | 4,000,000, 16,000,000 | Can be lowered, not raised. Integrity checks and the geometry evaluation budget use these defaults for generated snapshots. |
| `max_reader_memory`, `timeout_s` | 2 GiB, 300 s | Used by isolated conversion. |
| `max_animation_values` | 16,000,000 | Values sampled before conversion; FBX counts samples × (16 × nodes + blend channels) and refuses beyond it before sampling. |

glTF formats refuse `isolate`, `limits` and `options` with `E_SOURCE_OPTIONS`.

`isolate=True` runs the source reader in a new Python process (`python -I`, started from the msf-tools checkout or installation, with only `PATH`, `TMPDIR` and `PXR_WORK_THREAD_LIMIT=1` in its environment, in its own process group). The reader library is never imported by the calling process. The returned GLB is inspected again as untrusted input, so the snapshot is the same as without isolation. The resolver must be `None` or a `LocalResolver`, which the reader process rebuilds from its root and budgets; any other resolver is `E_ISOLATE_RESOLVER`. Failures:
- running longer than `timeout_s` kills the process group: `E_SOURCE_TIMEOUT`;
- physical memory over `max_reader_memory` (sampled every 100 ms) kills it too: `E_SOURCE_MEMORY`;
- a reader process that exits with an error or a signal: `E_SOURCE_CRASHED`, with the end of its stderr;
- a malformed response: `E_SOURCE_PROTOCOL`.

An unexpected exception inside the reader (a bug, not a declared refusal) is reported differently in the two modes: `E_SOURCE_CRASHED` with the end of the traceback when isolated, and `E_INPUT` or `E_INTERNAL` from the operation boundary when in-process. Declared refusals, reader parse errors and limits give the same diagnostics in both modes.

#### USD adapter (`msf-usd`, usd-core 25.11 to 26.x)

Install with `pip install 'msf-tools[usd]'`. Every Xformable or Scope prim (instance proxies included) becomes a glTF node, in path-sorted order. A Mesh prim gets its own glTF mesh: points become vertices and faces are fan-triangulated from their first corner. Blend shapes bound through `skel:blendShapes`/`skel:blendShapeTargets` become morph targets keyed by their token. Reader errors in any layer are `E_SOURCE_PARSE`.

- **Units and up axis** are applied to the data, so geometry comes back in metres with +Y up. With C = `metersPerUnit` times the Z-up to Y-up rotation (identity for Y-up), points and blend offsets become C·p and local transforms C·L·C⁻¹. An unauthored `metersPerUnit` means centimetres, as in USD. Conversions are declared as `I_UNITS_CONVERTED` and `I_AXES_CONVERTED`.
- **Local transforms** come from the earliest authored time and must be affine, finite and nonsingular. A negative determinant is stored as a negative X scale (`I_MIRRORED`). Shear (two axes of the linear part more than 1e-6 from perpendicular in cosine) is baked into the points of a static, unskinned leaf mesh, leaving the node with no transform (`W_SHEAR_BAKED`); anywhere else it is `E_SHEAR_UNSUPPORTED`.
- **Faces:** hole faces are dropped, subdivision surfaces use their control cage (`W_SUBDIV_CAGE`), and `orientation = "leftHanded"` faces are reversed (`I_WINDING_FLIPPED`).
- **Skinning** follows UsdSkel bindings under a SkelRoot. Each bound Skeleton's joints become nodes named `<skeleton path>.joints/<joint token>` (for example `/Rig/Skel.joints/root/arm`), parented by the joint topology under the Skeleton node and posed at the earliest time. A skeleton without `restTransforms` and without an animation covering every joint is refused (`E_SOURCE_VALUE`); rest poses are not derived from `bindTransforms`. Each skeleton gets one glTF skin over all its joints, with inverse bind matrices `inv(C·bind·C⁻¹)`. Skinned points are carried through `geomBindTransform`, and influence indices are mapped through `skel:joints` to skeleton joints; constant influences apply to every point. Declared losses:
  - more than four influences are kept in extra `JOINTS_n`/`WEIGHTS_n` sets (`I_INFLUENCES_N`), or with `options={"influences": "top4"}` cut to the four largest, ties going to the lower joint, and renormalized (`W_INFLUENCES_TRUNCATED`);
  - weights that don't sum to 1 within 1e-6 are normalized (`W_WEIGHTS_NORMALIZED`);
  - vertices with no weight are bound to the first root joint (`W_UNWEIGHTED_VERTICES`);
  - `dualQuaternion` skinning is stored as linear blend skinning (`W_SKINNING_METHOD`).

  A skinned mesh or joint with shear is `E_SHEAR_UNSUPPORTED`.
- **Blend shapes** keep their point indices, so sparse shapes stay sparse in the GLB. A shape that authors only `normalOffsets` becomes an all-zero target. A mesh bound to a skeleton only for its blend shapes gets its weights animated without a skin. In-between shapes are dropped and the main shape kept (`W_INBETWEENS_DROPPED`; `E_INBETWEEN_UNSUPPORTED` under strict losses).
- **Animation:** one glTF animation samples every animated transform, skeleton and blend-weight channel at the union of their authored time codes, kept within the stage's start and end time codes when those are authored and divided by `timeCodesPerSecond`. Negative time codes are shifted so the animation starts at 0 (`W_TIME_SHIFTED`). Samplers are LINEAR, with quaternions kept in one hemisphere. Channels whose value never changes are left out. Shear in any sample is `E_SHEAR_UNSUPPORTED`.
- **Skipped prims:** curves, points, NURBS, implicit surfaces, point instancers, cameras, lights and materials are counted by type in one `W_SKIPPED`, together with hole faces. Xformable ones still become nodes.
- **Point animation:** glTF animates points only through morph targets, so a mesh whose points, topology, blend-shape offsets or skin primvars change over time keeps their earliest value, with one `W_POINTS_ANIMATION_DROPPED` per mesh naming the attributes (`E_POINTS_ANIMATION_DROPPED` under strict losses).

Before a stage is opened, every layer named by a sublayer, reference or payload is gathered:

- Layer paths are relative to the layer that names them and must stay inside the source root. A bare path such as `sub.usda` is looked up next to that layer, which is the first place USD looks; USD search paths are never used. Absolute paths, URLs and other schemes, backslashes and escapes are `E_SOURCE_REFERENCE`, as are value clips.
- Outside a USDZ, the resolver fetches each layer by its anchored path (for example `parts/sub.usda`). A missing resolver or an unreadable layer is `E_SOURCE_REFERENCE`. Fetched layers are recorded in `source.dependencies`, and `max_dependencies`/`max_dependency_bytes` are checked after each fetch.
- Inside a USDZ, layers must be members of the package and are not fetched. The archive must be readable, with stored, unencrypted, uniquely named relative members, at most `max_usdz_members` of them; otherwise it is `E_USDZ_ARCHIVE`.

#### FBX adapter (`msf-ufbx`, ufbx 0.23.1)

Install the `msf-tools-ufbx` package (`pip install ./native/ufbx` from a checkout, or the `[fbx]` extra once it is published). The adapter checks the shim's ABI number when it loads; an installed shim built from another version is `E_FORMAT_DEPENDENCY` with the reinstall command, and the reader identity comes from the compiled ufbx's `ufbx_source_version`. Binary, ASCII and deflated FBX are read from memory only; external files and embedded media are never loaded. Reader errors are `E_SOURCE_PARSE`, and going over `max_reader_memory` (passed to ufbx's allocators) is `E_SOURCE_MEMORY`. Hierarchies deeper than 1024 nodes are refused.

- **Space:** ufbx converts the scene to metres and right-handed +Y up, applies geometric transforms to the points, compensates inherit types and adjusts pivots, offsets and pre/post rotations into the node transforms, so node TRS comes from ufbx's node-to-parent matrices. Conversions are declared as `I_UNITS_CONVERTED`, `I_AXES_CONVERTED` and `I_PIVOTS_BAKED`. Where ufbx has to add a helper node (a geometry helper for an instanced mesh with geometric transforms, or a scale helper for inherited scale), it is kept as `<owner path>#helper:geometry` or `#helper:scale` and declared as `W_HELPER_NODES`.
- **Nodes:** every node apart from the ufbx root becomes a glTF node. Paths are `/` plus escaped ancestor names, with `[k]` on siblings that share a name, numbered in file order. Shear, mirror and singular transforms follow the same rules as USD.
- **Meshes:** one glTF mesh per FBX mesh, shared by its instances, with control points as vertices and faces triangulated by ufbx. Hole faces, faces with fewer than three corners and empty meshes are counted in `W_SKIPPED`. A mesh that displays as a smoothed subdivision surface (Smoothness 2 or 3 with at least one preview level) keeps its control cage (`W_SUBDIV_CAGE`). A mesh with a vertex cache deformer keeps its own points; the cache file is never read, and `W_POINTS_ANIMATION_DROPPED` is declared at the mesh's node (`E_POINTS_ANIMATION_DROPPED` under strict losses).
- **Skin:** one glTF skin per skinned mesh. Each cluster's bone becomes a joint whose inverse bind matrix is ufbx's geometry-to-bone matrix. Weights follow the shared influence rules (`I_INFLUENCES_N`, `W_INFLUENCES_TRUNCATED`, `W_WEIGHTS_NORMALIZED`, `W_UNWEIGHTED_VERTICES`, which binds to the nearest ancestor joint of the mesh, else the skeleton root). Rigid, dual-quaternion and blended skinning are stored as linear blend skinning (`W_SKINNING_METHOD`). A mesh with more than one skin deformer is refused.
- **Blend shapes:** each blend channel becomes a morph target keyed `<deformer name>/<channel name>`, with `[k]` on repeated names. The keyframe at full weight is kept and other keyframes are dropped (`W_INBETWEENS_DROPPED`; `E_INBETWEEN_UNSUPPORTED` under strict losses). A channel with no full-weight keyframe uses its largest keyframe scaled to full weight (`W_INBETWEEN_PARTIAL`). Static channel weights (`DeformPercent / 100`) become the default weights.
- **Animation:** the first animation stack, or the one named or numbered by `options["animation"]`, is sampled from its start to its end at `options["sample_rate"]` (default: the scene frame rate) by evaluating the scene, so animated TRS is in exactly the same space as the static pose. Other stacks are declared as `W_ANIMATIONS_SKIPPED`, negative start times as `W_TIME_SHIFTED`, and more than 100,000 samples, or more sampled values than `max_animation_values`, is `E_RESOURCE_LIMIT`. Channels that never change are left out.

## Mapping and samples

```python
compile_mapping(pack, source_snapshot, target_snapshot, mapping_id,
                allow_approximation=False) -> Result[CompiledMapping]
evaluate_mapping(compiled_mapping, samples) -> Result[EvaluatedValues]
```

`profile_snapshot(pack,id)` explicitly constructs a virtual typed snapshot; it is never an overloaded inspect constructor. Its identity includes pack hash/profile/channels. Asset channels require verified sidecar bindings. Compiler checks snapshot type/unit/domain/calibration against pack, refuses missing references, competing drivers/multiple writers, cycles, unsupported or unresolved requested signals/rules, incompatible units/shapes, and approximation without opt-in. Instructions run in dependency waves: each wave holds the rules whose dependencies all ran in earlier waves, in declaration order, so `[A needs B, B, C]` compiles to `[B, C, A]`. Scheduling visits each rule and dependency edge once rather than rescanning all rules per wave. Intermediate values may remain virtual, terminal outputs must be bound in target. Declared losses survive compilation/evaluation reports.

Authoring validation and pack compilation preserve well-formed `verified_current`,
`proposed` and `unresolved` inventory, including empty evidence arrays. Requested
execution checks each rule, input, intermediate and output: a current rule needs
current endpoints; a proposed rule permits current/proposed endpoints. Every
record needs nonempty own evidence. Current records require every included
reference current, including current endpoints in proposed rules. Proposed
records permit current/proposed references. Participating unresolved records or
references refuse; unreferenced inventory remains allowed. Approximation opt-in
does not change authored statuses or evidence.

Identity additionally requires equal presence and value of `neutral`, `side`
and `coupling` on pack records. Absence differs from zero or an empty coupling
array; null remains structurally invalid. Profile channels keep their existing
type/unit/domain/calibration fields. These metadata equalities apply to identity.

Nonidentity operations need nonempty derivation assumptions when any input
calibration or units differs from the output, quality is approximate, or a loss
effect is `approximated`, `dropped` or `unknown`. Exact numeric operations on one
basis with no declared loss can keep empty assumptions; differing bounds alone
do not imply a different basis. Unit conversion retains its existing explicit
affine requirement. Approximate quality requires explicitly authored nonempty
`loss_annotations`; the compiler no longer supplies a generic loss. Existing
opt-in applies to declared losses even when quality is exact.

| Execution refusal | Diagnostic ref |
| --- | --- |
| `E_EVIDENCE_STATUS` | Offending rule/signal ID; endpoint message names requesting rule |
| `E_EVIDENCE_REQUIRED` | Record ID with empty own evidence |
| `E_EVIDENCE_COMPATIBILITY` | Record ID; message identifies each incompatible evidence ID/status |
| `E_NEUTRAL_COMPATIBILITY`, `E_SIDE_COMPATIBILITY`, `E_COUPLING_COMPATIBILITY` | Identity rule ID; message identifies both endpoints |
| `E_DERIVATION_ASSUMPTIONS`, `E_LOSS_REQUIRED` | Rule ID |

Checks run in rule declaration order, with own rule evidence before endpoint
evidence, inputs before output, and references in authored order. All incompatible
included references are reported. A repeated intermediate is checked at each
participating rule. Existing record, snapshot, graph and channel checks retain
their order. Missing/invalid statuses and unknown IDs still refuse at authoring
validation with `E_REQUIRED`, `E_ENUM` and `E_REFERENCE`.

These are structural arithmetic admission checks. A declared status, assumption,
loss or matching calibration string does not establish physiological, provider
or visual equivalence. Domain review owns the meaning and support for those
claims, including legitimate synthetic mixed-basis operations.

```python
from msf_tools import load_authoring, compile_pack, profile_snapshot
from msf_tools import compile_mapping, evaluate_mapping

authoring = load_authoring("examples/authoring")
assert authoring.ok, authoring.report.to_dict()
pack = compile_pack(authoring.value).value
source = profile_snapshot(pack, "source").value
target = profile_snapshot(pack, "target").value
mapping = compile_mapping(pack, source, target, "wink")
assert mapping.ok, mapping.report.to_dict()
result = evaluate_mapping(mapping.value, [{
    "timestamp": 0.5, "values": {"input.wink": -0.5},
    "validity": {"input.wink": True},
}])
assert result.ok, result.report.to_dict()
assert result.value.to_dict()["samples"][0]["values"]["output.wink"] == -0.5
```

Samples are an array of exact `{timestamp,values,validity}` objects. Timestamp is finite nonnegative seconds, excluding bool. Values are typed by source channel ID; every supplied value has explicit boolean validity. Required missing or invalid input fails, even if its numeric value equals neutral. Values are checked before/after each operation. Frames are independent and preserve input order; no temporal smoothing or hidden resampling. `.to_dict()` returns `{samples:[{timestamp,values:{output_id:value},validity:{output_id:true}}]}`. If any frame fails, entire Result has no evaluated value.

## Independent geometry helpers

```python
evaluate_geometry(snapshot, *, timestamp=0.0, animation_id=None,
                  morph_weights=None, node_transforms=None,
                  attributes=("POSITION",)) -> Result[GeometryValues]
sample_animation(snapshot, animation_id, timestamp) -> Result[immutable node/property map]
export_geometry_golden(snapshot, **kwargs) -> Result[immutable JSON value]
reparent_local(child_world, new_parent_world) -> Result[column-major local matrix]
```

Geometry is usable directly on an inspected fixture without any signal taxonomy. Matrices use column vectors and glTF column-major storage; quaternion XYZW, radians, metres, right-handed Y up. Arithmetic is binary64 after decoding original binary storage. Mesh-local position for every mesh node instance:

```text
p_morph = p_basis + sum(morph_weight * relative_position_delta)
p_local = sum(skin_weight * inverse(W_mesh) * W_joint * IBM * p_morph)
```

Morph precedes skinning. Rest is not assumed equal to bind. LBS uses every influence set: each JOINTS_n must be unsigned unnormalized byte/short and each WEIGHTS_n float or normalized byte/short, paired and numbered from 0. A vertex's influences are the sets in order, so a single set evaluates exactly as four-influence LBS did. All joint indices remain intact; a vertex's weights across all sets are finite nonnegative and sum to one within project tolerance1e-6, with no implicit renormalization. Source adapters can still cut influences to four with `options={"influences": "top4"}`, which declares `W_INFLUENCES_TRUNCATED`. Signed and >1 **morph** weights are accepted. Singular mesh world transforms fail. DQS/unsupported required behavior extensions, compressed semantics and non-position requests reject evaluation. Unknown nonbehavior data remains in snapshot. No geometry is deleted or rewritten.

`animation_id=None` evaluates authored rest/defaults; explicit integer selects one clip. STEP holds; LINEAR interpolates components and shortest quaternion slerp (both keys are normalized first, and keys with a dot product above 0.9995, less than about 3.6° apart, use normalized linear interpolation instead); CUBICSPLINE uses authored in/out tangents multiplied by interval duration in Hermite, then normalizes quaternion result. Tangents and intermediate quaternion polynomials are never normalized. Endpoints clamp; key times must be nonnegative/strictly increasing. Authored rotations (node `rotation`, rotation keys and rotation overrides) must be within 0.00769 of unit length, the Khronos glTF-Validator's limit (`unitLengthThresholdVec4`), or they are `E_QUATERNION`; accepted values are normalized before use. Binary output shape/count must match target/path/interpolation. Inspection validates available core animation data; unsupported extension channels remain inventoried.

`morph_weights` maps integer node IDs to explicit weight arrays. `node_transforms` maps integer node IDs to local TRS or matrix fields using the authored representation. Animation/manual writes to the same property fail; defaults never imply a competing driver. Returned wire is `{timestamp,instances:[{node,mesh,primitives:[{primitive,positions:[[x,y,z],...]}]}]}`. Every primitive uses corresponding accessor vertex order; indices remain in immutable document. Output contains all mesh node instances, including those outside the default scene; callers select instance explicitly. Before any decoding, evaluation counts `3 × vertices × (1 + morph targets with POSITION)` for every primitive of every mesh node instance, plus `8 × vertices × influence sets` for every primitive of every skinned instance (four joint and four weight components per set), plus `16 × joints` once for each skin those instances use, and refuses with `E_RESOURCE_LIMIT` at `/nodes` when the total exceeds 4,000,000 components. That equals the inspection limit on total declared accessor components, so an asset that evaluates each POSITION, morph-target, JOINTS, WEIGHTS and inverse-bind-matrix accessor once always fits; instancing a mesh or sharing accessors multiplies the count. Inverse bind matrices are decoded and checked once per skin per evaluation and reused by every instance sharing that skin. The remaining per-vertex skinning work (at most one palette matrix per distinct referenced joint) grows with vertices × instances, which the budget limits to 1,333,333.

`export_geometry_golden` wraps evaluation with source hash/precision/coordinate/units for consumers. `reparent_local` computes `inverse(new_parent_world)*child_world`, rejects singular/sheared TRS, returns matrix. It probes child world preservation only; skin preservation requires a separate geometry check. No joint deletion is implied.

## CLI and writes

```text
python -m msf_tools check AUTHORING --pack PATH --csv PATH [--coverage PATH] [--sha256 PATH] [--write]
python -m msf_tools inspect ASSET [--resolver-root ROOT] [--sidecar JSON] [--output JSON]
                              [--in-process] [--source-timeout SECONDS] [--max-source-bytes BYTES]
python -m msf_tools annotate ASSET ANNOTATIONS --output SIDECAR
python -m msf_tools map AUTHORING MAPPING --source-profile ID --target-profile ID [--allow-approximation] [--output JSON]
python -m msf_tools evaluate AUTHORING MAPPING SAMPLES --source-profile ID --target-profile ID [--output JSON]
python -m msf_tools geometry ASSET [--time SECONDS] [--animation INDEX] [--output JSON]
```

The format comes from the asset's suffix, so `.usda`, `.usdc`, `.usdz`, `.usd` and `.fbx` files take the source path. Source formats are read in a separate process by default (`isolate=True`); `--in-process` reads them in the CLI's own process. `--source-timeout SECONDS` and `--max-source-bytes BYTES` set `timeout_s` and `max_source_bytes`; an invalid value is `E_CLI_INPUT`. These three flags are accepted by `inspect`, `annotate`, `geometry`, `map` and `evaluate`, and glTF assets ignore them. Output-path checks cover a source file and, after inspection, the layers its reader fetched (`source.dependencies`). When a source-format read fails, its report goes to stderr only and `--output` is not written, because the fetched layers are unknown.

Map/evaluate sides also accept `--source-asset/--source-sidecar` and `--target-asset/--target-sidecar`; asset and profile choice are exclusive. Optional explicit resolver root applies to assets. SAMPLES is an array or sole-key `{samples:[...]}` file. Reports are JSON on stderr; successful values stdout or atomic output files; failed operations return nonzero and may write report to an explicitly safe output destination. Invalid CLI syntax also emits a machine-readable report after argparse help text.

Check renders all pack/CSV/coverage/SHA bytes before replacement and checks expected bytes afterward. Output aliases (resolved path or hardlink) of any input asset/authoring TOML/sample/sidecar/annotation/consumed resource fail `E_OUTPUT_PATH`; for a source format the consumed resources are the fetched layers in `source.dependencies`, checked after inspection and before the output is written. Explicit symlink output destinations fail. Each file is replaced atomically after fsync; there is no multi-file atomicity claim. A common output directory is owned by generation and extra files/directories fail; if outputs use different directories, extra detection is bounded to checksum manifest entries (choose a common directory for full detection). Parent paths are resolved for legitimate platform symlink prefixes. Preflight is protection against mistaken paths, not a guarantee against an adversarial process concurrently replacing directories.
