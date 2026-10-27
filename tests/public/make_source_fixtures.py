# SPDX-License-Identifier: MIT
"""Write the synthetic USD fixtures for the strict tier (CC-BY-SA-4.0 data, MIT code).

Each case is one USDA root under tests/public/fixtures/source; the layers case also
has files under layers/. The strict-tier test makes the USDC and USDZ forms
from these at test time. Run from the repository root:

    python -B tests/public/make_source_fixtures.py
"""
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures" / "source"


def header(meters=1, up="Y", rate=None, start=None, end=None, extra=()):
    lines = [f"metersPerUnit = {meters}", f'upAxis = "{up}"', *extra]
    if rate is not None:
        lines.append(f"timeCodesPerSecond = {rate}")
    if start is not None:
        lines += [f"startTimeCode = {start}", f"endTimeCode = {end}"]
    return "#usda 1.0\n(\n" + "".join(f"    {line}\n" for line in lines) + ")\n\n"


def matrices(translations):
    return "[" + ", ".join(f"((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), ({x}, {y}, {z}, 1))"
                           for x, y, z in translations) + "]"


def mesh(name, points, counts, indices, body="", scheme='"none"', schemas=False):
    api = ' (\n    prepend apiSchemas = ["SkelBindingAPI"]\n)' if schemas else ""
    lines = [f"point3f[] points = {points}", f"int[] faceVertexCounts = {counts}", f"int[] faceVertexIndices = {indices}"]
    if scheme:
        lines.append(f"uniform token subdivisionScheme = {scheme}")
    text = f'def Mesh "{name}"{api}\n{{\n' + "".join(f"    {line}\n" for line in lines)
    return text + "".join(f"    {line}\n" for line in body.splitlines()) + "}\n"


def xform(name, ops, children="", meta=""):
    order = ", ".join('"' + op.split()[1].split(".")[0] + '"' for op in ops)
    lines = list(ops) + ([f"uniform token[] xformOpOrder = [{order}]"] if ops else [])
    opener = f'def Xform "{name}"' + (f" (\n    {meta}\n)" if meta else "")
    text = f"{opener}\n{{\n" + "".join(f"    {line}\n" for line in lines)
    return text + "".join(f"    {line}\n" for line in children.splitlines()) + "}\n"


QUAD = ("[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]", "[4]", "[0, 1, 2, 3]")
SHEAR = "((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))"
IDENTITY = "((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))"


def influences(indices, weights, size, interpolation="vertex"):
    meta = f"(\n    elementSize = {size}\n    interpolation = \"{interpolation}\"\n)"
    return (f"int[] primvars:skel:jointIndices = {indices} {meta}\n"
            f"float[] primvars:skel:jointWeights = {weights} {meta}\n")


