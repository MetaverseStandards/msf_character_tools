# End-to-end examples

Each script takes real assets through all the msf-character-tools steps. It writes files that you can read or render:

1. **Inspect** the asset: nodes, meshes, skins, morph targets, clips, and any losses that the format reader declares.
2. **Annotate**: bind a signal to one morph target and write a hash-bound sidecar.
3. **Map**: compile a map with one rule (`example.target = 0.8 * example.jaw_open`) and evaluate it on three source frames.
4. **Pose**: evaluate the mesh at the rest pose, at each mapped value and at a few clip times, in world space.

| Script | Assets | What drives the mesh |
|---|---|---|
| `gltf_fox.py` | Khronos Fox and AnimatedMorphCube (GLB) | Fox: its Survey, Walk and Run clips. Cube: the map drives its `thin` morph target |
| `usd_tube.py` | A tube the script writes, packaged as USDZ | The map drives a `bulge` blend shape, and a skeleton clip bends the tube |
| `fbx_character.py` | A Kenney Mini Characters model (FBX SDK export), and AnimatedMorphCube written as FBX | Character: its `walk` clip. Cube: the map drives its `thin` shape key |

The Fox and the Kenney character have no morph targets. For each of them, the binding step is expected to fail with `E_BINDING_REFERENCE`. The script says so and continues. The map is then evaluated against the example pack's own target profile. The cubes show a successful binding.

msf-character-tools' own test FBX writer (`tests/public/make_example_fbx.py`) writes the FBX cube. The cube therefore tests the shape-key path, but it tells you nothing about how real exporters write FBX. The Kenney character is the real export.

## Set up from a clean environment

You need a standard CPython 3.11 or 3.12, from python.org, Homebrew, pyenv or uv. uv downloads a standard CPython for you. With uv, run this from the repository root:

```sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install '.[usd]'
python examples/fetch_assets.py
```

With another CPython, run `python3.12 -m venv .venv`, then `source .venv/bin/activate`, then `pip install '.[usd]'`. Then fetch the assets as above. The install compiles msf-character-tools' C++ core, FBX reader included, so you need a C++17 compiler and CMake 3.26 or newer (see `docs/building.md`). Without the `usd` extra, you can run every script except `usd_tube.py`.

`fetch_assets.py` downloads the assets at pinned revisions into `examples/assets/` and checks each SHA-256:
- Fox and AnimatedMorphCube from Khronos glTF-Sample-Assets;
- `character-female-a.fbx`, Kenney's own GLB export of the same model (the tests use it as a second, independent export) and the pack's licence file, from Kenney's Mini Characters zip.

Nothing downloaded is committed. Kenney's download link includes a dated CDN path. The link can stop working, or the pack can change so that the SHA-256 no longer matches. Then `fetch_assets.py` stops without saving anything. In that case, download Mini Characters from kenney.nl by hand. Put `character-female-a.fbx`, `character-female-a.glb` and `License.txt` (renamed `Kenney-Mini-Characters-License.txt`) in `examples/assets/`. The tests compare against the pinned hashes, so they pass only with the pinned pack.

On a corporate network that intercepts TLS, downloads fail with `CERTIFICATE_VERIFY_FAILED`. Point `SSL_CERT_FILE` at a CA bundle that includes your network's root, and run again. For example, on macOS: `export SSL_CERT_FILE=/etc/ssl/cert.pem`.

## Run

With the environment active:

```sh
python examples/gltf_fox.py
python examples/usd_tube.py
python examples/fbx_character.py
```

Each script prints one line per step and writes to `examples/out/<format>/`. Use `--out DIR` to write to a different folder, and `--assets DIR` if you fetched the assets to a different folder. The FBX run looks like this:

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
| `samples.json`, `mapping.json`, `evaluated.json` | The source frames, the compiled map and the mapped frames |
| `render/<pose>.f32` | World-space positions, little-endian float32 x, y, z per vertex, every mesh instance in one array |
| `render/mesh.u32` | Triangle indices into those positions, little-endian uint32, shared by every pose |
| `render/render.json` | A job list for the `meshrender` tool, with a camera framed on the deforming meshes. Its `credit` is repeated as each job's `caption`. It must be shown with any frame made from this file |
| `render/CREDITS.txt` | The same credit line |

Positions are in metres for USD and FBX, because the readers convert units and axes to glTF's Y-up. glTF positions keep the asset's own units. The Fox is about 100 units long. To read a pose in Python:

```python
import struct
data = open('examples/out/fbx/character/render/walk_0.25.f32', 'rb').read()
points = [struct.unpack_from('<3f', data, 12 * i) for i in range(len(data) // 12)]
```

To render PNGs with the `meshrender` tool from the visual checks, run it from inside the `render` folder: `meshrender render.json`.

## The same steps from the command line

With the environment active, the `msf-character-tools` command can make every file again, except the poses. For the glTF morph cube:

```sh
cd examples/out/gltf/morph_cube
msf-character-tools inspect ../../../assets/AnimatedMorphCube.glb --sidecar sidecar.json
msf-character-tools annotate ../../../assets/AnimatedMorphCube.glb annotations.json --output sidecar.json
msf-character-tools map authoring.toml example.drive --source-profile example.source \
    --target-asset ../../../assets/AnimatedMorphCube.glb --target-sidecar sidecar.json > mapping.json
msf-character-tools evaluate authoring.toml example.drive samples.json --source-profile example.source \
    --target-asset ../../../assets/AnimatedMorphCube.glb --target-sidecar sidecar.json > evaluated.json
msf-character-tools geometry ../../../assets/AnimatedMorphCube.glb
```

If the environment is not active, use `.venv/bin/msf-character-tools`. `geometry` prints mesh-local positions for every instance. The scripts also apply each node's world transform and the mapped morph weights.

## Asset licences

| Asset | Licence | Credit | Committed? |
|---|---|---|---|
| Fox | CC0-1.0 (model) and CC-BY-4.0 (rig, animation, conversion) | Model: PixelMannen. Rigging and animation: tomkranis. glTF conversion: @AsoboStudio and @scurest | No, fetched |
| AnimatedMorphCube | CC0-1.0 | Microsoft, 2017 | The GLB is fetched; its FBX rewrite, `data/AnimatedMorphCube.writer.fbx`, is committed |
| Kenney Mini Characters, `character-female-a.fbx` | CC0-1.0, per the `License.txt` in the pack | Kenney (www.kenney.nl); credit appreciated, not required | No, fetched |
| Generated tube | MIT, as part of this repository's code | Written by `usd_tube.py` | Generated when run |

Wherever renders of the Fox are shown, its CC-BY credits must be shown too. That is why each `render.json` carries its asset's credit. Khronos sample licences exclude logos and trademarks.

## Checks

`tests/public/test_examples.py` runs every script in a subprocess and checks the outputs against references that do not come from msf-character-tools:
- the assets' hashes, counts and licence text;
- the glTF cube's data read from the GLB with `struct`, with its target delta applied by hand;
- usd-core's own skinning of the tube;
- ufbx's own skinning of the Kenney character at each walk time, and Kenney's separate GLB export of it within 1e-3 of the bounding-box diagonal (the two exports key the clip differently);
- ufbx's own evaluation of the FBX cube with its shape key set to each mapped weight;
- the Fox against the independent Decimal oracle, when `MSF_REAL_ASSETS` is set.

It also checks that the command line rebuilds the glTF cube's files byte for byte. That check compares msf-character-tools with itself, so it is only a reproducibility check. The tests run when `MSF_EXAMPLE_ASSETS` names the folder that `fetch_assets.py` downloaded into.
