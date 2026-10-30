# MSF Character Tools

MSF Character Tools validates signal mappings and inspects glTF assets into immutable snapshots. It runs on Python 3.11 and later, with a C++ core. It also gives an independent binary64 evaluation of vertex positions, for relative morph targets and for linear blend skinning over every influence set. It reads USD (through usd-core) and FBX (through ufbx, which is compiled in) by converting them to glTF. The repository is https://github.com/MetaverseStandards/msf_character_tools. Its [v0.6.0 release](https://github.com/MetaverseStandards/msf_character_tools/releases/tag/v0.6.0) has wheels for macOS arm64 and for Linux x86_64 and aarch64 (manylinux_2_28). There is one wheel for CPython 3.11 and one abi3 wheel for CPython 3.12 and later.

## Run

```sh
python3 -B -m unittest discover -s tests/public
python3 -B -m unittest discover -s tests/internal -t tests
python3 -B check.py
python3 -B -m msf_character_tools check examples/authoring --pack examples/generated/pack.json --csv examples/generated/survey.csv
python3 -B -m msf_character_tools evaluate examples/authoring wink examples/samples.json --source-profile source --target-profile target
python3 -B -m msf_character_tools geometry tests/public/fixtures/combined.gltf --animation 0 --time 0.5
```

These commands run from a checkout (`git clone https://github.com/MetaverseStandards/msf_character_tools`) after you build the C++ core in place (see [building](docs/building.md)). CMake finds nanobind through the interpreter, so install nanobind into that interpreter first:

```sh
python3 -m pip install nanobind==3.1.0
cmake -S . -B build/core -G Ninja -DPython_EXECUTABLE=python3 -DMSF_CORE_IN_PLACE=ON && cmake --build build/core
```

To install a release, download the wheel for your platform and Python, and `SHA256SUMS`, from the [v0.6.0 release](https://github.com/MetaverseStandards/msf_character_tools/releases/tag/v0.6.0). Check the wheel's hash, then install it with `python -m pip install`. [AGENTS.md](AGENTS.md#install) shows an install pinned by the hash.

To install from a checkout into a virtual environment of your choice, use the commands below. The install compiles the core, so you need a C++17 compiler, CMake 3.26 or newer, and Ninja or Make.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m msf_character_tools --help
```

[examples/README.md](examples/README.md) is a walkthrough. It takes a real glTF, USD and FBX asset through inspection, a sidecar binding, a map and posed geometry.

There are no runtime dependencies. The optional `usd` extra installs usd-core. The build backend is scikit-build-core, through `tools/build_backend.py`. After an in-place core build, `python -m msf_character_tools` works from the repository root without installation. Other programs that use msf-character-tools should import an installed package, or select a local tools path explicitly.

## Six public APIs

```python
from msf_character_tools import (
    validate_authoring, compile_pack, inspect_asset,
    compile_mapping, evaluate_mapping, annotate_asset,
)
```

These six are the main operations. `msf_character_tools.__all__` has 29 public names in all: the six operations, plus helpers (such as `load_authoring` and `LocalResolver`) and the result and record types.

Words used in this documentation: a *mapping* is one rule (one entry of a map's `rules`). A *map* is a named group of rules: one `[[mappings]]` entry, selected by `mapping_id`. `compile_mapping` compiles one map, and `evaluate_mapping` runs the compiled map on samples. With `partial=True`, a bad or missing input stops only the outputs that depend on it (see [partial evaluation](docs/reference.md#partial-evaluation)).

Every operation returns a frozen `Result(value, report)`. `.ok` tells you if the operation succeeded. When there is an error, `value` is always `None`. `.report.to_dict()` gives all the diagnostics collected and all the declared losses. `compile_pack` accepts only validated authoring. The [reference](docs/reference.md) gives all six signatures, the helper APIs, the types, the byte formats and the geometry conventions. Portable [JSON schemas](schemas/README.md) describe the version 1 wire types. Validation at run time also checks references and numeric constraints.

## Capabilities and limits

Inspection keeps the original asset bytes, the complete JSON, unknown attributes and extensions, and every GLB chunk. External resources are only listed, unless you supply a resolver. A sidecar binds signals to morph target indices of a mesh instance, by structure, and checks the hashes of the source and its resources. Annotation writes a sidecar and does not change the asset bytes.

The evaluator supports these features:
- positions;
- relative Basis morph deltas, with signed weights;
- LBS over every `JOINTS_n`/`WEIGHTS_n` set of each instance;
- one animation that you select, with STEP, LINEAR and CUBICSPLINE sampling.

It refuses unsupported required extensions, unavailable resources, singular mesh transforms and requests for other attributes. It does not show visual, contact or calibration equivalence, or that formats are equivalent in general. The [test plan](docs/testing.md) records the gates and tolerances that run.

The original [combined fixture](tests/public/fixtures/README.md) has jaw and head deformation, wink, smile and corrective targets, an accessory joint, an unknown weighted joint, two mesh instances and independent analytical goldens. The geometry tests do not need a complete external signal taxonomy.

## Development and licences

Read [CONTRIBUTING](CONTRIBUTING.md), [GOVERNANCE](GOVERNANCE.md), [NOTICE](NOTICE.md) and [public sources](docs/sources.md). Coding agents should read [AGENTS.md](AGENTS.md). Original code is MIT. Original documentation, data and fixtures are CC-BY-SA-4.0. Since 0.4.0, the implementation is a C++ core (now `msf_character_tools._core`) behind the same Python API. [Building](docs/building.md) describes the build record and the build tools.
