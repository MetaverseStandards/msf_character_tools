# SPDX-License-Identifier: MIT
"""Source path grammar `path-sorted-v2`.

A node path is `/` followed by `/`-separated components. A component is a
source name with `%`, `/`, `#`, `[`, `]`, `:` and control characters
percent-encoded (uppercase hex), optionally followed by `[k]` to tell apart
siblings with the same name. A node path may end in `#helper:<kind>[k]` for a
reader-made helper node. A target key is one or more components joined by
`/`. A source locator is `<node path>#<target key>`, split at its last `#`.
Escaping makes every raw separator unambiguous, and nodes sort by their
unescaped components.
"""
import re

_ESCAPED = frozenset("%/#[]:" + "".join(map(chr, range(0x20))) + "\x7f")
_COMPONENT = re.compile(r"(?P<text>[^\[\]]*)(?:\[(?P<k>0|[1-9][0-9]*)\])?")
_HELPER = re.compile(r"helper:(?P<kind>geometry|scale)(?:\[(?P<k>0|[1-9][0-9]*)\])?")
HELPER_KINDS = ("geometry", "scale")


def escape(name):
    return "".join(f"%{ord(ch):02X}" if ch in _ESCAPED else ch for ch in name)


def unescape(text):
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "%":
            code = text[i + 1:i + 3]
            if not re.fullmatch("[0-9A-F]{2}", code) or chr(int(code, 16)) not in _ESCAPED:
                raise ValueError(f"Bad or unnecessary escape in {text!r}.")
            out.append(chr(int(code, 16)))
            i += 3
        elif ch in _ESCAPED:
            raise ValueError(f"Unescaped special character in {text!r}.")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _component(name, k):
    return escape(name) + ("" if k is None else f"[{k}]")


def _parse_component(text):
    match = _COMPONENT.fullmatch(text)
    if match is None:
        raise ValueError(f"Malformed path component {text!r}.")
    return unescape(match["text"]), None if match["k"] is None else int(match["k"])


def node_path(components, helper=None):
    """`components` are (name, duplicate index or None); `helper` is (kind, index or None)."""
    path = "/" + "/".join(_component(name, k) for name, k in components)
    if helper is not None:
        kind, k = helper
        if kind not in HELPER_KINDS:
            raise ValueError(f"Unknown helper kind {kind!r}.")
        path += f"#helper:{kind}" + ("" if k is None else f"[{k}]")
    return path


def parse_node_path(path):
    if type(path) is not str or not path.startswith("/"):
        raise ValueError(f"Node path must start with '/': {path!r}.")
    body, _, suffix = path.partition("#")
    helper = None
    if _:
        match = _HELPER.fullmatch(suffix)
        if match is None:
            raise ValueError(f"Malformed helper suffix in {path!r}.")
        helper = (match["kind"], None if match["k"] is None else int(match["k"]))
    return [_parse_component(c) for c in body[1:].split("/")], helper


def target_key(components):
    return "/".join(_component(name, k) for name, k in components)


def parse_target_key(key):
    if type(key) is not str:
        raise ValueError("Target key must be a string.")
    return [_parse_component(c) for c in key.split("/")]


def locator(path, key):
    return f"{path}#{key}"


def split_locator(text):
    """Split at the last `#`: target keys never contain a raw `#`, but a node path
    on a reader-made helper node ends in `#helper:<kind>`."""
    if type(text) is not str or "#" not in text:
        raise ValueError(f"Source locator needs '<node path>#<target key>': {text!r}.")
    path, _, key = text.rpartition("#")
    parse_node_path(path)
    parse_target_key(key)
    return path, key


def sort_key(path):
    components, helper = parse_node_path(path)
    return (tuple((name, -1 if k is None else k) for name, k in components),
            () if helper is None else (helper[0], -1 if helper[1] is None else helper[1]))
