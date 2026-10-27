# SPDX-License-Identifier: MIT
"""Show a skinned, animated USD rig going through msf-tools as USDA, USDC and USDZ.

For each container it inspects the rig in a separate reader process, binds the
"lift" blend shape to a signal, and prints mesh-local points at three
times. Needs usd-core. Run from the repository root:

    python -B scripts/demo_usd.py
"""
import io
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import msf_tools as m  # noqa: E402

RIG = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'source' / 'rig.usda'
SIGNAL = {'id': 'lift', 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0, 'max': 1}, 'calibration': 'literal'}


def containers():
    from pxr import Sdf
    text = RIG.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        Sdf.Layer.FindOrOpen(str(RIG)).Export(str(Path(tmp) / 'rig.usdc'))
        binary = (Path(tmp) / 'rig.usdc').read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(zipfile.ZipInfo('rig.usda'), text)
    return [('usda', text), ('usdc', binary), ('usdz', buffer.getvalue())]


def need(result):
    if not result.ok:
        sys.exit(f'msf-tools refused the rig: {result.report.to_dict()}')
    return result.value


def main():
    for fmt, data in containers():
        snapshot = need(m.inspect_asset(data, fmt, isolate=True))
        body = snapshot.source['node_paths'].index('/Rig/Body')
        binding = need(m.morph_binding(snapshot, SIGNAL, body, 0))
        sidecar = need(m.annotate_asset(snapshot, {'bindings': [binding]}))
        print(f'{fmt}: {len(data)} bytes, reader {snapshot.source["reader"]}, nodes {", ".join(snapshot.source["node_paths"])}')
        print(f'  "lift" is bound at {binding["ref"]["source_locator"]}; the sidecar has {len(sidecar.to_dict()["bindings"])} binding')
        for seconds in (0.0, 0.5, 1.0):
            pose = need(m.sample_animation(snapshot, 0, seconds))
            values = need(m.evaluate_geometry(snapshot, timestamp=seconds, animation_id=0)).to_dict()
            points = next(i for i in values['instances'] if i['node'] == body)['primitives'][0]['positions']
            weight = pose[body]['weights'][0]
            print(f'  t={seconds:.1f}s  lift weight {weight:.2f}  mesh-local points ' +
                  ' '.join('(' + ', '.join(f'{x:.3f}' for x in p) + ')' for p in points))


if __name__ == '__main__':
    main()
