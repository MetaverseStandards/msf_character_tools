# Version one reference

Original documentation: CC-BY-SA-4.0. This reference describes the project's contracts. `msf_tools.__all__` has 29 public names: the six main operations, plus helpers (such as `load_authoring` and `LocalResolver`) and the result and record types. The pinned [glTF specification](sources.md) defines the external format.

## Results and reports

The six main public functions, and the helpers decorated with `@public`, return the dataclass `Result[T]`. It has `.value: T | None`, `.report: Report` and `.ok: bool`. A `Report` has `schema_version="1.0"`, diagnostics and losses:
- Each diagnostic has `code`, `severity`, one `ref`, `message` and `remediation`.
- Each loss has `category`, `effect`, `reason` and `refs`, and optional `units` and `bound`.

A report that contains any error has no value. At decorated Result APIs, exceptions become diagnostics. Plain serialization functions and helpers raise exceptions: `canonical_json`, record `.to_dict()` and `.to_bytes()`, `survey_csv` and `coverage`. They raise `Fault` for inconsistent records. Callers must check `.ok` before they use values. Records are validated independently, so a failing operation reports several defects where it still makes sense to collect them. Decoding of dependent data stops when the structure is unsafe.

Every diagnostic code is listed in [schemas/diagnostics.toml](../schemas/diagnostics.toml) with its severity, a one-line meaning, the release that added it and, for source losses, the error that replaces it under strict losses.

## Record ownership in package 0.1.1

Create records with `validate_authoring` or `load_authoring`, `compile_pack`, `inspect_asset`, `profile_snapshot`, `compile_mapping`, `annotate_asset`, `evaluate_mapping` and `evaluate_geometry`. The public dataclass constructors keep their signatures for compatibility. But direct construction, copying and `dataclasses.replace` do not make admitted records. To make a record again, use its public factory. This stricter constructor policy affects code that replaces records. Existing wire inputs and factory calls stay the same.

Factories copy containers recursively, freeze `Mapping` objects and arrays, copy nested data records and keep immutable byte values. Admitted nested executable records can share owned immutable state. At compilation, binding, sampling, evaluation and record export, the checks do four things. They require factory admission. They compute again a typed digest of every stored state field. They validate nested records. They check source consistency. A token or a frozen outer dataclass alone does not give these invariants. Changed or unadmitted records fail with `E_RECORD_INTEGRITY`. Result APIs then return no value, and plain exporters raise `Fault`. This is an API consistency contract for callers that use the public interface. It is not isolation from arbitrary Python code or from private internals.

Pack identity hashes the canonical pack bytes. Asset identity hashes the exact original bytes, including whitespace and opaque GLB chunks. Snapshot checks parse the original source and compare it with the owned evaluation view. They verify the digests and declarations of consumed bytes and resources, and derive channels from validated bindings. Assets that differ only in whitespace have equal views and different raw identities. External resource bytes are bound to the bytes that the explicit resolver returned. Source text does not authenticate remote contents. Profile selection and channels, and compiled instructions and dependencies, stay bound to the supplied pack.

Compilation checks each full profile twice: once at entry and once during admission of the compiled record. Each of these boundaries uses a shared signal index. Per-channel checks compare declarations without building profiles again. Each later operation checks the current stored state again. Checks walk the stored state and hash consumed bytes. Asset checks also parse the raw document. Nested dependencies can cause several complete asset hashes and parses per operation. This cost is a fixed multiple, but it matters for consumers that repeat frames. It is not a guarantee of wall time or heap use. General resource budgets beyond the documented limits are future work.

Hardening release 0.1.1 keeps schema, wire and scalar operator 1.0. It adds no wire keys and changes no deterministic bytes of valid input. Scalars must fit in finite binary64, and booleans are not scalars. Huge integers give precise numeric diagnostics instead of an overflow exception. After a JSON numeric refusal, authoring still collects the independent diagnostics for rows and versions. Descriptions must be nonblank strings. Coupling arrays must have unique nonblank entries, and empty arrays stay valid.

The runtime and the portable authoring and pack schemas use one explicit set of blank characters: U+0009–000D, U+001C–0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF. A string must contain at least one character outside that set. Text is kept as it is, without trimming or normalization. The earlier refusals of control whitespace stay, and a string of only U+FEFF is now refused too. Other nonempty Unicode text stays valid. Schema patterns use explicit code points, not whitespace classes that depend on the regex engine. Opaque metadata strings are not description fields. The finite binary64 range and structural references are runtime checks that JSON Schema does not express.

## Authoring and packs

```python
validate_authoring(document) -> Result[ValidatedAuthoring]
compile_pack(validated_authoring) -> Result[Pack]
```

Authoring is a JSON-compatible `Mapping` (such as a `dict`), usually loaded from TOML. The required top-level keys are `schema_version` (`"1.0"` or `"1.1"`), `data_version` (an independent semantic version), `operator_version` (`"1.0"` or `"1.1"`), `id`, `license`, `signals`, `profiles`, `mappings` and `evidence`. The pack wire bytes contain the same validated document. `.document` is deeply immutable. `.to_dict()` returns a detached ordinary JSON value. `.to_bytes()` gives deterministic UTF-8, and `.sha256` hashes those exact bytes. You cannot pass raw dicts to `compile_pack`.

