# Version one reference

Original documentation: CC-BY-SA-4.0. This reference describes project contracts; the pinned [glTF specification](sources.md) defines the external format.

## Results and reports

All six public functions and fallible helpers return dataclass `Result[T]` with `.value: T | None`, `.report: Report` and `.ok: bool`. Report has `schema_version="1.0"`, diagnostics and losses. Each diagnostic has `code`, `severity`, singular `ref`, `message`, `remediation`; losses have `category`, `effect`, `reason`, `refs` and optional `units`, `bound`. A report containing any error has no value. Exceptions at public APIs become diagnostics; callers must check `.ok` before using values. Records are validated independently so a failing operation reports multiple defects where collection remains meaningful; dependent decoding stops when structure is unsafe.

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

`load_authoring(path) -> Result[ValidatedAuthoring]` accepts one TOML file or directory containing `pack.toml`. Directory TOML fragments are recursively sorted by relative path, excluding any `generated` directory and all hidden file/directory components (names beginning with `.`). Exclusion uses relative paths: a deliberately hidden authoring root is still allowed. Hidden virtual environments and CI checkouts are pruned before traversal. Array categories concatenate in that order; metadata keys cannot occur twice even if values match. Symlinks, reserved device filenames and case-insensitive path collisions fail. TOML datetime values must be quoted when stored as strings; arbitrary non-JSON objects fail.

### Deterministic outputs

`canonical_json(value) -> bytes` recursively normalizes -0.0 to 0.0, then uses exactly `json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)+"\n"`, UTF-8. Array order is preserved. This is the project byte convention, not RFC8785 certification. No timestamps or absolute machine paths are injected. Caller-authored metadata remains caller data.

`survey_csv(pack) -> bytes` writes UTF-8 LF, `csv.QUOTE_MINIMAL`, header `id,label,value_type,units,disposition,evidence_status` then profile IDs in declared order; membership is `1` or empty. Existing independently owned CRLF survey formats must use their original checker; this new CSV does not rewrite them.

`coverage(pack) -> dict` includes signal disposition/reason/profile/rule uses; complete evidence including unused/unresolved entries; rule quality partitions; aggregate totals; per-profile partitions/counts and original metadata. SHA256SUMS hashes pack, CSV and coverage exact bytes, in that order, using `digest + "  " + basename + LF`. Four output basenames must be distinct.

## Snapshots and sidecars

```python
inspect_asset(bytes, format, resolver=None, sidecar=None) -> Result[AssetSnapshot]
annotate_asset(snapshot, annotations) -> Result[Sidecar]
```

Supported format strings: `gltf`, `glb` (also `json`/`gltf2` JSON aliases). Input is immutable bytes. Snapshot retains `.original_bytes`, `.sha256`, deeply immutable `.document`, `.chunks` with original payload bytes, `.resources` with URI/declared byte length/digest/consumed data, `.channels` and `.bindings`. `.to_dict()` publishes complete document/inventory/capabilities without embedding duplicate binary payloads. Hashes are source byte identities; names are display only.

No default remote or local external fetch. Embedded base64 and BIN are explicitly consumed. Unconsumed external buffers produce warning/inventory; decoding them fails `E_RESOURCE_UNAVAILABLE`. Images are inventoried; external images are consumed only with explicit resolver. Unknown required extensions and extension-defined animation targets may be inspected, but requested evaluation applies the stricter capability gate.

`LocalResolver(root,max_resource_bytes=64MiB,max_total_bytes=256MiB)` is a callable. Root must be canonical, without symlink ancestors (`Path(root).resolve()` is explicit). URI paths are relative, percent-decoded, no traversal, query, fragment or remote scheme. Each directory/file is opened with no-follow descriptors to reject symlink traversal and substitution. Regular files only. Budgets accumulate over resolver lifetime; create a new resolver for a new budget. Custom callables are explicit caller capability and must return bytes.

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

## Mapping and samples

```python
compile_mapping(pack, source_snapshot, target_snapshot, mapping_id,
                allow_approximation=False) -> Result[CompiledMapping]
evaluate_mapping(compiled_mapping, samples) -> Result[EvaluatedValues]
```

