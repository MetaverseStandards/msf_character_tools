# SPDX-License-Identifier: MIT
"""Download the example assets at pinned revisions and check their SHA-256.

    python fetch_assets.py [--dest DIR]

Nothing here is committed to the repository. Fox and AnimatedMorphCube come from
Khronos glTF-Sample-Assets. The FBX character comes from Kenney's Mini
Characters pack (CC0); only that model, as FBX and as Kenney's own GLB export
(used by the tests as an independent second export), and the pack's licence
file are taken out of the downloaded zip.
"""
import argparse
import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

KHRONOS = 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/8f492390ddc7a2ae221a1369ef560589cf8c70fb/Models'
KENNEY = 'https://kenney.nl/media/pages/assets/mini-characters/bfc7e272b4-1774770718/kenney_mini-characters.zip'
FILES = {
    'Fox.glb': (f'{KHRONOS}/Fox/glTF-Binary/Fox.glb',
                'd97044e701822bac5a62696459b27d7b375aada5de8574ed4362edbba94771f7'),
    'AnimatedMorphCube.glb': (f'{KHRONOS}/AnimatedMorphCube/glTF-Binary/AnimatedMorphCube.glb',
                              '214ee56160a50dbf22543a1d66dbf860986e87f0efac3d89feac1359d0e6aeab'),
}
ARCHIVES = {
    KENNEY: ('9e1d48e6d7b8479ebbe84df71eb5bd8e1b3f0da546dea641890dccc8a02d0999', {
        'Models/FBX format/character-female-a.fbx':
            ('character-female-a.fbx', '961d8957c4ef36025b9ba1bdee13b3f0c8f860907cd1474dab74b42290e144cc'),
        'Models/GLB format/character-female-a.glb':
            ('character-female-a.glb', '8cfcff43460da8b421f2a7fdfb43ec177321cad2746db9497cbf128d5806e2a8'),
        'License.txt': ('Kenney-Mini-Characters-License.txt', '28358ae5accc85b572eb42507956afc8beae05acb4648bb9026a5714d421b785'),
    }),
}


def present(path, digest):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def download(url, digest):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(f'{url}: downloaded bytes do not match the pinned SHA-256; nothing saved')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dest', type=Path, default=Path(__file__).resolve().parent / 'assets')
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in FILES.items():
        if present(args.dest / name, digest):
            print(f'{name}: already present')
            continue
        (args.dest / name).write_bytes(download(url, digest))
        print(f'{name}: from {url}')
    for url, (digest, members) in ARCHIVES.items():
        if all(present(args.dest / name, d) for name, d in members.values()):
            print(f'{", ".join(name for name, _ in members.values())}: already present')
            continue
        with zipfile.ZipFile(io.BytesIO(download(url, digest))) as archive:
            for member, (name, member_digest) in members.items():
                data = archive.read(member)
                if hashlib.sha256(data).hexdigest() != member_digest:
                    raise SystemExit(f'{member}: does not match the pinned SHA-256; not saved')
                (args.dest / name).write_bytes(data)
                print(f'{name}: from {url}')


if __name__ == '__main__':
    main()