Required signal keys: `id`, `label`, `value_type="scalar"`, `units`, `domain={min?,max?}`, an explicit `calibration`, `disposition`, `evidence` IDs and `evidence_status`. Optional keys: `region`, `side`, `neutral`, `native_default`, `coupling`, `native_id`, `surface`, `validity`, `confidence`, `time` and `metadata`. The neutral value and the storage default are each optional, and each must be within the domain. Units and calibration are explicit nonempty strings. Identity mappings need the same calibration basis on both sides. Scalars exclude bool and all nonfinite values. An unbounded domain is `{}`. Survey text is never run as code.

Disposition: `mapped|unsupported|unresolved|excluded`. Evidence status: `verified_current|proposed|unresolved`, plus `calibrated_software` from authoring schema 1.1. Any other schema version refuses `calibrated_software` with `E_ENUM`. `calibrated_software` marks values fitted in software without measured people or devices. Map compilation treats it exactly as `proposed`, so it never satisfies a `verified_current` record.

Coupling is a description or an array of descriptions. Confidence is a description or a scalar in [0,1]. Validity is a bool or a description. Time is a description. Format-specific structures kept as inventory belong inside explicit `metadata` objects. Unknown keys anywhere else fail.

A profile needs `id`, `label` and `signal_ids`, with optional evidence and metadata. An evidence entry needs `id`, `claim` and `status`. Public evidence has `url` (HTTPS), at least one of `revision`, `retrieved` and `sha256`, and `locator`. Evidence for original fixtures uses `license` and `authorship`. The optional evidence keys are exactly `url,revision,retrieved,sha256,locator,license,authorship`.

A map (one entry of `mappings`) needs `id` and `rules`. A rule has `id,inputs,outputs,operator,disposition,assumptions,evidence,evidence_status,loss_annotations`, an optional `coupling`, and `mapping_quality=exact|approximate` when its disposition is `mapped`. Rule IDs are unique across the document. Inventory IDs are unique within each category. References and duplicate array entries are checked. The operators are:

| Operator | Coefficients | Arity | Numeric operation |
| --- | --- | --- | --- |
| identity | none | one scalar in/out | y=x |
| affine | explicit finite scale, offset | one scalar in/out | y=scale*x+offset |
| weighted_sum | explicit ordered finite weights | N scalar inputs, one output | y=sum(weights[i]*inputs[i]) in declared order |
| piecewise_linear (operators 1.1) | `knots=[[x,y],...]`, at least two | one scalar in/out | y=y_i at a knot; otherwise y=y_i+t*(y_{i+1}-y_i), t=(x-x_i)/(x_{i+1}-x_i), in the segment holding x |

The output domain of unary and weighted operators is checked during evaluation. Identity needs equal declared domains. Units must be compatible. An explicit affine unit conversion needs stated assumptions. No operator implies a clamp, an inverse, neutral substitution, bilateral expansion or synthesis. Unresolved inventory compiles into a pack, but a request for an unresolved rule fails map compilation.

`piecewise_linear` needs `operator_version="1.1"`. In a document with `operator_version="1.0"`, a rule that names it fails with `E_OPERATOR_VERSION` alone, before its keys or knots are checked. 0.2 reported `E_UNKNOWN_KEY` for its `knots` key, or `E_ENUM` when it had no `knots` key. Under operators 1.0, a `knots` key on another operator is still `E_UNKNOWN_KEY`. Under 1.1 it is `E_OPERATOR`. A document whose `operator_version` is unknown fails with `E_ENUM`, and its rules are checked as operators 1.0.

Knot x values must strictly increase. Knot y values must be monotone in one direction, and flat segments are allowed. The span between neighbouring knots must be finite binary64 (`E_KNOTS`). Map compilation requires the first and last x to equal the input signal's declared `min` and `max` (`E_DOMAIN_COMPATIBILITY`), so there is no extrapolation. The segment formula uses the same checked binary64 arithmetic as `affine`, so a product that underflows is refused with `E_NONFINITE`. The result is kept within the segment's two y values. This keeps the operator monotone across knots, even with rounding. That guard is not a clamp to any domain. Inputs and outputs are still checked against their declared domains, and are never clamped. A one-sided split such as `[[-1,1],[0,0],[1,0]]` is exactly zero on its flat side, so two opposite splits of one signed value are never both nonzero.

### Fragment loader