def rig(k=1, up="Y", method=None, joints=("root", "root/arm"), binding=None, animated=True, shapes=True):
    """A skinned quad on a two-joint arm, optionally animated with a blend shape."""
    s = lambda *v: tuple(x * k for x in v)
    z = (lambda x, y, w: (x, -w, y)) if up == "Z" else (lambda x, y, w: (x, y, w))
    translations = [s(*z(0, 0, 0)), s(*z(0, 1, 0))] + [s(*z(0, 0, 0))] * (len(joints) - 2)
    anim = ""
    if animated:
        t0, t1, t2 = (s(*z(0, 1, 0)), s(*z(0, 1.5, 0)), s(*z(0.5, 1, 0)))
        axis = "(0.7071068, 0, 0, 0.7071068)" if up == "Y" else "(0.7071068, 0, -0.7071068, 0)"
        anim = (f'rel skel:animationSource = </Rig/Skel/Anim>\n'
                f'def SkelAnimation "Anim"\n{{\n    uniform token[] joints = ["root/arm"]\n'
                f'    float3[] translations.timeSamples = {{0: [{t0}], 12: [{t1}], 24: [{t2}]}}\n'
                f'    quatf[] rotations.timeSamples = {{0: [(1, 0, 0, 0)], 24: [{axis}]}}\n'
                f'    half3[] scales = [(1, 1, 1)]\n'
                + ('    uniform token[] blendShapes = ["lift"]\n    float[] blendShapeWeights.timeSamples = {0: [0], 24: [1]}\n'
                   if shapes else "") + "}\n")
    skeleton = (f'def Skeleton "Skel" (\n    prepend apiSchemas = ["SkelBindingAPI"]\n)\n{{\n'
                f'    uniform token[] joints = [{", ".join(chr(34) + j + chr(34) for j in joints)}]\n'
                f'    uniform matrix4d[] bindTransforms = {matrices(translations)}\n'
                f'    uniform matrix4d[] restTransforms = {matrices(translations)}\n'
                + "".join(f"    {line}\n" for line in anim.splitlines()) + "}\n")
    points = "[" + ", ".join(str(s(*z(*p))) for p in ((0, 0, 0), (1, 0, 0), (1, 2, 0), (0, 2, 0))) + "]"
    body = binding or influences("[0, 0, 0, 0, 1, 0, 1, 1]", "[1, 0, 1, 0, 0.5, 0.5, 1, 0]", 2)
    body += f"double3 xformOp:translate = {s(*z(5, 0, 0))}\nuniform token[] xformOpOrder = [\"xformOp:translate\"]\n"
    body += "rel skel:skeleton = </Rig/Skel>\n"
    if method:
        body += f'uniform token primvars:skel:skinningMethod = "{method}"\n'
    if shapes:
        offset = s(*z(0, 0.5, 0))
        body += (f'uniform token[] skel:blendShapes = ["lift"]\nrel skel:blendShapeTargets = </Rig/Body/Lift>\n'
                 f'def BlendShape "Lift"\n{{\n    uniform int[] pointIndices = [2]\n    uniform vector3f[] offsets = [{offset}]\n}}\n')
    body_mesh = mesh("Body", points, "[4]", "[0, 1, 2, 3]", body, schemas=True)
    return f'def SkelRoot "Rig"\n{{\n' + "".join(f"    {line}\n" for line in (skeleton + body_mesh).splitlines()) + "}\n"


EIGHT = [f"root/j{i}" for i in range(7)]