`profile_snapshot(pack,id)` explicitly constructs a virtual typed snapshot; it is never an overloaded inspect constructor. Its identity includes pack hash/profile/channels. Asset channels require verified sidecar bindings. Compiler checks snapshot type/unit/domain/calibration against pack, refuses missing references, competing drivers/multiple writers, cycles, unsupported or unresolved requested signals/rules, incompatible units/shapes, and approximation without opt-in. Instructions use stable topological order; independent rules preserve declared order. Intermediate values may remain virtual, terminal outputs must be bound in target. Declared losses survive compilation/evaluation reports.

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

Morph precedes skinning. Rest is not assumed equal to bind. Four influence LBS requires unsigned unnormalized byte/short JOINTS_0 and float or normalized byte/short WEIGHTS_0. All joint indices remain intact; skin weights are finite nonnegative and sum to one within project tolerance1e-6, with no implicit renormalization. Signed and >1 **morph** weights are accepted. Singular mesh world transforms fail. Extra JOINTS_n/WEIGHTS_n sets, DQS/unsupported required behavior extensions, compressed semantics and non-position requests reject evaluation. Unknown nonbehavior data remains in snapshot. No geometry is deleted or rewritten.

`animation_id=None` evaluates authored rest/defaults; explicit integer selects one clip. STEP holds; LINEAR interpolates components and shortest quaternion slerp; CUBICSPLINE uses authored in/out tangents multiplied by interval duration in Hermite, then normalizes quaternion result. Tangents and intermediate quaternion polynomials are never normalized. Endpoints clamp; key times must be nonnegative/strictly increasing. Rotation keys must be unit length. Binary output shape/count must match target/path/interpolation. Inspection validates available core animation data; unsupported extension channels remain inventoried.

`morph_weights` maps integer node IDs to explicit weight arrays. `node_transforms` maps integer node IDs to local TRS or matrix fields using the authored representation. Animation/manual writes to the same property fail; defaults never imply a competing driver. Returned wire is `{timestamp,instances:[{node,mesh,primitives:[{primitive,positions:[[x,y,z],...]}]}]}`. Every primitive uses corresponding accessor vertex order; indices remain in immutable document. Output contains all mesh node instances, including those outside the default scene; callers select instance explicitly.

`export_geometry_golden` wraps evaluation with source hash/precision/coordinate/units for consumers. `reparent_local` computes `inverse(new_parent_world)*child_world`, rejects singular/sheared TRS, returns matrix. It probes child world preservation only; skin preservation requires a separate geometry check. No joint deletion is implied.

## CLI and writes

```text
python -m msf_tools check AUTHORING --pack PATH --csv PATH [--coverage PATH] [--sha256 PATH] [--write]
python -m msf_tools inspect ASSET [--resolver-root ROOT] [--sidecar JSON] [--output JSON]
python -m msf_tools annotate ASSET ANNOTATIONS --output SIDECAR
python -m msf_tools map AUTHORING MAPPING --source-profile ID --target-profile ID [--allow-approximation] [--output JSON]
python -m msf_tools evaluate AUTHORING MAPPING SAMPLES --source-profile ID --target-profile ID [--output JSON]
python -m msf_tools geometry ASSET [--time SECONDS] [--animation INDEX] [--output JSON]
```

Map/evaluate sides also accept `--source-asset/--source-sidecar` and `--target-asset/--target-sidecar`; asset and profile choice are exclusive. Optional explicit resolver root applies to assets. SAMPLES is an array or sole-key `{samples:[...]}` file. Reports are JSON on stderr; successful values stdout or atomic output files; failed operations return nonzero and may write report to an explicitly safe output destination. Invalid CLI syntax also emits a machine-readable report after argparse help text.

Check renders all pack/CSV/coverage/SHA bytes before replacement and checks expected bytes afterward. Output aliases (resolved path or hardlink) of any input asset/authoring TOML/sample/sidecar/annotation/consumed resource fail `E_OUTPUT_PATH`; explicit symlink output destinations fail. Each file is replaced atomically after fsync; there is no multi-file atomicity claim. A common output directory is owned by generation and extra files/directories fail; if outputs use different directories, extra detection is bounded to checksum manifest entries (choose a common directory for full detection). Parent paths are resolved for legitimate platform symlink prefixes. Preflight is protection against mistaken paths, not a guarantee against an adversarial process concurrently replacing directories.
