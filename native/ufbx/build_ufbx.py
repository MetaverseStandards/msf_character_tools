# SPDX-License-Identifier: MIT
"""cffi build for msf_tools_ufbx._native: vendored ufbx 0.23.1 plus the msf shim."""
from pathlib import Path

from cffi import FFI

HERE = Path(__file__).resolve().parent
HEADER = (HERE / "msf_ufbx_shim.h").read_text()

ffi = FFI()
# cdef takes the declarations between the include guard and its end.
ffi.cdef(HEADER.split("#include <stdint.h>", 1)[1].rsplit("#endif", 1)[0])
ffi.set_source(
    "msf_tools_ufbx._native",
    '#include "msf_ufbx_shim.h"',
    sources=["vendor/ufbx.c", "msf_ufbx_shim.c"],
    include_dirs=[".", "vendor"],
    define_macros=[("UFBX_NO_STDIO", None), ("UFBX_NO_FORMAT_OBJ", None), ("UFBX_NO_GEOMETRY_CACHE", None),
                   ("UFBX_NO_SUBDIVISION", None), ("UFBX_NO_TESSELLATION", None)],
    extra_compile_args=["-O2"],
    py_limited_api=True,
)

if __name__ == "__main__":
    ffi.compile(verbose=False)
