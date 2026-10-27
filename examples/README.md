# End-to-end examples

Each script takes real assets through the whole msf-tools chain and writes files you can read or render:

1. **Inspect** the asset: nodes, meshes, skins, morph targets, clips and any declared losses from the format reader.
2. **Annotate**: bind a signal to one morph target and write a hash-bound sidecar.
3. **Map**: compile a one-rule mapping (`example.target = 0.8 * example.jaw_open`) and evaluate it on three source frames.
4. **Pose**: evaluate the mesh at the rest pose, at each mapped value and at a few clip times, in world space.

| Script | Assets | What drives the mesh |
|---|---|---|
| `gltf_fox.py` | Khronos Fox and AnimatedMorphCube (GLB) | Fox: its Survey, Walk and Run clips. Cube: the mapping drives its `thin` morph target |
| `usd_tube.py` | A tube the script writes, packaged as USDZ | The mapping drives a `bulge` blend shape; a skeleton clip bends the tube |
| `fbx_character.py` | A Kenney Mini Characters model (FBX SDK export), and AnimatedMorphCube written as FBX | Character: its `walk` clip. Cube: the mapping drives its `thin` shape key |

The Fox and the Kenney character have no morph targets. For each of them the binding step is expected to fail with `E_BINDING_REFERENCE`, and the script says so and carries on. The mapping is then evaluated against the example pack's own target profile. The cubes show a successful binding.

The FBX cube is written by msf-tools' own test FBX writer (`tests/make_example_fbx.py`), so it exercises the shape-key path but says nothing about how real exporters write FBX. The Kenney character is the real export.

## Set up from a clean environment

You need a standard CPython 3.11 or 3.12: from python.org, Homebrew, pyenv, or uv. The FBX reader is a small compiled extension. Meta's system `python3` cannot build it, because its link settings point at a toolchain that only exists inside buck; the install stops with a message saying so. With uv, which downloads a standard CPython for you, run this from the repository root:

```sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install ./native/ufbx '.[usd,fbx]'
python examples/fetch_assets.py
```

With another CPython, run `python3.12 -m venv .venv`, then `source .venv/bin/activate`, then `pip install ./native/ufbx '.[usd,fbx]'`, then fetch the assets as above. `./native/ufbx` is listed because the `fbx` extra needs `msf-tools-ufbx`, which is built from this repository rather than downloaded. If you only want glTF, `pip install .` is enough and `gltf_fox.py` is the only script you can run.

`fetch_assets.py` downloads the assets at pinned revisions into `examples/assets/` and checks each SHA-256:
- Fox and AnimatedMorphCube from Khronos glTF-Sample-Assets;
- `character-female-a.fbx`, Kenney's own GLB export of the same model (the tests use it as a second, independent export) and the pack's licence file, from Kenney's Mini Characters zip.

Nothing downloaded is committed. On a corporate network that intercepts TLS, downloads fail with `CERTIFICATE_VERIFY_FAILED`. Point `SSL_CERT_FILE` at a CA bundle that includes your network's root, for example `export SSL_CERT_FILE=/etc/ssl/cert.pem` on macOS, and rerun.

## Run

With the environment active:

```sh
python examples/gltf_fox.py
python examples/usd_tube.py
python examples/fbx_character.py
```

Each script prints one line per step and writes to `examples/out/<format>/`. Use `--out DIR` to write somewhere else and `--assets DIR` if you fetched the assets elsewhere. The FBX run looks like this:

```
[fbx_character] inspected character-female-a.fbx: 10 nodes, 3 declared losses
[fbx_character] no morph target to bind: E_BINDING_REFERENCE Binding does not address a mesh-instance morph target.
[fbx_character] mapped example.jaw_open [0.0, 0.5, 1.0] to example.target [0.0, 0.4, 0.8]
[fbx_character] posed 4 times: 553 vertices, 876 triangles each
[fbx_morph_cube] inspected data/AnimatedMorphCube.writer.fbx: 1 nodes, 0 declared losses
[fbx_morph_cube] bound example.target to node 0 (/AnimatedMorphCube) morph target 0 (thin)
```

