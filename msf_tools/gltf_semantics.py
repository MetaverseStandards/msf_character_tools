# SPDX-License-Identifier: MIT
"""Selected glTF 2.0 core semantics, independent of POSITION evaluation capability.

Unknown semantics/resources remain inventory. This is not a full glTF validator.
"""
from collections.abc import Mapping
from decimal import Decimal
import json
import re
import struct

from .common import parse_json, number
from .report import fail

INDEXED = ('TEXCOORD', 'COLOR', 'JOINTS', 'WEIGHTS')
CORE_PATHS = ('translation', 'rotation', 'scale', 'weights')


def parse_document(raw):
    """Normalize only core integer slots; retain opaque values and original bytes.

    Decimal parsing prevents lexical fractions rounded to an integer by binary64
    from being admitted at integer slots. The ordinary parser checks JSON limits,
    duplicate keys and finiteness first.
    """
    doc = parse_json(raw)
    exact = json.loads(raw, parse_float=Decimal)

    def field(obj, original, key, ref):
        if key not in obj:
            return
        value = original[key]
        if type(value) is int:
            obj[key] = value
        elif isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
            obj[key] = int(value)
        else:
            fail('E_TYPE', ref + '/' + key, 'Core glTF integer field must have an exact integral numeric value.')

    def array(obj, original, key, ref):
        if isinstance(obj.get(key), list):
            for i in range(len(obj[key])):
                holder = {'value': obj[key][i]}
                field(holder, {'value': original[key][i]}, 'value', ref + '/' + key + '/' + str(i))
                obj[key][i] = holder['value']

    if not isinstance(doc, Mapping):
        return doc

    def objects(name):
        # Leave malformed containers for the structural validator's precise ref.
        value = doc.get(name)
        return value if isinstance(value, list) else ()

    field(doc, exact, 'scene', '')
    slots = {'buffers': ('byteLength',), 'bufferViews': ('buffer','byteOffset','byteLength','byteStride','target'),
             'accessors': ('bufferView','byteOffset','componentType','count'),
             'nodes': ('camera','skin','mesh'), 'skins': ('inverseBindMatrices','skeleton'),
             'images': ('bufferView',), 'textures': ('sampler','source'),
             'samplers': ('magFilter','minFilter','wrapS','wrapT')}
    for name, fields in slots.items():
        if not isinstance(doc.get(name), list):
            continue
        for i, obj in enumerate(doc[name]):
            if not isinstance(obj, Mapping):
                continue
            original = exact[name][i]; ref = f'/{name}/{i}'
            for key in fields:
                field(obj, original, key, ref)
            if name == 'nodes':
                array(obj, original, 'children', ref)
            if name == 'skins':
                array(obj, original, 'joints', ref)
            if name == 'accessors' and obj.get('componentType') in (5120,5121,5122,5123,5125):
                for key in ('min', 'max'):
                    if not isinstance(obj.get(key), list):
                        continue
                    for k, value in enumerate(original[key]):
                        if isinstance(value, Decimal):
                            if value != value.to_integral_value():
                                fail('E_ACCESSOR_DOMAIN', ref, 'Integer bounds must be raw integral component values.')
                            obj[key][k] = int(value)
            if name == 'accessors' and isinstance(obj.get('sparse'), Mapping):
                sp, orig = obj['sparse'], original['sparse']
                field(sp, orig, 'count', ref + '/sparse')
                for key in ('indices','values'):
                    if isinstance(sp.get(key), Mapping):
                        for slot in ('bufferView','byteOffset','componentType'):
                            field(sp[key], orig[key], slot, ref + '/sparse/' + key)
    for i, scene in enumerate(objects('scenes')):
        if isinstance(scene, Mapping):
            array(scene, exact['scenes'][i], 'nodes', f'/scenes/{i}')
    for i, mesh in enumerate(objects('meshes')):
        if not isinstance(mesh, Mapping) or not isinstance(mesh.get('primitives'), list):
            continue
        for j, p in enumerate(mesh['primitives']):
            if not isinstance(p, Mapping):
                continue
            original = exact['meshes'][i]['primitives'][j]; ref = f'/meshes/{i}/primitives/{j}'
            for key in ('indices','material','mode'):
                field(p, original, key, ref)
            if isinstance(p.get('attributes'), Mapping):
                for key in p['attributes']:
                    field(p['attributes'], original['attributes'], key, ref + '/attributes')
            if isinstance(p.get('targets'), list):
                for k, target in enumerate(p['targets']):
                    if isinstance(target, Mapping):
                        for key in target:
                            field(target, original['targets'][k], key, ref + f'/targets/{k}')
    for i, anim in enumerate(objects('animations')):
        if not isinstance(anim, Mapping):
            continue
        for name, fields in (('samplers',('input','output')), ('channels',('sampler',))):
            if not isinstance(anim.get(name), list):
                continue
            for j, item in enumerate(anim[name]):
                if not isinstance(item, Mapping):
                    continue
                original = exact['animations'][i][name][j]; ref = f'/animations/{i}/{name}/{j}'
                for key in fields:
                    field(item, original, key, ref)
                if name == 'channels' and isinstance(item.get('target'), Mapping):
                    field(item['target'], original['target'], 'node', ref + '/target')
    for i, mat in enumerate(objects('materials')):
        if not isinstance(mat, Mapping):
            continue
        original = exact['materials'][i]
        infos = [(mat, original, key, f'/materials/{i}') for key in ('normalTexture','occlusionTexture','emissiveTexture')]
        if isinstance(mat.get('pbrMetallicRoughness'), Mapping):
            pbr = mat['pbrMetallicRoughness']; orig = original['pbrMetallicRoughness']
            infos += [(pbr, orig, key, f'/materials/{i}/pbrMetallicRoughness') for key in ('baseColorTexture','metallicRoughnessTexture')]
        for obj, orig, key, ref in infos:
            if isinstance(obj.get(key), Mapping):
                for slot in ('index','texCoord'):
                    field(obj[key], orig[key], slot, ref + '/' + key)
    return doc


