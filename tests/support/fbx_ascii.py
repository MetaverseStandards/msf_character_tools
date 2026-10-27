# SPDX-License-Identifier: MIT
"""A small FBX 7.4 ASCII writer for tests: models, meshes, skins, blend shapes and one animation stack.

Only what the FBX adapter tests need is written. Model properties follow the
FBX names (`Lcl Translation`, `RotationPivot`, `InheritType`, ...); ids are
assigned in creation order.
"""

KTIME_PER_SECOND = 46186158000


def _numbers(values):
    return ",".join(repr(float(v)) if isinstance(v, float) else str(v) for v in values)


def _array(name, values, indent):
    values = list(values)
    return f"{indent}{name}: *{len(values)} {{\n{indent}\ta: {_numbers(values)}\n{indent}}}\n"


class Scene:
    def __init__(self, unit_cm=100.0, up=1, front=2, coord=0, front_sign=1, fps=24.0):
        """`unit_cm` is FBX UnitScaleFactor (centimetres per unit); axes use FBX's index/sign convention."""
        self.objects, self.connections, self.next_id = [], [], 1000
        self.settings = {"UpAxis": up, "FrontAxis": front, "CoordAxis": coord, "FrontAxisSign": front_sign,
                         "UnitScaleFactor": unit_cm, "fps": fps}

    def _id(self):
        self.next_id += 1
        return self.next_id

    def _add(self, text, parent=None, prop=None):
        oid = self._id()
        self.objects.append(text.replace("@ID@", str(oid)))
        if parent is not None:
            self.connect(oid, parent, prop)
        return oid

    def connect(self, child, parent, prop=None):
        self.connections.append((child, parent, prop))

    def model(self, name, parent=0, kind="Null", **props):
        """props: translation, rotation (Euler degrees), scale, rotation_pivot, scaling_pivot, rotation_offset,
        scaling_offset, pre_rotation, post_rotation, rotation_order, inherit_type, geometric_translation/rotation/scaling."""
        names = {"translation": ("Lcl Translation", "Lcl Translation", "", "A"), "rotation": ("Lcl Rotation", "Lcl Rotation", "", "A"),
                 "scale": ("Lcl Scaling", "Lcl Scaling", "", "A"), "rotation_pivot": ("RotationPivot", "Vector3D", "Vector", ""),
                 "scaling_pivot": ("ScalingPivot", "Vector3D", "Vector", ""), "rotation_offset": ("RotationOffset", "Vector3D", "Vector", ""),
                 "scaling_offset": ("ScalingOffset", "Vector3D", "Vector", ""), "pre_rotation": ("PreRotation", "Vector3D", "Vector", ""),
                 "post_rotation": ("PostRotation", "Vector3D", "Vector", ""),
                 "geometric_translation": ("GeometricTranslation", "Vector3D", "Vector", ""),
                 "geometric_rotation": ("GeometricRotation", "Vector3D", "Vector", ""),
                 "geometric_scaling": ("GeometricScaling", "Vector3D", "Vector", "")}
        lines = []
        if any(k in props for k in ("pre_rotation", "post_rotation", "rotation_order")):
            lines.append('\t\t\tP: "RotationActive", "bool", "", "",1')
        if "rotation_order" in props:
            lines.append(f'\t\t\tP: "RotationOrder", "enum", "", "",{props.pop("rotation_order")}')
        if "inherit_type" in props:
            lines.append(f'\t\t\tP: "InheritType", "enum", "", "",{props.pop("inherit_type")}')
        for key, value in props.items():
            label, kind_a, kind_b, flags = names[key]
            lines.append(f'\t\t\tP: "{label}", "{kind_a}", "{kind_b}", "{flags}",{_numbers(value)}')
        body = "\t\tVersion: 232\n\t\tProperties70:  {\n" + "".join(line + "\n" for line in lines) + "\t\t}\n"
        return self._add(f'\tModel: @ID@, "Model::{name}", "{kind}" {{\n{body}\t}}\n', parent)

    def mesh(self, model, name, points, faces):
        """faces: lists of point indices; the last index of each face is written as -(i + 1)."""
        indices = [i for face in faces for i in face[:-1] + [-face[-1] - 1]]
        text = (f'\tGeometry: @ID@, "Geometry::{name}", "Mesh" {{\n' + _array("Vertices", [c for p in points for c in p], "\t\t")
                + _array("PolygonVertexIndex", indices, "\t\t") + "\t\tGeometryVersion: 124\n\t}\n")
        return self._add(text, model)

    def skin(self, geometry, clusters, skinning="Linear"):
        """clusters: (bone model id, point indices, weights, Transform 16, TransformLink 16), matrices column-major.

        As in files FBX tools write, Transform maps the mesh at bind time into bone space (the inverse
        of the bone's bind matrix times the mesh's), and TransformLink is the bone's bind matrix."""
        skin = self._add(f'\tDeformer: @ID@, "Deformer::Skin", "Skin" {{\n\t\tVersion: 101\n\t\tLink_DeformAcuracy: 50\n'
                         f'\t\tSkinningType: "{skinning}"\n\t}}\n', geometry)
        for k, (bone, indexes, weights, transform, link) in enumerate(clusters):
            text = (f'\tDeformer: @ID@, "SubDeformer::Cluster{k}", "Cluster" {{\n\t\tVersion: 100\n\t\tUserData: "", ""\n'
                    + _array("Indexes", indexes, "\t\t") + _array("Weights", [float(w) for w in weights], "\t\t")
                    + _array("Transform", [float(x) for x in transform], "\t\t")
                    + _array("TransformLink", [float(x) for x in link], "\t\t") + "\t}\n")
            cluster = self._add(text, skin)
            self.connect(bone, cluster)
        return skin

    def text(self):
        s = self.settings
        props = "".join(f'\t\tP: "{k}", "int", "Integer", "",{v}\n' for k, v in (
            ("UpAxis", s["UpAxis"]), ("UpAxisSign", 1), ("FrontAxis", s["FrontAxis"]), ("FrontAxisSign", s["FrontAxisSign"]),
            ("CoordAxis", s["CoordAxis"]), ("CoordAxisSign", 1)))
        props += f'\t\tP: "UnitScaleFactor", "double", "Number", "",{_numbers([s["UnitScaleFactor"]])}\n'
        props += '\t\tP: "TimeMode", "enum", "", "",14\n' + f'\t\tP: "CustomFrameRate", "double", "Number", "",{_numbers([s["fps"]])}\n'
        out = ("; FBX 7.4.0 project file\nFBXHeaderExtension:  {\n\tFBXHeaderVersion: 1003\n\tFBXVersion: 7400\n}\n"
               f"GlobalSettings:  {{\n\tVersion: 1000\n\tProperties70:  {{\n{props}\t}}\n}}\n"
               "Objects:  {\n" + "".join(self.objects) + "}\nConnections:  {\n")
        for child, parent, prop in self.connections:
            out += f'\tC: "OP",{child},{parent}, "{prop}"\n' if prop else f'\tC: "OO",{child},{parent}\n'
        return (out + "}\n").encode()
