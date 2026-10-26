# SPDX-License-Identifier: MIT
"""A source adapter for tests: a JSON scene behind a USDA-looking header."""
import json

from msf_tools.common import digest
from msf_tools.report import Diagnostic
from msf_tools.sources import Generated, SourceParseError
from msf_tools.sources import glb, paths as source_paths

MAGIC = b'#usda 1.0\n'


def source(scene):
    return MAGIC + json.dumps(scene, sort_keys=True).encode()


def scene(**changes):
    """Root transform node, a face mesh with two targets, and one dependency."""
    base = {
        'nodes': [{'path': '/Root/Face', 'mesh': 'face'}, {'path': '/Root', 'translation': [0.0, 1.0, 0.0]}],
        'meshes': {'face': {'points': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'triangles': [0, 1, 2],
                            'targets': [['smile', [[0, 0.5, 0], [0, 0, 0], [0, 0, 0]]],
                                        ['blink', [[0, 0, 0], [0, 0, 0.25], [0, 0, 0]]]]}},
        'dependencies': ['layers/sub.usda'],
        'losses': [['W_SKIPPED', '/Root', 'Skipped 1 camera.']],
    }
    base.update(changes)
    return base


class FakeAdapter:
    """`edit` rewrites the parsed scene, standing in for a different reader version."""
    name = 'msf-fake'
    version = '1'
    formats = ('usda',)

    def __init__(self, reader_version='1', edit=None):
        self.reader_version = reader_version
        self.edit = edit

    def reader(self):
        return f'fake-reader {self.reader_version}'

    def convert(self, data, fmt, resolver, limits, options):
        if not data.startswith(MAGIC):
            raise SourceParseError('Missing fake header.')
        try:
            scene = json.loads(data[len(MAGIC):])
        except ValueError as exc:
            raise SourceParseError(f'Fake scene is not JSON: {exc}') from None
        if 'fail' in scene:
            raise SourceParseError(scene['fail'])
        if self.edit is not None:
            self.edit(scene)
        nodes = sorted(scene['nodes'], key=lambda n: source_paths.sort_key(n['path']))
        paths = [n['path'] for n in nodes]
        meshes = []
        for n in nodes:
            if 'mesh' in n and n['mesh'] not in meshes:
                meshes.append(n['mesh'])
        children = {i: [] for i in range(len(nodes))}
        for i, path in enumerate(paths):
            parent = path.rsplit('/', 1)[0]
            if parent in paths:
                children[paths.index(parent)].append(i)
        glb_nodes = tuple(glb.Node(name=path.rsplit('/', 1)[1], children=tuple(children[i]),
                                   translation=tuple(n.get('translation', (0.0, 0.0, 0.0))),
                                   mesh=meshes.index(n['mesh']) if 'mesh' in n else None)
                          for i, (path, n) in enumerate(zip(paths, nodes)))
        glb_meshes, target_keys = [], []
        for name in meshes:
            mesh = scene['meshes'][name]
            targets = mesh.get('targets', ())
            glb_meshes.append(glb.Mesh(points=tuple(map(tuple, mesh['points'])), triangles=tuple(mesh.get('triangles', ())),
                                       targets=tuple(tuple(map(tuple, offsets)) for _, offsets in targets)))
            target_keys.append(tuple(key for key, _ in targets))
        dependencies = []
        for uri in sorted(scene.get('dependencies', ())):
            payload = resolver(uri)
            dependencies.append((uri, digest(payload), len(payload)))
        losses = tuple(Diagnostic(code, 'warning' if code.startswith('W_') else 'info', ref, message, 'Review the declared loss.')
                       for code, ref, message in scene.get('losses', ()))
        return Generated(glb=glb.write_glb(glb_nodes, tuple(glb_meshes), generator=f'{self.name} {self.version}'),
                         node_paths=tuple(paths), target_keys=tuple(target_keys),
                         dependencies=tuple(dependencies), losses=losses)


def resolver(uri):
    return {'layers/sub.usda': b'#usda 1.0\n(sub layer)\n'}[uri]


ADAPTER = FakeAdapter()
