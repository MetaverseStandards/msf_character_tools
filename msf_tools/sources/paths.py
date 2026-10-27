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

Implemented in the C++ core (core/src/paths.cpp).
"""
from .. import _native

_core = _native.required()
HELPER_KINDS = ("geometry", "scale")
_MESSAGES = {"escape": "Bad or unnecessary escape in {!r}.", "unescaped": "Unescaped special character in {!r}.",
             "component": "Malformed path component {!r}.", "start": "Node path must start with '/': {!r}.",
             "helper": "Malformed helper suffix in {!r}."}


def _call(fn, *args):
    try:
        return fn(*args)
    except _core.PathError as exc:
        kind, text = exc.args
        raise ValueError(_MESSAGES[kind].format(text)) from None


def _index(k):
    return None if k is None else int(k)


def _text(k):
    return None if k is None else f"{k}"


def escape(name):
    return _core._paths_escape(name)


def unescape(text):
    return _call(_core._paths_unescape, text)


def node_path(components, helper=None):
    """`components` are (name, duplicate index or None); `helper` is (kind, index or None)."""
    if helper is not None:
        kind, k = helper
        if kind not in HELPER_KINDS:
            raise ValueError(f"Unknown helper kind {kind!r}.")
        helper = (kind, _text(k))
    return _core._paths_node_path([(name, _text(k)) for name, k in components], helper)


def parse_node_path(path):
    if type(path) is not str or not path.startswith("/"):
        raise ValueError(f"Node path must start with '/': {path!r}.")
    components, helper = _call(_core._paths_parse_node_path, path)
    return [(name, _index(k)) for name, k in components], None if helper is None else (helper[0], _index(helper[1]))


def target_key(components):
    return _core._paths_target_key([(name, _text(k)) for name, k in components])


def parse_target_key(key):
    if type(key) is not str:
        raise ValueError("Target key must be a string.")
    return [(name, _index(k)) for name, k in _call(_core._paths_parse_target_key, key)]


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
