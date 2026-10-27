# SPDX-License-Identifier: MIT
"""Read an FBX file's GlobalSettings properties straight from its bytes, without ufbx or msf-tools."""
import re
import struct

_SCALARS = {b'Y': 'h', b'C': '?', b'I': 'i', b'F': 'f', b'D': 'd', b'L': 'q'}


def _properties(data, at, count, e):
    values = []
    for _ in range(count):
        kind = data[at:at + 1]
        at += 1
        if kind in _SCALARS:
            values.append(struct.unpack_from(e + _SCALARS[kind], data, at)[0])
            at += struct.calcsize(e + _SCALARS[kind])
        elif kind in (b'S', b'R'):
            (length,) = struct.unpack_from(e + 'I', data, at)
            values.append(data[at + 4:at + 4 + length])
            at += 4 + length
        else:  # arrays: count, encoding, byte length, then the (possibly deflated) bytes
            length = struct.unpack_from(e + 'III', data, at)[2]
            values.append(None)
            at += 12 + length
    return values


def _binary(data):
    e = '>' if data[22] else '<'  # the byte after the magic's 0x1A flags big-endian files
    wide = struct.unpack_from(e + 'I', data, 23)[0] >= 7500
    header = e + ('QQQB' if wide else 'IIIB')
    size = struct.calcsize(header)

    def nodes(at, end):
        while at < end:
            stop, count, _, name_length = struct.unpack_from(header, data, at)
            if stop == 0:
                return
            name = data[at + size:at + size + name_length]
            yield name, at + size + name_length, count, stop
            at = stop

    def settings_in(first, stop):
        for inner, start, inner_count, inner_stop in nodes(first, stop):
            if inner in (b'Properties70', b'Properties60'):
                found = {}
                for prop, p_start, p_count, _ in nodes(start + _skip(data, start, inner_count, e), inner_stop):
                    if prop in (b'P', b'Property'):
                        values = _properties(data, p_start, p_count, e)
                        found[values[0].decode('utf-8', 'replace')] = values[-1]
                return found
        return {}

    # FBX 7 keeps GlobalSettings at the top level; FBX 6 keeps it inside Objects.
    for name, first, count, stop in nodes(27, len(data)):
        start = first + _skip(data, first, count, e)
        if name == b'GlobalSettings':
            return settings_in(start, stop)
        if name == b'Objects':
            for inner, inner_first, inner_count, inner_stop in nodes(start, stop):
                if inner == b'GlobalSettings':
                    return settings_in(inner_first + _skip(data, inner_first, inner_count, e), inner_stop)
    return {}


def _skip(data, at, count, e):
    """Byte length of a node's property list."""
    end = at
    for _ in range(count):
        kind = data[end:end + 1]
        end += 1
        if kind in _SCALARS:
            end += struct.calcsize(e + _SCALARS[kind])
        elif kind in (b'S', b'R'):
            end += 4 + struct.unpack_from(e + 'I', data, end)[0]
        else:
            end += 12 + struct.unpack_from(e + 'III', data, end)[2]
    return end - at


def global_settings(data):
    """{property name: value} from GlobalSettings/Properties70; empty when the file has none."""
    if data.startswith(b'Kaydara FBX Binary'):
        return _binary(data)
    text = data.decode('utf-8', 'replace')
    block = re.search(r'GlobalSettings:\s*\{.*?Properties[67]0:\s*\{(.*?)\n\s*\}', text, re.S)
    settings = {}
    for name, value in re.findall(r'(?:P|Property):\s*"([^"]+)",\s*"[^"]*",\s*"[^"]*",(?:\s*"[^"]*",)?\s*([^\n]*)', block.group(1) if block else ''):
        value = value.strip().split(',')[-1].strip().strip('"')
        try:
            settings[name] = float(value) if '.' in value or 'e' in value.lower() else int(value)
        except ValueError:
            settings[name] = value
    return settings


_AXES = {0: (1, 0, 0), 1: (0, 1, 0), 2: (0, 0, 1)}


def axes_and_unit(data):
    """The rotation (rows: right, up, front as file-space unit vectors) that ufbx's conversion to right-handed
    +Y up applies, or None when an axis is missing, and metres per file unit (UnitScaleFactor x 0.01, default 0.01)."""
    s = global_settings(data)

    def axis(name, sign):
        index = int(s.get(name, 3))
        if index not in _AXES:
            return None
        return tuple(c * (1 if int(s.get(sign, 2)) > 0 else -1) for c in _AXES[index])

    right, up, front = axis('CoordAxis', 'CoordAxisSign'), axis('UpAxis', 'UpAxisSign'), axis('FrontAxis', 'FrontAxisSign')
    rotation = (right, up, front) if None not in (right, up, front) else None
    return rotation, float(s.get('UnitScaleFactor', 1.0)) * 0.01
