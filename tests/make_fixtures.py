# SPDX-License-Identifier: MIT
"""Original CC-BY-SA-4.0 fixture authoring and independent analytical goldens.

No evaluator imports: rotations below are direct axis equations. Run from repo root.
"""
import base64
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).parent / "fixtures"


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


class Builder:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def add(self, values, kind="VEC3", component=5126, extrema=False):
        fmt = {5126: "f", 5123: "H", 5121: "B"}[component]
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        rows = [(v,) if isinstance(v, (int,float)) else tuple(v) for v in values]
        for row in rows:
            self.data.extend(struct.pack("<" + fmt*len(row), *row))
        vi = len(self.views)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(self.data)-offset})
        a = {"bufferView": vi, "componentType": component, "type": kind, "count": len(rows)}
        if extrema:
            a["min"] = [min(r[i] for r in rows) for i in range(len(rows[0]))]
            a["max"] = [max(r[i] for r in rows) for i in range(len(rows[0]))]
        self.accessors.append(a)
        return len(self.accessors)-1


def quaternion(axis, angle):
    return [math.sin(angle/2) if i == axis else 0 for i in range(3)] + [math.cos(angle/2)]


def rotate(p, axis, angle):
    x,y,z = p
    c,s = math.cos(angle),math.sin(angle)
    return [(x,y*c-z*s,y*s+z*c), (x*c+z*s,y,-x*s+z*c), (x*c-y*s,x*s+y*c,z)][axis]