def morph_count(mesh):
    """Common positive target count; primitives without targets have zero deltas."""
    counts = {len(p.get('targets', ())) for p in mesh['primitives'] if p.get('targets')}
    if len(counts) > 1:
        fail('E_MORPH', '/meshes', 'Positive morph target counts must agree across primitives.')
    return next(iter(counts), 0)


def semantic_type(name, a, count, ref, *, morph=False, base=None):
    family = name
    for prefix in INDEXED:
        if name.startswith(prefix + '_'):
            suffix = name[len(prefix)+1:]
            if not re.fullmatch(r'(?:0|[1-9][0-9]{0,8})', suffix):
                fail('E_ATTRIBUTE_SEMANTIC', ref, 'Indexed attribute suffix must be decimal 0..999999999 without leading zeros.')
            family = prefix
            break
    if a.get('count') != count:
        fail('E_MORPH' if morph else 'E_GEOMETRY_TYPE', ref, 'Attribute count must match primitive vertex count.')
    shapes = {'POSITION': ('VEC3',), 'NORMAL': ('VEC3',), 'TANGENT': ('VEC3',) if morph else ('VEC4',),
              'TEXCOORD': ('VEC2',), 'COLOR': ('VEC3','VEC4'), 'JOINTS': ('VEC4',), 'WEIGHTS': ('VEC4',)}
    if family not in shapes:
        return
    normalized = a.get('normalized', False); ct = a.get('componentType')
    if family == 'JOINTS' and not morph:
        component_ok = ct in (5121,5123) and normalized is False
    elif family in ('TEXCOORD','COLOR','WEIGHTS'):
        integers = (5120,5121,5122,5123) if morph and family != 'WEIGHTS' else (5121,5123)
        component_ok = ct == 5126 and normalized is False or ct in integers and normalized is True
    else:
        component_ok = ct == 5126 and normalized is False
    if morph and family in ('JOINTS','WEIGHTS'):
        component_ok = False
    if not component_ok or a.get('type') not in shapes[family] or morph and family == 'COLOR' and a.get('type') != base.get('type'):
        fail('E_MORPH' if morph else 'E_GEOMETRY_TYPE', ref, 'Core attribute component type, shape or normalization is incompatible with its semantic.')
    if family == 'POSITION' and ('min' not in a or 'max' not in a):
        fail('E_ACCESSOR_BOUNDS', ref, 'POSITION accessors require min and max bounds.')