`load_authoring(path) -> Result[ValidatedAuthoring]` accepts one TOML file, or a directory that contains `pack.toml`. In a directory, the TOML fragments are found recursively and sorted by relative path. Any `generated` directory is left out, and so is every hidden file or directory component (a name that starts with `.`). Exclusion uses relative paths, so an authoring root that is hidden on purpose is still allowed. Hidden virtual environments and CI checkouts are pruned before the walk enters them. Array categories are joined in that order. A metadata key cannot occur twice, even if the values match. Symlinks, reserved device file names and path collisions that ignore case fail. Fragments are opened without blocking, so a FIFO or other non-regular `.toml` entry fails with `E_FRAGMENT_PATH` instead of hanging. TOML datetime values must be quoted when they are stored as strings. Arbitrary non-JSON objects fail.

### Deterministic outputs

`canonical_json(value) -> bytes` changes -0.0 to 0.0 recursively, and then uses exactly `json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)+"\n"`, in UTF-8. Array order is kept. This is the project's byte convention. It is not certified to RFC 8785. No timestamps or absolute machine paths are added. Metadata that the caller wrote stays the caller's data.

`survey_csv(pack) -> bytes` writes UTF-8 with LF line ends and `csv.QUOTE_MINIMAL`. The header is `id,label,value_type,units,disposition,evidence_status`, then the profile IDs in declared order. Membership is `1` or empty. Existing CRLF survey formats that other projects own must use their original checker. This new CSV does not rewrite them.

`coverage(pack) -> dict` includes, for each signal, its disposition, reason, and uses in profiles and rules. It includes all the evidence, unused and unresolved entries too. It also has partitions by rule quality, aggregate totals, partitions and counts for each profile, and the original metadata. SHA256SUMS hashes the exact bytes of the pack, the CSV and the coverage, in that order, with the line format `digest + "  " + basename + LF`. The four output basenames must be different.

## Snapshots and sidecars

```python
inspect_asset(bytes, /, format, resolver=None, sidecar=None, *,
              isolate=False, limits=None, options=None) -> Result[AssetSnapshot]
annotate_asset(snapshot, annotations) -> Result[Sidecar]
```

Supported format strings: `gltf` and `glb`, and `json` and `gltf2` as aliases for JSON. The input is immutable bytes, passed by position. `bytes` is positional-only, so `inspect_asset(bytes=...)` is refused with `E_INPUT`. A snapshot keeps these:
- `.original_bytes` and `.sha256`;
- the deeply immutable `.document`;
- `.chunks`, with the original payload bytes;
- `.resources`, each with its URI, declared byte length, digest and consumed data;
- `.channels` and `.bindings`.

`.to_dict()` gives the complete document, inventory and capabilities, without copies of binary payloads. Hashes identify the source bytes. Names are only for display.

By default, nothing external is fetched, remote or local. Embedded base64 data and the BIN chunk are consumed explicitly. An external buffer that is not consumed gives a warning and an inventory entry, and decoding it fails with `E_RESOURCE_UNAVAILABLE`. Images are listed as inventory. External images are consumed only with an explicit resolver. Unknown required extensions and animation targets defined by extensions can be inspected. But a request for evaluation applies the stricter capability gate.

`LocalResolver(root,max_resource_bytes=64MiB,max_total_bytes=256MiB)` is a callable. The root must be canonical, with no symlink among its ancestors (`Path(root).resolve()` is explicit). URI paths are relative and percent-decoded, with no traversal, query, fragment or remote scheme. Each directory and file is opened with no-follow, nonblocking descriptors, which refuse symlink traversal and substitution. Only regular files are read. FIFOs, devices and sockets fail with `E_RESOURCE_TYPE`, without waiting on the open. Budgets add up over the life of a resolver. For a new budget, make a new resolver. A custom callable is a capability that the caller gives explicitly, and it must return bytes.

Inspection limits:
- input: 64MiB;
- each resource: 64MiB;
- total consumed resources: 256MiB;
- decoded components per accessor: 1,000,000;
- total declared accessor components: 4,000,000;
- objects per category: 100,000;
- JSON nesting: 128 levels.

These checks run before allocation for zero-backed and sparse accessors. Custom resolvers must limit their own allocation before they return. JSON parser recursion failures are diagnostics. Large production assets need a revision of the limits, reviewed separately. The limits do not promise streaming.

Accessors support all core component types, matrix column padding, offsets, interleaving, normalized byte and short values, and strictly increasing sparse overrides. Bounds are checked, and decoded floats must be finite. Zero-backed accessors are supported within the same budgets. Binary data used for geometry or animation gets more type and shape checks when it is evaluated.

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

`annotate_asset` accepts `{bindings:[...],metadata?:{...}}`. The output is a canonical, idempotent sidecar. Each reuse of the sidecar verifies the source hash, the hashes of all consumed resources, the structural indices, and that the locator agrees. The sidecar binds the digests of sparse indices, sparse values and base buffers. The optional `ref.resource_sha256` must identify a consumed target resource. Binding IDs and destinations are unique. The first version supports scalar morph weights for each mesh instance. Other shapes of channel binding need an explicit revision.

`morph_binding(snapshot, signal, node, target) -> Result[immutable binding]` makes a structural binding from a pack signal. When it applies, the binding includes the digest of the single target resource. When there are several buffers, `resource_hashes` still binds all of them. `decode_accessor(snapshot,index)` returns `Result[tuple[tuple[number,...],...]]`.