def combined():
    b = Builder()
    basis = [(-.5,1,0),(.5,1,0),(0,0,0),(-.1,1.2,.1),(.1,1.2,.1),(0,.8,.2)]
    deltas = [ [(0,-.1,0),(0,0,0),(0,0,0),(0,-.05,0),(0,0,0),(0,0,0)],
               [(-.05,.05,0),(.05,.05,0),(0,0,0),(0,0,0),(0,0,0),(0,.05,0)],
               [(0,0,.1),(0,0,.1),(0,0,0),(0,0,.02),(0,0,.02),(0,0,.05)] ]
    pos = b.add(basis, extrema=True)
    joints = b.add([(0,1,2,3)]*6,"VEC4",5123)
    weights = b.add([(.4,.3,.2,.1)]*6,"VEC4")
    indices = b.add([0,1,2,3,4,5],"SCALAR",5123)
    morphs = [b.add(d,extrema=True) for d in deltas]
    ibm = [1,0,0,0,0,1,0,0,0,0,1,0,.25,0,0,1]
    bind = b.add([ibm]*4,"MAT4")
    time = b.add([0,2],"SCALAR",extrema=True)
    outputs = [b.add([quaternion(axis,0),quaternion(axis,angle)],"VEC4")
               for axis,angle in [(2,math.pi/2),(1,math.pi/3),(0,math.pi/2)]]
    motion = b.add([(0,0,0),(.2,.1,0)],extrema=True)
    morph_out = b.add([-.5,1.5,.25,1,.5,-.5],"SCALAR",extrema=True)
    doc = {"asset":{"version":"2.0","generator":"MSF original analytical fixture"},
           "extras":{"license":"CC-BY-SA-4.0","authorship":"MSF Tools contributors", "unknown":{"keep":[1,"opaque",{"x":True}]},"fixture_version":"1"},
           "extensionsUsed":["MSF_fixture_unknown"],"extensions":{"MSF_fixture_unknown":{"opaque":"preserve"}},
           "buffers":[{"byteLength":len(b.data),"uri":"data:application/octet-stream;base64,"+base64.b64encode(b.data).decode()}],
           "bufferViews":b.views,"accessors":b.accessors,
           "nodes":[{"name":"root","children":[1,3,4,5,6]},
                    {"name":"head","children":[2]}, {"name":"jaw"},
                    {"name":"corrective accessory joint"}, {"name":"unrecognized weighted joint","extras":{"native":"opaque"}},
                    {"name":"face instance A","mesh":0,"skin":0,"translation":[.25,0,0]},
                    {"name":"face instance B","mesh":0,"skin":0,"translation":[.75,.2,0],"weights":[-.5,1.5,.25]}],
           "skins":[{"joints":[1,2,3,4],"inverseBindMatrices":bind,"skeleton":0}],
           "meshes":[{"name":"head-jaw-wink-smile-corrective","weights":[-.5,1.5,.25],
                      "extras":{"targetNames":["wink.L","smile","jawSmileCorrective"]},
                      "primitives":[{"attributes":{"POSITION":pos,"JOINTS_0":joints,"WEIGHTS_0":weights,"_CUSTOM_UNKNOWN":pos},
                                     "indices":indices,"targets":[{"POSITION":a} for a in morphs],"extras":{"artist_data":"keep"}}]}],
           "scenes":[{"nodes":[0]}],"scene":0,
           "animations":[{"name":"CombinedReference","samplers":[{"input":time,"output":o,"interpolation":"LINEAR"} for o in outputs+[motion,morph_out]],
                          "channels":[{"sampler":i,"target":{"node":node,"path":path}} for i,(node,path) in enumerate([(0,"rotation"),(1,"rotation"),(2,"rotation"),(3,"translation"),(5,"weights")])]}]}
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/"combined.gltf").write_bytes(json_bytes(doc))
    glb_doc = json.loads(json.dumps(doc))
    del glb_doc["buffers"][0]["uri"]
    jb = json_bytes(glb_doc)
    jb += b" "*((-len(jb))%4)
    binary = bytes(b.data)+b"\0"*((-len(b.data))%4)
    unknown = b"opaque!!"
    chunks = struct.pack("<II",len(jb),0x4E4F534A)+jb+struct.pack("<II",len(binary),0x004E4942)+binary+struct.pack("<II",len(unknown),0xDEADBEEF)+unknown
    (ROOT/"combined.glb").write_bytes(struct.pack("<III",0x46546C67,2,12+len(chunks))+chunks)
    golden = {"license":"CC-BY-SA-4.0","authorship":"MSF Tools contributors", "units":"metres", "coordinates":"mesh_local", "tolerance":1e-6,"samples":[]}
    for t in [0,.25,.5,1,1.5,1.75,2,3]:
        u = min(t,2)/2
        instances = []
        for ni,translation in [(5,(.25,0,0)),(6,(.75,.2,0))]:
            mw = [-.5+1.5*u,1.5-u,.25-.75*u] if ni == 5 else [-.5,1.5,.25]
            positions = []
            for p,ds in zip(basis,zip(*deltas)):
                morphed = [p[k]+sum(w*d[k] for w,d in zip(mw,ds)) for k in range(3)]
                bound = [morphed[0]+.25,morphed[1],morphed[2]]
                head = rotate(bound,1,math.pi/3*u)
                jaw = rotate(rotate(bound,0,math.pi/2*u),1,math.pi/3*u)
                accessory = [bound[0]+.2*u,bound[1]+.1*u,bound[2]]
                # Root rotation cancels through inverse(W_mesh); directly evaluate
                # the remaining four known joint equations in root coordinates.
                positions.append([sum(w*q[k] for w,q in zip([.4,.3,.2,.1],[head,jaw,accessory,bound]))-translation[k] for k in range(3)])
            instances.append({"node":ni,"positions":positions})
        golden["samples"].append({"timestamp":t,"instances":instances})
    (ROOT/"combined.analytical.json").write_bytes(json_bytes(golden))
    rest = json.loads(json.dumps(doc))
    rest["nodes"][1]["translation"]=[0,.25,0]
    (ROOT/"rest-not-bind.gltf").write_bytes(json_bytes(rest))
    eight = json.loads(json.dumps(doc))
    eight["meshes"][0]["primitives"][0]["attributes"].update({"JOINTS_1":joints,"WEIGHTS_1":weights})
    (ROOT/"eight-influence.gltf").write_bytes(json_bytes(eight))


if __name__ == "__main__":
    combined()