def validate_meshes(doc, lookup):
    accessors = doc.get('accessors', ())
    for mi, mesh in enumerate(doc.get('meshes', ())):
        primitives = mesh.get('primitives')
        if not isinstance(primitives, (list,tuple)) or not primitives:
            fail('E_MESH', f'/meshes/{mi}', 'Mesh needs nonempty primitives.')
        for pi, p in enumerate(primitives):
            ref = f'/meshes/{mi}/primitives/{pi}'
            if not isinstance(p, Mapping) or not isinstance(p.get('attributes'), Mapping) or not p['attributes']:
                fail('E_MESH', ref, 'Primitive needs nonempty attributes.')
            attrs = p['attributes']; first = lookup(next(iter(attrs.values())), accessors, ref)
            count = first.get('count'); indexed = {prefix: set() for prefix in INDEXED}
            for name, aid in attrs.items():
                a = lookup(aid, accessors, ref + '/attributes/' + name)
                semantic_type(name, a, count, ref + '/attributes/' + name)
                for prefix in INDEXED:
                    if name.startswith(prefix + '_'):
                        indexed[prefix].add(int(name[len(prefix)+1:]))
            for values in indexed.values():
                if values and (min(values) != 0 or max(values) != len(values)-1):
                    fail('E_ATTRIBUTE_SEMANTIC', ref, 'Indexed attribute sets must be contiguous from zero.')
            if indexed['JOINTS'] != indexed['WEIGHTS']:
                fail('E_ATTRIBUTE_SEMANTIC', ref, 'JOINTS and WEIGHTS sets must be paired.')
            vertices = lookup(p['indices'], accessors, ref).get('count') if 'indices' in p else count
            mode = p.get('mode',4)
            if type(mode) is not int or mode not in range(7):
                fail('E_PRIMITIVE_MODE', ref, 'Invalid primitive mode.')
            if type(vertices) is int and vertices > 0:
                if mode == 1 and vertices % 2 or mode == 4 and vertices % 3 or mode in (2,3) and vertices < 2 or mode in (5,6) and vertices < 3:
                    fail('E_PRIMITIVE_COUNT', ref, 'Primitive vertex count is incompatible with topology mode.')
            targets = p.get('targets', ())
            if 'targets' in p and (not isinstance(targets, (list,tuple)) or not targets):
                fail('E_MORPH', ref, 'Authored targets array must be nonempty.')
            for ti, target in enumerate(targets):
                if not isinstance(target, Mapping) or not target:
                    fail('E_MORPH', ref, 'Morph target must be a nonempty attribute object.')
                for name, aid in target.items():
                    if name not in attrs:
                        fail('E_MORPH', ref, 'Morph semantic must have a corresponding base attribute.')
                    a = lookup(aid, accessors, ref)
                    semantic_type(name, a, count, ref + f'/targets/{ti}/{name}', morph=True, base=lookup(attrs[name],accessors,ref))
        morph_count(mesh)