### Source formats

`format` may also be `usd`, `usda`, `usdc`, `usdz` or `fbx`. The leading bytes must match: `#usda`, `PXR-USDC`, a ZIP header for `usdz`, and for `fbx` the binary magic or text that starts with a letter or `;`. `usd` accepts USDA or USDC and records which one it found. A mismatch is `E_FORMAT_MISMATCH`, and an unknown format is `E_ASSET_TYPE`. Reading needs the format's adapter and its reader library. Without them the result is `E_FORMAT_DEPENDENCY`. The message says if this build has no adapter at all, or lacks only the optional reader, which `msf-tools[usd]` installs. The FBX reader is compiled into the core, so FBX always has its reader. The adapters themselves are added separately. This section describes the contract they share.

An adapter converts the source into an in-memory GLB with one glTF vertex per source point. The unchanged glTF inspector then admits it, and `original_bytes`, `sha256` and `format="glb"` describe that GLB. `source` records:
- `format`, `sha256` and `byte_length` of the source; the source bytes are not kept;
- `adapter`, `adapter_version` and `reader`;
- `options_sha256`, the digest of the canonical options with defaults filled in;
- `node_order="path-sorted-v2"`;
- `node_paths`, one per glTF node, and `target_keys`, one list per glTF mesh in target order;
- `dependencies` (`uri`, `sha256`, `byte_length`, sorted by URI) and `losses` (warning or info diagnostics, which are also in the report).

The GLB bytes are deterministic for a fixed source, dependency set, adapter version, reader version and options. They are not deterministic across reader versions, so no hash of them is stored. Every recorded hash is the source sha256 instead:
- snapshot `asset_sha256` (`to_dict` adds `generated_sha256` and `source`);
- sidecar and binding `asset_sha256`;
- geometry golden `asset_sha256`;
- compiled-map `source_sha256` and `target_sha256`.

Goldens and compiled maps add a summary of how the snapshot was produced (`source`, or `source_adapter` / `target_adapter`). Sidecar `resource_hashes` lists the source dependencies. In a generated snapshot's `to_dict`, `generated_sha256`, `document`, `resources` and `chunks` describe the generated GLB and can change when the reader version changes. Only `asset_sha256` and `source` identify the source.

Node paths escape `%`, `/`, `#`, `[`, `]`, `:` and control characters in each component. `[k]` tells duplicate siblings apart. `#helper:geometry` or `#helper:scale` marks helper nodes that the reader made. glTF node `i` is the `i`-th path in order of unescaped components. A generated-snapshot binding must carry `ref.source_locator = <node path>#<target key>`, which is authoritative. The stored `node`, `mesh`, `target` and `locator` are hints:
- if a different reader version moved them, the binding is admitted with the resolved indices and a `W_BINDING_REINDEXED` warning;
- if the locator names nothing in the source, it is `E_STALE_SOURCE`;
- `resource_sha256` is refused.

glTF bindings never use `source_locator`.

`options` is a `Mapping` with only these keys:
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
| `max_animation_values` | 16,000,000 | Values sampled before conversion: FBX counts samples × (16 × nodes + blend channels), USD time codes × (16 × animated nodes and joints + blend channels). Both refuse beyond it before sampling. |

glTF formats refuse `isolate`, `limits` and `options` with `E_SOURCE_OPTIONS`.

`isolate=True` runs the source reader in a new Python process. The process runs `python -I`, starts from the msf-tools checkout or installation, has only `PATH`, `TMPDIR` and `PXR_WORK_THREAD_LIMIT=1` in its environment, and has its own process group. The calling process never imports the reader library. The returned GLB is inspected again as untrusted input, so the snapshot is the same as without isolation. The resolver must be `None` or a `LocalResolver`. The reader process builds the `LocalResolver` again from its root and budgets. Any other resolver is `E_ISOLATE_RESOLVER`. Failures:
- running longer than `timeout_s` kills the process group: `E_SOURCE_TIMEOUT`;
- physical memory over `max_reader_memory` (sampled every 100 ms) kills it too: `E_SOURCE_MEMORY`;
- a reader process that exits with an error or a signal: `E_SOURCE_CRASHED`, with the end of its stderr;
- a malformed response: `E_SOURCE_PROTOCOL`.

The two modes report an unexpected exception inside the reader (a bug, not a declared refusal) differently. Isolated, it is `E_SOURCE_CRASHED` with the end of the traceback. In-process, it is `E_INPUT` or `E_INTERNAL` from the operation boundary. Declared refusals, reader parse errors and limits give the same diagnostics in both modes.

#### USD adapter (`msf-usd`, usd-core 25.11 to 26.x)

Install with `pip install 'msf-tools[usd]'`. Every Xformable or Scope prim (instance proxies included) becomes a glTF node, in path-sorted order. A Mesh prim gets its own glTF mesh: points become vertices and faces are fan-triangulated from their first corner. Blend shapes bound through `skel:blendShapes`/`skel:blendShapeTargets` become morph targets keyed by their token. Reader errors in any layer are `E_SOURCE_PARSE`.

