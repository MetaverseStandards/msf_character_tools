# SPDX-License-Identifier: MIT
"""Download the example assets at pinned revisions and check their SHA-256.

    python fetch_assets.py [--dest DIR]

The files are not committed to this repository. Fox and AnimatedMorphCube come
from Khronos glTF-Sample-Assets with clear licences; the FBX barbarian comes
from the ufbx test corpus, whose data files carry no licence of their own, so
it is only ever fetched for local use.
"""
import argparse
import hashlib
from pathlib import Path
import urllib.request

KHRONOS = 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/8f492390ddc7a2ae221a1369ef560589cf8c70fb/Models'
UFBX = 'https://raw.githubusercontent.com/ufbx/ufbx/26a482ae66871d7de36eb722aa060bce95bce274/data'
ASSETS = {
    'Fox.glb': (f'{KHRONOS}/Fox/glTF-Binary/Fox.glb',
                'd97044e701822bac5a62696459b27d7b375aada5de8574ed4362edbba94771f7'),
    'AnimatedMorphCube.glb': (f'{KHRONOS}/AnimatedMorphCube/glTF-Binary/AnimatedMorphCube.glb',
                              '214ee56160a50dbf22543a1d66dbf860986e87f0efac3d89feac1359d0e6aeab'),
    'blender_293_barbarian_7400_binary.fbx': (f'{UFBX}/blender_293_barbarian_7400_binary.fbx',
                                              'bd78a4fc05abe83cb3bb26e4ca649a3c5e7cb1e0c6f523fcd599e48cd0435e04'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dest', type=Path, default=Path(__file__).resolve().parent / 'assets')
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in ASSETS.items():
        path = args.dest / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            print(f'{name}: already present')
            continue
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f'{name}: downloaded bytes do not match the pinned SHA-256; not saved')
        path.write_bytes(data)
        print(f'{name}: {len(data)} bytes from {url}')


if __name__ == '__main__':
    main()
