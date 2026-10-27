# End-to-end examples

Each script takes one asset through the whole msf-tools chain and writes files you can read or render:

1. **Inspect** the asset: nodes, meshes, skins, morph targets, clips and any declared losses from the format reader.
2. **Annotate**: bind a signal to one morph target and write a hash-bound sidecar.
3. **Map**: compile a one-rule mapping (`example.target = 0.8 * example.jaw_open`) and evaluate it on three source frames.
4. **Pose**: evaluate the mesh at the rest pose, at each mapped value and at a few clip times, in world space.

| Script | Asset | Format | What drives the mesh |
|---|---|---|---|
| `gltf_fox.py` | Khronos Fox, and AnimatedMorphCube | GLB | Fox: its Survey, Walk and Run clips (it has no morph targets, so the binding is refused). Cube: the mapping drives its `thin` target |
| `usd_tube.py` | A tube the script writes, packaged as USDZ | USDZ | The mapping drives a `bulge` blend shape; a skeleton clip bends the tube |
| `fbx_barbarian.py` | Blender barbarian from the ufbx test corpus | FBX | The mapping drives the `Mouth` shape key; the character's clip gives the animated poses |

## Set up from a clean environment

From the repository root, with Python 3.11 or newer and a C compiler (the FBX reader is a small compiled extension):

```sh
python3 -m venv .venv
.venv/bin/pip install ./native/ufbx '.[usd,fbx]'
.venv/bin/python examples/fetch_assets.py
```

`./native/ufbx` is listed first because the `fbx` extra needs `msf-tools-ufbx`, which is built from this repository rather than downloaded. If you only want glTF, `pip install .` is enough and `gltf_fox.py` is the only script you can run.

`fetch_assets.py` downloads the three asset files at pinned revisions into `examples/assets/` and checks each SHA-256. Nothing is committed. The USD tube needs no download.

## Run

```sh
.venv/bin/python examples/gltf_fox.py
.venv/bin/python examples/usd_tube.py
.venv/bin/python examples/fbx_barbarian.py
```

Each script prints one line per step and writes to `examples/out/<format>/`. Use `--out DIR` to write somewhere else and `--assets DIR` if you fetched the assets elsewhere. The FBX run looks like this:

```
[fbx_barbarian] inspected blender_293_barbarian_7400_binary.fbx: 71 nodes, 5 declared losses
[fbx_barbarian] bound example.target to node 34 (/body) morph target 0 (Mouth)
[fbx_barbarian] mapped example.jaw_open [0.0, 0.5, 1.0] to example.target [0.0, 0.4, 0.8]
[fbx_barbarian] posed 7 times: 1828 vertices, 3285 triangles each
```

## Outputs

| File | Contents |
|---|---|
| `summary.json` | The asset and its licence, the inspection summary with declared losses, the binding (or why it was refused), the mapped values, and one entry per pose |
| `poses.csv` | One row per pose: how it was made, vertex and triangle counts, world-space bounds |
| `authoring.toml` | The example pack: two signals, two profiles and the one rule |
| `annotations.json`, `sidecar.json` | The input to `annotate_asset` and the sidecar it wrote |
| `samples.json`, `mapping.json`, `evaluated.json` | The source frames, the compiled mapping and the mapped frames |
| `render/<pose>.f32` | World-space positions, little-endian float32 x, y, z per vertex, every mesh instance in one array |
| `render/mesh.u32` | Triangle indices into those positions, little-endian uint32, shared by every pose |
| `render/render.json` | A job list for the `meshrender` tool, with a camera framed on the deforming meshes |

Positions are in metres for USD and FBX (the readers convert units and axes to glTF's Y-up). glTF positions keep the asset's own units; the Fox is about 100 units long. To read a pose in Python:

```python
import struct
data = open('examples/out/fbx/render/jaw_open_1.f32', 'rb').read()
points = [struct.unpack_from('<3f', data, 12 * i) for i in range(len(data) // 12)]
```

To render PNGs with the `meshrender` tool from the visual checks, run it from inside the `render` folder: `meshrender render.json`.

## The same steps from the command line

Every file except the poses can be made again with the `msf-tools` command. For the morph cube:

```sh
cd examples/out/gltf/morph_cube
msf-tools inspect ../../../assets/AnimatedMorphCube.glb --sidecar sidecar.json
msf-tools annotate ../../../assets/AnimatedMorphCube.glb annotations.json --output sidecar.json
msf-tools map authoring.toml example.drive --source-profile example.source \
    --target-asset ../../../assets/AnimatedMorphCube.glb --target-sidecar sidecar.json > mapping.json
msf-tools evaluate authoring.toml example.drive samples.json --source-profile example.source \
    --target-asset ../../../assets/AnimatedMorphCube.glb --target-sidecar sidecar.json > evaluated.json
msf-tools geometry ../../../assets/AnimatedMorphCube.glb
```

`geometry` prints mesh-local positions for every instance; the scripts add each node's world transform and the mapped morph weights.

## Asset licences

| Asset | Licence | Credit | Committed? |
|---|---|---|---|
| Fox | CC0-1.0 (model) and CC-BY-4.0 (rig, animation, conversion) | Model: PixelMannen. Rigging and animation: tomkranis. glTF conversion: @AsoboStudio and @scurest | No, fetched |
| AnimatedMorphCube | CC0-1.0 | Microsoft, 2017 | No, fetched |
| Barbarian (`blender_293_barbarian_7400_binary.fbx`) | Not stated. The ufbx code is MIT or public domain, but its test data files carry no licence or author of their own | ufbx test corpus | No: fetched for local use only |
| Generated tube | MIT, as part of this repository's code | Written by `usd_tube.py` | Generated when run |

The CC-BY credits above must be shown wherever renders of the Fox are shown. Khronos sample licences exclude logos and trademarks.

## Checks

`tests/test_examples.py` runs every script in a subprocess and checks the outputs against facts that do not come from msf-tools:
- the assets' hashes and counts;
- the morph cube's target delta applied by hand;
- usd-core's own skinning of the tube;
- the barbarian's shape key responding linearly to the mapped weight;
- the Fox against the independent Decimal oracle, when `MSF_REAL_ASSETS` is set;
- the command line rebuilding the morph cube's files byte for byte.

It runs when `MSF_EXAMPLE_ASSETS` names the folder `fetch_assets.py` downloaded into. `scripts/ci_local.sh` runs it when `$MSF/_viz/assets/examples` exists.