- **Units and up axis** are applied to the data, so geometry comes back in metres with +Y up. With C = `metersPerUnit` times the Z-up to Y-up rotation (identity for Y-up), points and blend offsets become C·p and local transforms C·L·C⁻¹. An unauthored `metersPerUnit` means centimetres, as in USD. Conversions are declared as `I_UNITS_CONVERTED` and `I_AXES_CONVERTED`.
- **Local transforms** come from the earliest authored time and must be affine, finite and nonsingular. A negative determinant is stored as a negative X scale (`I_MIRRORED`). Shear means two axes of the linear part are more than 1e-6 from perpendicular, in cosine. On a static, unskinned leaf mesh, shear is baked into the points and the node is left with no transform (`W_SHEAR_BAKED`). Anywhere else it is `E_SHEAR_UNSUPPORTED`.
- **Faces:** hole faces are dropped, subdivision surfaces use their control cage (`W_SUBDIV_CAGE`), and `orientation = "leftHanded"` faces are reversed (`I_WINDING_FLIPPED`).
- **Skinning** follows UsdSkel bindings under a SkelRoot. Each bound Skeleton's joints become nodes named `<skeleton path>.joints/<joint token>` (for example `/Rig/Skel.joints/root/arm`), parented by the joint topology under the Skeleton node and posed at the earliest time. A skeleton without `restTransforms` and without an animation covering every joint is refused (`E_SOURCE_VALUE`); rest poses are not derived from `bindTransforms`. Each skeleton gets one glTF skin over all its joints, with inverse bind matrices `inv(C·bind·C⁻¹)`. Skinned points are carried through `geomBindTransform`, and influence indices are mapped through `skel:joints` to skeleton joints; constant influences apply to every point. Declared losses:
  - more than four influences are kept in extra `JOINTS_n`/`WEIGHTS_n` sets (`I_INFLUENCES_N`), or with `options={"influences": "top4"}` cut to the four largest, ties going to the lower joint, and renormalized (`W_INFLUENCES_TRUNCATED`);
  - weights that don't sum to 1 within 1e-6 are normalized (`W_WEIGHTS_NORMALIZED`);
  - vertices with no weight are bound to the first root joint (`W_UNWEIGHTED_VERTICES`);
  - `dualQuaternion` skinning is stored as linear blend skinning (`W_SKINNING_METHOD`).

  A skinned mesh or joint with shear is `E_SHEAR_UNSUPPORTED`.
- **Blend shapes** keep their point indices, so sparse shapes stay sparse in the GLB. A shape that authors only `normalOffsets` becomes an all-zero target. A mesh bound to a skeleton only for its blend shapes gets its weights animated without a skin. In-between shapes are dropped and the main shape kept (`W_INBETWEENS_DROPPED`; `E_INBETWEEN_UNSUPPORTED` under strict losses).
- **Animation:** one glTF animation samples every animated transform, skeleton and blend-weight channel at the union of their authored time codes. The time codes are kept within the stage's start and end time codes when those are authored, and are divided by `timeCodesPerSecond`. Negative time codes are shifted so the animation starts at 0 (`W_TIME_SHIFTED`). Samplers are LINEAR, with quaternions kept in one hemisphere. Channels whose value never changes are left out. Shear in any sample is `E_SHEAR_UNSUPPORTED`. More sampled values than `max_animation_values` is `E_RESOURCE_LIMIT`, checked before any sample is taken.
- **Skipped prims:** curves, points, NURBS, implicit surfaces, point instancers, cameras, lights and materials are counted by type in one `W_SKIPPED`, together with hole faces. Xformable ones still become nodes.
- **Point animation:** glTF animates points only through morph targets. When a mesh's points, topology, blend-shape offsets or skin primvars change over time, the mesh keeps their earliest value. Each such mesh gets one `W_POINTS_ANIMATION_DROPPED` that names the attributes (`E_POINTS_ANIMATION_DROPPED` under strict losses).

Before a stage is opened, every layer named by a sublayer, reference or payload is gathered:

- Layer paths are relative to the layer that names them and must stay inside the source root. A bare path such as `sub.usda` is looked up next to that layer, which is the first place USD looks; USD search paths are never used. Absolute paths, URLs and other schemes, backslashes and escapes are `E_SOURCE_REFERENCE`, as are value clips.
- Outside a USDZ, the resolver fetches each layer by its anchored path (for example `parts/sub.usda`). A missing resolver or an unreadable layer is `E_SOURCE_REFERENCE`. Fetched layers are recorded in `source.dependencies`, and `max_dependencies`/`max_dependency_bytes` are checked after each fetch.
- Inside a USDZ, layers must be members of the package and are not fetched. The archive must be readable, with stored, unencrypted, uniquely named relative members, at most `max_usdz_members` of them; otherwise it is `E_USDZ_ARCHIVE`.

#### FBX adapter (`msf-ufbx`, ufbx 0.23.1)

