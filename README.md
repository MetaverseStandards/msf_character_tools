# MSF Tools

Python 3.11+ standard library reference for validated signal mappings and immutable glTF inspection. The package also supplies independent binary64 position evaluation for relative morph targets and conventional four influence linear blend skinning.

## Run

```sh
python3 -B -m unittest discover -s tests
python3 -B check.py
python3 -B -m msf_tools check examples/authoring --pack examples/generated/pack.json --csv examples/generated/survey.csv
python3 -B -m msf_tools evaluate examples/authoring wink examples/samples.json --source-profile source --target-profile target
python3 -B -m msf_tools geometry tests/fixtures/combined.gltf --animation 0 --time 0.5
```

For installation in your chosen virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m msf_tools --help
```

There are no runtime dependencies. Setuptools is the installation build backend. The repository root supports `python -m msf_tools` without installation; consumers should import an installed package or explicitly select a local tools path.

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

The evaluator supports positions, relative Basis morph deltas with signed weights, four influence LBS per instance, and one explicitly selected animation with STEP, LINEAR and CUBICSPLINE sampling. It rejects unsupported required extensions, eight influences, unavailable resources, singular mesh transforms and requests for other attributes. It does not establish visual, contact, calibration or universal format equivalence. The [test plan](docs/testing.md) records actual gates and tolerances.

The original [combined fixture](tests/fixtures/README.md) includes jaw/head deformation, wink/smile/corrective targets, an accessory joint, unknown weighted joint, two mesh instances and independent analytical goldens. Geometry tests run without completing any external signal taxonomy.

## Development and licenses

Read [CONTRIBUTING](CONTRIBUTING.md), [GOVERNANCE](GOVERNANCE.md), [NOTICE](NOTICE.md) and [public sources](docs/sources.md). Original code is MIT; original documentation, data and fixtures are CC-BY-SA-4.0. Native modules and build integration have their own numerical and ownership gates described in their documentation.
