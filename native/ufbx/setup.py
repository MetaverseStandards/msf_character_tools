# SPDX-License-Identifier: MIT
from pathlib import Path
import sys
import sysconfig

from setuptools import setup
from setuptools.command.build_ext import build_ext

sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import GUIDANCE, missing_link_folders  # noqa: E402


class GuidedBuildExt(build_ext):
    def run(self):
        missing = missing_link_folders(sysconfig.get_config_var('LDSHARED'), sysconfig.get_config_var('LDFLAGS'))
        if missing:
            raise SystemExit(GUIDANCE + '\nMissing link folders: ' + ', '.join(missing))
        try:
            super().run()
        except Exception as exc:
            if type(exc).__name__ in ('LinkError', 'CompileError', 'DistutilsExecError', 'CCompilerError'):
                raise SystemExit(f'{GUIDANCE}\nThe build failed with: {exc}') from exc
            raise


setup(cffi_modules=["build_ufbx.py:ffi"], cmdclass={"build_ext": GuidedBuildExt})