ufbx and the `msf-ufbx` shim are compiled into the C++ core, so nothing extra needs installing; the `[fbx]` extra is empty and kept so existing install commands work. The reader identity comes from the compiled ufbx's `ufbx_source_version`. Binary, ASCII and deflated FBX are read from memory only; external files and embedded media are never loaded. Reader errors are `E_SOURCE_PARSE`, and going over `max_reader_memory` (passed to ufbx's allocators) is `E_SOURCE_MEMORY`. Hierarchies deeper than 1024 nodes are refused.

- **Space:** ufbx converts the scene to metres and right-handed +Y up. It applies geometric transforms to the points, compensates inherit types, and moves pivots, offsets and pre/post rotations into the node transforms. Node TRS therefore comes from ufbx's node-to-parent matrices. Conversions are declared as `I_UNITS_CONVERTED`, `I_AXES_CONVERTED` and `I_PIVOTS_BAKED`. Sometimes ufbx has to add a helper node: a geometry helper for an instanced mesh with geometric transforms, or a scale helper for inherited scale. The helper is kept as `<owner path>#helper:geometry` or `#helper:scale`, and declared as `W_HELPER_NODES`.
- **Nodes:** every node apart from the ufbx root becomes a glTF node. Paths are `/` plus escaped ancestor names, with `[k]` on siblings that share a name, numbered in file order. Shear, mirror and singular transforms follow the same rules as USD.
- **Meshes:** one glTF mesh per FBX mesh, shared by its instances, with control points as vertices and faces triangulated by ufbx. Hole faces, faces with fewer than three corners and empty meshes are counted in `W_SKIPPED`. A mesh that displays as a smoothed subdivision surface (Smoothness 2 or 3 with at least one preview level) keeps its control cage (`W_SUBDIV_CAGE`). A mesh with a vertex cache deformer keeps its own points; the cache file is never read, and `W_POINTS_ANIMATION_DROPPED` is declared at the mesh's node (`E_POINTS_ANIMATION_DROPPED` under strict losses).
- **Skin:** one glTF skin per skinned mesh. Each cluster's bone becomes a joint whose inverse bind matrix is ufbx's geometry-to-bone matrix. Weights follow the shared influence rules (`I_INFLUENCES_N`, `W_INFLUENCES_TRUNCATED`, `W_WEIGHTS_NORMALIZED`, `W_UNWEIGHTED_VERTICES`, which binds to the nearest ancestor joint of the mesh, else the skeleton root). Rigid, dual-quaternion and blended skinning are stored as linear blend skinning (`W_SKINNING_METHOD`). A mesh with more than one skin deformer is refused.
- **Blend shapes:** each blend channel becomes a morph target keyed `<deformer name>/<channel name>`, with `[k]` on repeated names. The keyframe at full weight is kept and other keyframes are dropped (`W_INBETWEENS_DROPPED`; `E_INBETWEEN_UNSUPPORTED` under strict losses). A channel with no full-weight keyframe uses its largest keyframe scaled to full weight (`W_INBETWEEN_PARTIAL`). Static channel weights (`DeformPercent / 100`) become the default weights.
- **Animation:** the first animation stack, or the one named or numbered by `options["animation"]`, is sampled from its start to its end at `options["sample_rate"]` (default: the scene frame rate) by evaluating the scene, so animated TRS is in exactly the same space as the static pose. Other stacks are declared as `W_ANIMATIONS_SKIPPED`, negative start times as `W_TIME_SHIFTED`, and more than 100,000 samples, or more sampled values than `max_animation_values`, is `E_RESOURCE_LIMIT`. Channels that never change are left out.

## Maps and samples

```python
compile_mapping(pack, source_snapshot, target_snapshot, mapping_id,
                allow_approximation=False) -> Result[CompiledMapping]
evaluate_mapping(compiled_mapping, samples) -> Result[EvaluatedValues]
```

`compile_mapping` compiles one map: the `[[mappings]]` entry named by `mapping_id`. `evaluate_mapping` runs the compiled map (`CompiledMapping`) on samples.

`profile_snapshot(pack,id)` explicitly makes a virtual typed snapshot. It is never an overloaded form of inspection. Its identity includes the pack hash, the profile and the channels. Asset channels need verified sidecar bindings. The compiler checks the snapshot's types, units, domains and calibration against the pack. It refuses these:
- missing references;
- competing drivers and multiple writers;
- cycles;
- requested signals or rules that are unsupported or unresolved;
- incompatible units or shapes;
- approximation without opt-in.

Instructions run in dependency waves. Each wave holds the rules whose dependencies all ran in earlier waves, in declaration order. For example, `[A needs B, B, C]` compiles to `[B, C, A]`. Scheduling visits each rule and dependency edge once, and does not scan all rules again for each wave. Intermediate values can stay virtual. Terminal outputs must be bound in the target. Declared losses are kept in the compilation and evaluation reports.

