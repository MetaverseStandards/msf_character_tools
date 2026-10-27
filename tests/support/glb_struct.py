# SPDX-License-Identifier: MIT
"""Read GLB accessors with struct alone, as a reference that does not use msf-tools' decoding."""
import json
import struct

_COMPONENTS = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
_WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def read_glb(data):
    """(document, binary chunk) of a GLB with a JSON chunk followed by one BIN chunk."""
    magic, version, _ = struct.unpack_from('<4sII', data, 0)
    assert magic == b'glTF' and version == 2
    length, kind = struct.unpack_from('<I4s', data, 12)
    assert kind == b'JSON'
    document = json.loads(data[20:20 + length])
    binary_length, binary_kind = struct.unpack_from('<I4s', data, 20 + length)
    assert binary_kind == b'BIN\0'
    return document, data[28 + length:28 + length + binary_length]


def accessor(document, binary, index):
    """Rows of a non-sparse, non-normalized accessor."""
    a = document['accessors'][index]
    view = document['bufferViews'][a['bufferView']]
    code, width = _COMPONENTS[a['componentType']], _WIDTHS[a['type']]
    stride = view.get('byteStride', struct.calcsize('<' + code * width))
    start = view.get('byteOffset', 0) + a.get('byteOffset', 0)
    return [struct.unpack_from('<' + code * width, binary, start + k * stride) for k in range(a['count'])]