def animation_layout(doc, sampler, target, lookup, ref):
    """Validate known target layout even when its bytes have not been resolved."""
    node = lookup(target['node'],doc.get('nodes',()),ref)
    path = target['path']; times = lookup(sampler['input'],doc.get('accessors',()),ref)
    a = lookup(sampler['output'],doc.get('accessors',()),ref)
    count = morph_count(doc['meshes'][node['mesh']]) if path == 'weights' and 'mesh' in node else 4 if path == 'rotation' else 3
    if path == 'weights' and ('mesh' not in node or count == 0):
        fail('E_ANIMATION',ref,'Weights target needs a mesh with morph targets.')
    interpolation = sampler.get('interpolation','LINEAR'); factor = 3 if interpolation == 'CUBICSPLINE' else 1
    expected = 'SCALAR' if path == 'weights' else 'VEC4' if path == 'rotation' else 'VEC3'
    component_ok = a['componentType'] == 5126 and not a.get('normalized',False)
    if path in ('rotation','weights'):
        component_ok |= a['componentType'] in (5120,5121,5122,5123) and a.get('normalized',False) is True
    if not component_ok or a['type'] != expected or a['count'] != times['count'] * factor * (count if path == 'weights' else 1) or factor == 3 and times['count'] < 2:
        fail('E_ANIMATION_TYPE',ref,'Animation component type, shape, output count or cubic key count disagrees with target.')
    return count


def validate_skin_hierarchy(doc, parents):
    nodes = doc.get('nodes',())
    def chain(node):
        result = [node]
        while node in parents:
            node = parents[node]; result.append(node)
        return result
    for si, skin in enumerate(doc.get('skins',())):
        chains = [chain(j) for j in skin['joints']]
        common = set(chains[0]).intersection(*chains[1:])
        if not common:
            fail('E_SKIN',f'/skins/{si}','Skin joints must have a common root.')
        root = next(j for j in chains[0] if j in common)
        if 'skeleton' in skin and skin['skeleton'] not in chain(root):
            fail('E_SKIN',f'/skins/{si}','Skeleton must be common root or its ancestor.')
        for scene in doc.get('scenes',()):
            roots = set(scene.get('nodes',()))
            if any(n.get('skin') == si and roots.intersection(chain(i)) for i,n in enumerate(nodes)) and not roots.intersection(chain(root)):
                fail('E_SKIN',f'/skins/{si}','Common joint root must belong to every scene referencing this skin.')


def validate_bounds(a, rows, ref):
    ct = a['componentType']
    for name, op in (('min',min),('max',max)):
        if name not in a:
            continue
        bound = a[name]
        if ct == 5126:
            try:
                bound = tuple(struct.unpack('<f',struct.pack('<f',v))[0] for v in bound)
            except (OverflowError,struct.error):
                fail('E_ACCESSOR_DOMAIN',ref,'Accessor bounds cannot be represented by component type.')
            if not all(number(v) for v in bound):
                fail('E_ACCESSOR_DOMAIN',ref,'Accessor bounds overflow component type.')
        else:
            lo, hi = {5120:(-128,127),5121:(0,255),5122:(-32768,32767),5123:(0,65535),5125:(0,4294967295)}[ct]
            if any(v != int(v) or not lo <= v <= hi for v in bound):
                fail('E_ACCESSOR_DOMAIN',ref,'Integer bounds must be raw integral component values.')
        if rows is not None and tuple(bound) != tuple(op(row[k] for row in rows) for k in range(len(bound))):
            fail('E_ACCESSOR_DOMAIN',ref,'Declared bounds must exactly match component-rounded extrema after sparse overrides.')