Authoring validation and pack compilation keep well-formed `verified_current`,
`proposed` and `unresolved` inventory, empty evidence arrays included. A request
to run a map checks each rule, input, intermediate and output. A current rule
needs current endpoints. A proposed rule allows current or proposed endpoints.
Every record needs nonempty evidence of its own. Current records need every
reference they include to be current, and this includes current endpoints in
proposed rules. Proposed records allow current or proposed references. Unresolved
records or references that take part are refused. Inventory that nothing
references is still allowed. Approximation opt-in does not change the authored
statuses or evidence.

Identity also needs `neutral`, `side` and `coupling` to be equally present, with
equal values, on the pack records. An absent key is different from zero or from an
empty coupling array. Null is still structurally invalid. Profile channels keep
their existing type, unit, domain and calibration fields. These metadata equality
rules apply only to identity.

Operations other than identity need nonempty derivation assumptions in three
cases: an input's calibration or units differ from the output's, the quality is
approximate, or a loss effect is `approximated`, `dropped` or `unknown`. Exact
numeric operations on one basis with no declared loss can keep empty assumptions.
Different bounds alone do not mean a different basis. Unit conversion keeps its
existing rule that it must be an explicit affine. Approximate quality needs
nonempty `loss_annotations`, authored explicitly. The compiler no longer adds a
generic loss. The existing opt-in applies to declared losses, even when the
quality is exact.

| Execution refusal | Diagnostic ref |
| --- | --- |
| `E_EVIDENCE_STATUS` | Offending rule/signal ID; endpoint message names requesting rule |
| `E_EVIDENCE_REQUIRED` | Record ID with empty own evidence |
| `E_EVIDENCE_COMPATIBILITY` | Record ID; message identifies each incompatible evidence ID/status |
| `E_NEUTRAL_COMPATIBILITY`, `E_SIDE_COMPATIBILITY`, `E_COUPLING_COMPATIBILITY` | Identity rule ID; message identifies both endpoints |
| `E_DERIVATION_ASSUMPTIONS`, `E_LOSS_REQUIRED` | Rule ID |

Checks run in rule declaration order. A rule's own evidence comes before endpoint
evidence, inputs come before the output, and references follow the authored order.
All incompatible included references are reported. A repeated intermediate is
checked at each rule it takes part in. The existing record, snapshot, graph and
channel checks keep their order. Missing or invalid statuses and unknown IDs are
still refused at authoring validation, with `E_REQUIRED`, `E_ENUM` and
`E_REFERENCE`.

These are structural checks for admitting arithmetic. A declared status,
assumption or loss, or a matching calibration string, does not show physiological,
provider or visual equivalence. Domain review owns the meaning of those claims and
the support for them. This includes legitimate synthetic operations that mix
bases.

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

Samples are an array of objects with exactly the keys `{timestamp,values,validity}`. The timestamp is finite, nonnegative seconds, and not a bool. Values are keyed by source channel ID and typed by that channel. Every supplied value has an explicit boolean validity. A required input that is missing or invalid fails, even if its numeric value equals the neutral value. Values are checked before and after each operation. Frames are independent and keep the input order. There is no temporal smoothing and no hidden resampling. `.to_dict()` returns `{samples:[{timestamp,values:{output_id:value},validity:{output_id:true}}]}`. If any frame fails, the whole Result has no evaluated value.

## Independent geometry helpers

```python
evaluate_geometry(snapshot, *, timestamp=0.0, animation_id=None,
                  morph_weights=None, node_transforms=None,
                  attributes=("POSITION",)) -> Result[GeometryValues]
sample_animation(snapshot, animation_id, timestamp) -> Result[immutable node/property map]
export_geometry_golden(snapshot, **kwargs) -> Result[immutable JSON value]
reparent_local(child_world, new_parent_world) -> Result[column-major local matrix]
```

You can use geometry directly on an inspected fixture, without any signal taxonomy. Matrices use column vectors and glTF column-major storage. Quaternions are XYZW. Units are radians and metres, in a right-handed, Y-up frame. Arithmetic is binary64, after the original binary storage is decoded. The mesh-local position for every mesh node instance is:

```text
p_morph = p_basis + sum(morph_weight * relative_position_delta)
p_local = sum(skin_weight * inverse(W_mesh) * W_joint * IBM * p_morph)
```

Morphing comes before skinning. The rest pose is not assumed to equal the bind pose. LBS uses every influence set. Each JOINTS_n must be unsigned, unnormalized byte or short. Each WEIGHTS_n must be float, or normalized byte or short. The sets are paired and numbered from 0. A vertex's influences are the sets in order, so a single set evaluates exactly as four-influence LBS did. All joint indices stay intact. Across all sets, a vertex's weights are finite and nonnegative, and sum to one within the project tolerance 1e-6, with no implicit renormalization. Source adapters can still cut influences to four with `options={"influences": "top4"}`, which declares `W_INFLUENCES_TRUNCATED`.

Signed **morph** weights, and morph weights above 1, are accepted. Singular mesh world transforms fail. Evaluation refuses DQS, unsupported required behaviour extensions, compressed semantics and requests for attributes other than positions. Unknown data that does not affect behaviour stays in the snapshot. No geometry is deleted or rewritten.

