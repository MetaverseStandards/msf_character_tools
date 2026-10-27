# SPDX-License-Identifier: MIT
"""The ufbx C shim through cffi; skipped when msf-tools-ufbx is not installed."""
import importlib.util
import unittest

HAVE_UFBX = importlib.util.find_spec('msf_tools_ufbx') is not None

MINIMAL = b'''; FBX 7.4.0 project file
FBXHeaderExtension:  {
	FBXHeaderVersion: 1003
	FBXVersion: 7400
}
Objects:  {
	Model: 1, "Model::Root", "Null" {
	}
}
Connections:  {
	C: "OO",1,0
}
'''


def open_scene(data, memory_limit=0, allocation_limit=0):
    """Return (handle, error text); the handle is closed by the caller."""
    from msf_tools_ufbx import ffi, lib
    limits = ffi.new('msf_fbx_limits *', {'memory_limit': memory_limit, 'allocation_limit': allocation_limit})
    out = ffi.new('msf_fbx **')
    err = ffi.new('char[512]')
    ok = lib.msf_fbx_open(ffi.from_buffer(data), len(data), limits, out, err, 512)
    return (out[0] if ok else None), ffi.string(err).decode('utf-8', 'replace')


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class UfbxShim(unittest.TestCase):
    def test_open_reports_scene_counts(self):
        from msf_tools_ufbx import ffi, lib
        handle, err = open_scene(MINIMAL)
        self.assertIsNotNone(handle, err)
        try:
            info = ffi.new('msf_fbx_info *')
            self.assertEqual(lib.msf_fbx_info_get(handle, info), 1)
            self.assertEqual((info.nodes, info.meshes, info.anim_stacks, info.ascii, info.version), (1, 0, 0, 1, 7400))
        finally:
            lib.msf_fbx_close(handle)

    def test_unreadable_input_and_memory_limits_are_errors(self):
        handle, err = open_scene(b'this is not an FBX file at all')
        self.assertIsNone(handle)
        self.assertTrue(err)
        handle, err = open_scene(MINIMAL, memory_limit=4096)
        self.assertIsNone(handle)
        self.assertIn('memory', err.lower())


if __name__ == '__main__':
    unittest.main()