def validate_binary(snapshot, decode):
    """Check each available primitive and every IBM row; unresolved data stays unknown."""
    from .report import Fault
    errors = []
    def attempt(fn):
        try:
            fn()
        except Fault as exc:
            if exc.diagnostic.code != 'E_RESOURCE_UNAVAILABLE':
                errors.append(exc.diagnostic)
    doc = snapshot.document
    for mi,mesh in enumerate(doc.get('meshes',())):
        for pi,p in enumerate(mesh['primitives']):
            ref = f'/meshes/{mi}/primitives/{pi}'; attrs = p['attributes']
            def indices():
                if 'indices' in p:
                    a = doc['accessors'][p['indices']]; count = doc['accessors'][next(iter(attrs.values()))]['count']
                    maximum = {5121:255,5123:65535,5125:4294967295}[a['componentType']]
                    if any(i >= count or i == maximum for (i,) in decode(snapshot,p['indices'])):
                        fail('E_INDEX_BOUNDS',ref,'Index must reference a vertex and must not equal reserved component maximum.')
            attempt(indices)
            for name,aid in attrs.items():
                def attribute():
                    rows = decode(snapshot,aid)
                    if name == 'TANGENT' and any(abs(r[3]) != 1 for r in rows):
                        fail('E_TANGENT',ref,'TANGENT W must be exactly -1 or +1.')
                    if name == 'COLOR_0' and any(not 0 <= x <= 1 for r in rows for x in r):
                        fail('E_COLOR',ref,'COLOR_0 components must be in [0,1].')
                attempt(attribute)
            def influences():
                sets = sorted(int(name[7:]) for name in attrs if name.startswith('JOINTS_'))
                if not sets:
                    return
                def available(aid, *, raw=False):
                    try:
                        return decode(snapshot, aid, raw=raw)
                    except Fault as exc:
                        if exc.diagnostic.code != 'E_RESOURCE_UNAVAILABLE':
                            raise
                        return None
                weights = [available(attrs[f'WEIGHTS_{s}']) for s in sets]
                weight_types = [doc['accessors'][attrs[f'WEIGHTS_{s}']]['componentType'] for s in sets]
                raw_weights = [available(attrs[f'WEIGHTS_{s}'], raw=True) for s in sets]
                for rows in weights:
                    if rows is not None and any(w < 0 for row in rows for w in row):
                        fail('E_SKIN_WEIGHTS',ref,'Skin weights must be nonnegative.')
                joints = [available(attrs[f'JOINTS_{s}']) for s in sets]
                palettes = [len(doc['skins'][n['skin']]['joints']) for n in doc.get('nodes',()) if n.get('mesh') == mi and 'skin' in n]
                count = doc['accessors'][next(iter(attrs.values()))]['count']
                for vi in range(count):
                    for rows in joints:
                        if rows is not None and any(j >= size for size in palettes for j in rows[vi]):
                            fail('E_JOINT_BOUNDS',ref,'Joint index exceeds referencing skin palette.')
                    positive = [j for js,ws in zip(joints,weights) if js is not None and ws is not None for j,w in zip(js[vi],ws[vi]) if w > 0]
                    if len(set(positive)) != len(positive):
                        fail('E_SKIN_WEIGHTS',ref,'A vertex must not have duplicate positive joint weights.')
                    if all(rows is not None for rows in weights):
                        if len(set(weight_types)) == 1 and weight_types[0] in (5121,5123):
                            total = sum(w for rows in raw_weights for w in rows[vi]); expected = 255 if weight_types[0] == 5121 else 65535
                            valid = total == expected
                        else:
                            valid = abs(sum(w for rows in weights for w in rows[vi])-1) <= 1e-6
                        if not valid:
                            fail('E_SKIN_WEIGHTS',ref,'Weight sum violates raw integer or project floating sum policy; no implicit normalization.')
            attempt(influences)
    for si,skin in enumerate(doc.get('skins',())):
        def ibms():
            if 'inverseBindMatrices' in skin:
                for row in decode(snapshot,skin['inverseBindMatrices']):
                    if tuple(row[3::4]) != (0,0,0,1):
                        fail('E_SKIN_TYPE',f'/skins/{si}','Every inverse bind matrix including extras must have affine fourth row [0,0,0,1].')
        attempt(ibms)
    return errors