`animation_id=None` evaluates the authored rest values and defaults. An explicit integer selects one clip. Sampling works like this:
- STEP holds the value.
- LINEAR interpolates components, and uses the shortest quaternion slerp. Both keys are normalized first. Keys with a dot product above 0.9995 (less than about 3.6° apart) use normalized linear interpolation instead.
- CUBICSPLINE uses the authored in and out tangents, multiplied by the interval duration, in Hermite form, and normalizes a quaternion result.

Tangents and intermediate quaternion polynomials are never normalized. Endpoints clamp. Key times must be nonnegative and strictly increasing. Authored rotations (node `rotation`, rotation keys and rotation overrides) must be within 0.00769 of unit length, or they are `E_QUATERNION`. This is the Khronos glTF-Validator's limit (`unitLengthThresholdVec4`). Accepted values are normalized before use. The shape and count of the binary output must match the target, path and interpolation. Inspection validates the core animation data that is available. Unsupported extension channels stay in the inventory.

`morph_weights` maps integer node IDs to explicit weight arrays. `node_transforms` maps integer node IDs to local TRS or matrix fields, in the authored representation. If animation and a manual override write the same property, evaluation fails. Defaults never count as a competing driver. The returned wire is `{timestamp,instances:[{node,mesh,primitives:[{primitive,positions:[[x,y,z],...]}]}]}`. Every primitive uses the vertex order of its accessor. Indices stay in the immutable document. The output contains all mesh node instances, also those outside the default scene. Callers select the instance explicitly.

Before any decoding, evaluation counts components and refuses with `E_RESOURCE_LIMIT` at `/nodes` when the total is more than 4,000,000. The count is the sum of:
- `3 × vertices × (1 + morph targets with POSITION)` for every primitive of every mesh node instance;
- `8 × vertices × influence sets` for every primitive of every skinned instance (four joint and four weight components per set);
- `16 × joints`, once for each skin that those instances use.

That limit equals the inspection limit on total declared accessor components. An asset that evaluates each POSITION, morph-target, JOINTS, WEIGHTS and inverse-bind-matrix accessor once always fits. Instancing a mesh or sharing accessors multiplies the count. Inverse bind matrices are decoded and checked once per skin per evaluation, and every instance that shares that skin uses them again. The remaining per-vertex skinning work (at most one palette matrix per distinct referenced joint) grows with vertices × instances. The budget limits that product to 1,333,333.

`export_geometry_golden` wraps evaluation for consumers, and adds the source hash, precision, coordinate system and units. `reparent_local` computes `inverse(new_parent_world)*child_world`, refuses a singular or sheared TRS, and returns the matrix. It checks only that the child's world transform is preserved. A separate geometry check is needed to show that skinning is preserved. Reparenting does not imply that a joint is deleted.

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

The format comes from the asset's suffix, so `.usda`, `.usdc`, `.usdz`, `.usd` and `.fbx` files take the source path. By default, source formats are read in a separate process (`isolate=True`). `--in-process` reads them in the CLI's own process. `--source-timeout SECONDS` and `--max-source-bytes BYTES` set `timeout_s` and `max_source_bytes`. An invalid value is `E_CLI_INPUT`. `inspect`, `annotate`, `geometry`, `map` and `evaluate` accept these three flags, and glTF assets ignore them. Output-path checks cover a source file and, after inspection, the layers that its reader fetched (`source.dependencies`). When a source-format read fails, its report goes only to stderr, and `--output` is not written, because the fetched layers are unknown.

For each side, `map` and `evaluate` also accept `--source-asset/--source-sidecar` and `--target-asset/--target-sidecar`. For one side, you can choose an asset or a profile, not both. The optional explicit resolver root applies to assets. The SAMPLES file holds an array, or an object whose only key is `samples` (`{samples:[...]}`). Reports are JSON on stderr. Successful values go to stdout or to atomic output files. Failed operations return nonzero, and can write the report to an output destination that is explicitly safe. Invalid CLI syntax also gives a machine-readable report, after the argparse help text.

`check` renders all the pack, CSV, coverage and SHA bytes before it replaces any file, and checks the expected bytes afterwards. An output that aliases an input fails with `E_OUTPUT_PATH`. An alias is the same resolved path or a hard link. Inputs are assets, authoring TOML, samples, sidecars, annotations and consumed resources. For a source format, the consumed resources are the fetched layers in `source.dependencies`. They are checked after inspection and before the output is written. An explicit symlink as output destination fails. Each file is replaced atomically after fsync. There is no claim of atomicity across several files.

Generation owns a common output directory, and extra files or directories in it fail. If the outputs are in different directories, only the entries in the checksum manifest are checked for extras. For full detection, choose a common directory. Parent paths are resolved, to allow legitimate platform symlink prefixes. The preflight check protects against mistaken paths. It does not guarantee anything against a hostile process that replaces directories at the same time.