## Outputs

| File | Contents |
|---|---|
| `summary.json` | The asset with its licence and credit, the inspection summary with declared losses, the binding (or why it was refused), the mapped values, and one entry per pose |
| `poses.csv` | One row per pose: how it was made, vertex and triangle counts, world-space bounds |
| `authoring.toml` | The example pack: two signals, two profiles and the one rule |
| `annotations.json`, `sidecar.json` | The input to `annotate_asset` and the sidecar it wrote |
| `samples.json`, `mapping.json`, `evaluated.json` | The source frames, the compiled mapping and the mapped frames |
| `render/<pose>.f32` | World-space positions, little-endian float32 x, y, z per vertex, every mesh instance in one array |
| `render/mesh.u32` | Triangle indices into those positions, little-endian uint32, shared by every pose |
| `render/render.json` | A job list for the `meshrender` tool, with a camera framed on the deforming meshes. Its `credit`, repeated as each job's `caption`, must be shown with any frame made from it |
| `render/CREDITS.txt` | The same credit line |

Positions are in metres for USD and FBX (the readers convert units and axes to glTF's Y-up). glTF positions keep the asset's own units; the Fox is about 100 units long. To read a pose in Python:

```python
import struct
data = open('examples/out/fbx/character/render/walk_0.25.f32', 'rb').read()
points = [struct.unpack_from('<3f', data, 12 * i) for i in range(len(data) // 12)]
```

To render PNGs with the `meshrender` tool from the visual checks, run it from inside the `render` folder: `meshrender render.json`.

## The same steps from the command line

With the environment active, every file except the poses can be made again with the `msf-tools` command. For the glTF morph cube:

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

Without activating, use `.venv/bin/msf-tools`. `geometry` prints mesh-local positions for every instance; the scripts add each node's world transform and the mapped morph weights.

## Asset licences

| Asset | Licence | Credit | Committed? |
|---|---|---|---|
| Fox | CC0-1.0 (model) and CC-BY-4.0 (rig, animation, conversion) | Model: PixelMannen. Rigging and animation: tomkranis. glTF conversion: @AsoboStudio and @scurest | No, fetched |
| AnimatedMorphCube | CC0-1.0 | Microsoft, 2017 | The GLB is fetched; its FBX rewrite, `data/AnimatedMorphCube.writer.fbx`, is committed |
| Kenney Mini Characters, `character-female-a.fbx` | CC0-1.0, per the `License.txt` in the pack | Kenney (www.kenney.nl); credit appreciated, not required | No, fetched |
| Generated tube | MIT, as part of this repository's code | Written by `usd_tube.py` | Generated when run |

The Fox's CC-BY credits must be shown wherever renders of it are shown, which is why each `render.json` carries its asset's credit. Khronos sample licences exclude logos and trademarks.

## Checks

`tests/test_examples.py` runs every script in a subprocess and checks the outputs against references that do not come from msf-tools:
- the assets' hashes, counts and licence text;
- the glTF cube's data read from the GLB with `struct`, with its target delta applied by hand;
- usd-core's own skinning of the tube;
- ufbx's own skinning of the Kenney character at each walk time, and Kenney's separate GLB export of it within 1e-3 of the bounding-box diagonal (the two exports key the clip differently);
- ufbx's own evaluation of the FBX cube with its shape key set to each mapped weight;
- the Fox against the independent Decimal oracle, when `MSF_REAL_ASSETS` is set.

It also checks that the command line rebuilds the glTF cube's files byte for byte. That one compares msf-tools with itself, so it is only a reproducibility check. The tests run when `MSF_EXAMPLE_ASSETS` names the folder `fetch_assets.py` downloaded into. `scripts/ci_local.sh` runs them when `$MSF/_viz/assets/examples` exists.
