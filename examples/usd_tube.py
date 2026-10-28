# SPDX-License-Identifier: MIT
"""USD example: a generated, skinned and animated tube with a blend shape, packaged as USDZ.

    python usd_tube.py [--out DIR]

Needs usd-core (pip install "msf-character-tools[usd]") for msf-character-tools' USD reader. The
tube is written by this script, so there is no asset licence to track. It
has three joints that bend it over two seconds and a "bulge" blend shape that
the mapping drives.
"""
import hashlib
import io
import math
import struct
import zipfile

from example_pipeline import arguments, run

SEGMENTS, RINGS, RADIUS, HEIGHT = 16, 13, 0.3, 3.0


def tube_usda():
    rings = [HEIGHT * r / (RINGS - 1) for r in range(RINGS)]
    points, indices, weights, bulge = [], [], [], []
    for r, y in enumerate(rings):
        lower = min(int(y), 1) if y < 2 else 2
        share = 0.0 if lower == 2 else y - lower
        for s in range(SEGMENTS):
            a = 2 * math.pi * s / SEGMENTS
            points.append((RADIUS * math.cos(a), y, RADIUS * math.sin(a)))
            indices += [lower, min(lower + 1, 2)]
            weights += [1 - share, share]
            closeness = 1 - abs(y - 1.5) / 0.8
            if closeness > 0:
                bulge.append((r * SEGMENTS + s, (0.2 * closeness * math.cos(a), 0.0, 0.2 * closeness * math.sin(a))))
    faces = [i for r in range(RINGS - 1) for s in range(SEGMENTS)
             for i in (r * SEGMENTS + s, r * SEGMENTS + (s + 1) % SEGMENTS,
                       (r + 1) * SEGMENTS + (s + 1) % SEGMENTS, (r + 1) * SEGMENTS + s)]

    def vec(values):
        return '[' + ', '.join('(' + ', '.join(f'{c:.9g}' for c in v) + ')' for v in values) + ']'

    def matrix(y):
        return f'((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, {y:g}, 0, 1))'

    def bend(degrees):
        half = math.radians(degrees) / 2
        return f'[(1, 0, 0, 0), ({math.cos(half):.9g}, 0, 0, {math.sin(half):.9g}), ({math.cos(half):.9g}, 0, 0, {math.sin(half):.9g})]'

    rotations = ', '.join(f'{code}: {bend(40 * math.sin(2 * math.pi * code / 48))}' for code in range(0, 49, 6))
    return f'''#usda 1.0
(
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
    startTimeCode = 0
    endTimeCode = 48
)

def SkelRoot "Tube"
{{
    def Skeleton "Skel" (
        prepend apiSchemas = ["SkelBindingAPI"]
    )
    {{
        uniform token[] joints = ["root", "root/mid", "root/mid/tip"]
        uniform matrix4d[] bindTransforms = [{matrix(0)}, {matrix(1)}, {matrix(2)}]
        uniform matrix4d[] restTransforms = [{matrix(0)}, {matrix(1)}, {matrix(1)}]
        rel skel:animationSource = </Tube/Skel/Bend>
        def SkelAnimation "Bend"
        {{
            uniform token[] joints = ["root", "root/mid", "root/mid/tip"]
            float3[] translations = [(0, 0, 0), (0, 1, 0), (0, 1, 0)]
            quatf[] rotations.timeSamples = {{{rotations}}}
            half3[] scales = [(1, 1, 1), (1, 1, 1), (1, 1, 1)]
        }}
    }}
    def Mesh "Body" (
        prepend apiSchemas = ["SkelBindingAPI"]
    )
    {{
        point3f[] points = {vec(points)}
        int[] faceVertexCounts = [{', '.join(['4'] * (len(faces) // 4))}]
        int[] faceVertexIndices = [{', '.join(map(str, faces))}]
        uniform token subdivisionScheme = "none"
        int[] primvars:skel:jointIndices = [{', '.join(map(str, indices))}] (
            elementSize = 2
            interpolation = "vertex"
        )
        float[] primvars:skel:jointWeights = [{', '.join(f'{w:.9g}' for w in weights)}] (
            elementSize = 2
            interpolation = "vertex"
        )
        rel skel:skeleton = </Tube/Skel>
        uniform token[] skel:blendShapes = ["bulge"]
        rel skel:blendShapeTargets = </Tube/Body/Bulge>
        def BlendShape "Bulge"
        {{
            uniform int[] pointIndices = [{', '.join(str(i) for i, _ in bulge)}]
            uniform vector3f[] offsets = {vec(o for _, o in bulge)}
        }}
    }}
}}
'''


def usdz(name, payload):
    """A one-layer USDZ: stored, not compressed, with the data padded to a 64-byte boundary and a fixed date."""
    info = zipfile.ZipInfo(name)
    padding = -(30 + len(name) + 4) % 64
    info.extra = struct.pack('<HH', 0x1986, padding) + bytes(padding)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(info, payload)
    return buffer.getvalue()


if __name__ == '__main__':
    args = arguments('usd', __doc__)
    args.out.mkdir(parents=True, exist_ok=True)
    text = tube_usda()
    (args.out / 'tube.usda').write_text(text)
    data = usdz('tube.usda', text.encode())
    (args.out / 'tube.usdz').write_bytes(data)
    asset = {'name': 'Generated tube', 'file': 'tube.usdz', 'format': 'usdz', 'sha256': hashlib.sha256(data).hexdigest(),
             'license': 'MIT', 'credit': 'Written by examples/usd_tube.py'}
    run(args, name='usd_tube', data=data, fmt='usdz', asset=asset, binding=('/Tube/Body', 0, 'bulge'),
        clips=[('bend_0.5', 0, 0.5), ('bend_1', 0, 1.0), ('bend_1.5', 0, 1.5)])