def cases():
    """Return {relative path: USDA text}."""
    out = {
        "rig.usda": header(rate=24) + rig(),
        "rig_zup_cm.usda": header(meters=0.01, up="Z", rate=24) + rig(k=100, up="Z"),
        "dual_quaternion.usda": header(rate=24) + rig(method="dualQuaternion"),
        "eight_influences.usda": header() + rig(joints=("root",) + tuple(EIGHT), animated=False, shapes=False, binding=influences(
            "[" + ", ".join(", ".join(str(j) for j in range(8)) for _ in range(4)) + "]",
            "[" + ", ".join("0.3, 0.2, 0.15, 0.1, 0.1, 0.05, 0.05, 0.05" for _ in range(4)) + "]", 8)),
        "constant_influences.usda": header() + rig(animated=False, shapes=False, binding=influences("[1]", "[1]", 1, "constant")),
        "left_handed.usda": header() + mesh("Quad", *QUAD, body='uniform token orientation = "leftHanded"'),
        "ngon_holes.usda": header() + mesh(
            "Ngon", "[(0, 0, 0), (2, 0, 0), (3, 1, 0), (1, 2, 0), (-1, 1, 0), (3, 3, 0), (4, 3, 0)]", "[5, 3, 3]",
            "[0, 1, 2, 3, 4, 2, 5, 3, 2, 6, 5]", body="int[] holeIndices = [1]"),
        "default_subdiv.usda": header() + mesh("Cage", *QUAD, scheme=None),
        "inbetween.usda": header() + mesh("Face", *QUAD, schemas=True, body=(
            'uniform token[] skel:blendShapes = ["smile"]\nrel skel:blendShapeTargets = </Face/Smile>\n'
            'def BlendShape "Smile"\n{\n    uniform vector3f[] offsets = [(0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0)]\n'
            '    uniform vector3f[] inbetweens:half = [(0, 0.25, 0), (0, 0.25, 0), (0, 0.25, 0), (0, 0.25, 0)] (\n'
            '        weight = 0.5\n    )\n}')),
        "static_leaf_shear.usda": header() + xform("Root", ["double3 xformOp:translate = (1, 2, 3)"], mesh(
            "Leaf", *QUAD, body=f"matrix4d xformOp:transform = {SHEAR}\nuniform token[] xformOpOrder = [\"xformOp:transform\"]")),
        "interior_shear.usda": header() + xform("Root", [f"matrix4d xformOp:transform = {SHEAR}"], mesh("Leaf", *QUAD)),
        "animated_shear.usda": header() + mesh("Leaf", *QUAD, body=(
            f"matrix4d xformOp:transform.timeSamples = {{0: {IDENTITY}, 1: {SHEAR}}}\n"
            'uniform token[] xformOpOrder = ["xformOp:transform"]')),
        "rotated_scaled_interior.usda": header() + xform(
            "Root", ["double3 xformOp:translate = (1, 0, 0)", "float3 xformOp:rotateXYZ = (30, 45, 60)", "float3 xformOp:scale = (2, 2, 2)"],
            xform("Arm", ["double3 xformOp:translate = (0, 1, 0)", "float3 xformOp:scale = (1, 3, 0.5)"], mesh("Quad", *QUAD))),
        "mirrored.usda": header() + xform("Root", ["float3 xformOp:rotateXYZ = (0, 30, 0)", "float3 xformOp:scale = (1, 1, -1)"],
                                          mesh("Quad", *QUAD)),
        "negative_time.usda": header(rate=24) + xform(
            "Mover", ["double3 xformOp:translate.timeSamples = {-12: (0, 0, 0), 12: (0, 3, 0)}"], mesh("Quad", *QUAD)),
        "instancing.usda": header() + "class Xform \"Proto\"\n{\n" + "".join(
            f"    {line}\n" for line in mesh("Quad", *QUAD).splitlines()) + "}\n" + "".join(
            xform(name, [f"double3 xformOp:translate = ({x}, 0, 0)"], meta="instanceable = true\n    references = </Proto>")
            for name, x in (("A", 0), ("B", 3))),
        "point_instancer.usda": header() + mesh("Quad", *QUAD) + (
            'def PointInstancer "Scatter"\n{\n    int[] protoIndices = [0, 0]\n    point3f[] positions = [(0, 0, 0), (2, 0, 0)]\n'
            '    rel prototypes = </Scatter/Protos/Dot>\n    def Scope "Protos"\n    {\n'
            '        def Sphere "Dot"\n        {\n        }\n    }\n}\n'),
        "layers.usda": header(extra=["subLayers = [@./layers/sub.usda@]"]) + xform(
            "Root", [], meta="references = @./layers/ref.usda@</Thing>") + xform("Loaded", [], meta="payload = @./layers/payload.usda@</Load>"),
        "layers/sub.usda": header() + xform("FromSub", ["double3 xformOp:translate = (0, 0, 2)"], mesh("Quad", *QUAD)),
        "layers/ref.usda": header() + xform("Thing", ["double3 xformOp:translate = (2, 0, 0)"], mesh("Quad", *QUAD)),
        "layers/payload.usda": header() + xform("Load", ["double3 xformOp:translate = (0, 2, 0)"], mesh("Quad", *QUAD)),
        "escape.usda": header(extra=["subLayers = [@../outside.usda@]"]) + xform("Root", []),
    }
    return out


def main():
    for name, text in cases().items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


if __name__ == "__main__":
    main()
