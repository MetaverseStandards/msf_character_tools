# MSF Tools

Validated signal mappings and immutable glTF inspection for Python 3.11+, with a C++ core. The package also supplies independent binary64 position evaluation for relative morph targets and linear blend skinning over every influence set, and reads USD (through usd-core) and FBX (through ufbx, compiled in) by converting them to glTF.

## Run

```sh
python3 -B -m unittest discover -s tests/public
python3 -B -m unittest discover -s tests/internal -t tests
python3 -B check.py
python3 -B -m msf_tools check examples/authoring --pack examples/generated/pack.json --csv examples/generated/survey.csv
python3 -B -m msf_tools evaluate examples/authoring wink examples/samples.json --source-profile source --target-profile target
python3 -B -m msf_tools geometry tests/public/fixtures/combined.gltf --animation 0 --time 0.5
```

The commands above run from a checkout once the C++ core is built in place (see [building](docs/building.md)); CMake finds nanobind through the interpreter, so install it there first:

```sh
python3 -m pip install nanobind==3.1.0
cmake -S . -B build/core -G Ninja -DPython_EXECUTABLE=python3 -DMSF_CORE_IN_PLACE=ON && cmake --build build/core
```

For installation in your chosen virtual environment, which compiles the core (a C++17 compiler, CMake 3.26+ and Ninja or Make):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m msf_tools --help
```

For a walkthrough that takes a real glTF, USD and FBX asset each through inspection, a sidecar binding, a mapping and posed geometry, see [examples/README.md](examples/README.md).

There are no runtime dependencies; the optional `usd` extra installs usd-core. The build backend is scikit-build-core, through `tools/build_backend.py`. The repository root supports `python -m msf_tools` without installation once the core is built in place; consumers should import an installed package or explicitly select a local tools path.

## Six public APIs

```python
from msf_tools import (
    validate_authoring, compile_pack, inspect_asset,
    compile_mapping, evaluate_mapping, annotate_asset,
)
```

Every operation returns a frozen `Result(value, report)`. `.ok` indicates success. Errors always yield `value=None`; `.report.to_dict()` gives the complete collected diagnostics and declared losses. `compile_pack` accepts only validated authoring. The [reference](docs/reference.md) specifies all six signatures, helper APIs, types, bytes and geometry conventions. Portable [JSON schemas](schemas/README.md) document the version one wire types; the Python validator additionally enforces references and numerical constraints.

## Capabilities and limits

Inspection retains original asset bytes, complete JSON, opaque attributes/extensions, and every GLB chunk. External resources remain inventory unless an explicit resolver is supplied. Sidecars bind signals to structural mesh-instance morph indices and verify source/resource hashes; annotation writes a sidecar and leaves asset bytes unchanged.

The evaluator supports positions, relative Basis morph deltas with signed weights, LBS over every JOINTS_n/WEIGHTS_n set per instance, and one explicitly selected animation with STEP, LINEAR and CUBICSPLINE sampling. It rejects unsupported required extensions, unavailable resources, singular mesh transforms and requests for other attributes. It does not establish visual, contact, calibration or universal format equivalence. The [test plan](docs/testing.md) records actual gates and tolerances.

The original [combined fixture](tests/public/fixtures/README.md) includes jaw/head deformation, wink/smile/corrective targets, an accessory joint, unknown weighted joint, two mesh instances and independent analytical goldens. Geometry tests run without completing any external signal taxonomy.

## Development and licenses

Read [CONTRIBUTING](CONTRIBUTING.md), [GOVERNANCE](GOVERNANCE.md), [NOTICE](NOTICE.md) and [public sources](docs/sources.md). Original code is MIT; original documentation, data and fixtures are CC-BY-SA-4.0. Since 0.4.0 the implementation is a C++ core, `msf_tools._core`, behind the same Python API. [Building](docs/building.md) covers the build record and tools.
