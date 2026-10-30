#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# The CI run: what .github/workflows/check.yml (dormant) would run, on local Python 3.11 and 3.12
# environments, then print a summary block for a pull-request description.
# Interpreters are MSF_PY311 / MSF_PY312, by default python3.11 and python3.12 on
# PATH. MSF names an optional local workspace: with it set, the interpreters
# default to $MSF/_tools/venv3.11 and venv3.12, cmake, ninja and uv come from
# $MSF/_tools, the 0.3.0 oracle from $MSF/_tools/oracle-venv, RCEF from $MSF/RCEF
# and the asset tiers from $MSF/_viz/assets. Each optional input also has its own
# variable (see docs/testing.md); tiers whose inputs are absent are skipped.
#
#   --gate      add the gate tier: 10^7 floats against repr, wider JSON fuzzing,
#               and RCEF's JSON goldens (MSF_RCEF_ROOT, MSF_RCEF_COMMIT)
#   --sanitize  rebuild the core with ASan and UBSan, run the core and public
#               suites on it, then restore the normal build
#   --fuzz      run scripts/fuzz.sh, libFuzzer on the core's parsers, for
#               MSF_FUZZ_SECONDS (default 300) per harness
set -u
cd "$(dirname "$0")/.." || exit 2
gate=0
sanitize=0
fuzz=0
for arg in "$@"; do
  case "$arg" in
    --gate) gate=1 ;;
    --sanitize) sanitize=1 ;;
    --fuzz) fuzz=1 ;;
    *) echo "usage: scripts/ci_local.sh [--gate] [--sanitize] [--fuzz]" >&2; exit 2 ;;
  esac
done
MSF="${MSF:-}"
failed=0
lines=()

seconds() { python3 -c 'import sys, time; print(f"{time.time() - float(sys.argv[1]):.1f}")' "$1"; }

# interpreter VERSION: MSF_PY3xx, else the workspace venv, else pythonX.Y on PATH.
interpreter() {
  local var="MSF_PY${1/./}"
  if [ -n "${!var:-}" ]; then echo "${!var}"
  elif [ -n "$MSF" ]; then echo "$MSF/_tools/venv$1/bin/python"
  else command -v "python$1" || echo "python$1"
  fi
}
# workspace SUBPATH: $MSF/SUBPATH in a workspace, else nothing.
workspace() { [ -n "$MSF" ] && echo "$MSF/$1"; }

if [ -n "$MSF" ]; then
  uv="${UV:-$MSF/_tools/boot/bin/uv}"
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$MSF/_tools/uv-cache}"
  export PATH="$MSF/_tools/bin:$PATH"
else
  uv="${UV:-$(command -v uv)}"
fi

# Build the C++ core in place for each Python, then require it in the suites.
for version in 3.11 3.12; do
  py=$(interpreter $version)
  [ -x "$py" ] || continue
  start=$(python3 -c 'import time; print(time.time())')
  if cmake -S . -B "build/core-$version" -G Ninja -DPython_EXECUTABLE="$py" -DMSF_CORE_IN_PLACE=ON >/dev/null 2>&1 \
      && cmake --build "build/core-$version" >/dev/null 2>&1 \
      && MSF_TOOLS_PURE= "$py" -B -c 'from msf_character_tools import _native; assert _native.core'; then
    lines+=("- C++ core for Python $version: built in place and loaded in $(seconds "$start") s")
  else
    lines+=("- C++ core for Python $version: BUILD OR LOAD FAILED (cmake -S . -B build/core-$version -DMSF_CORE_IN_PLACE=ON)")
    failed=1
  fi
done
# Differential tests against the 0.3.0 oracle (MSF_ORACLE_PYTHON) skip without it, except in a
# workspace, where a missing oracle fails them; MSF_REQUIRE_ORACLE overrides either way.
[ -n "$MSF" ] && export MSF_ORACLE_PYTHON="${MSF_ORACLE_PYTHON:-$MSF/_tools/oracle-venv/bin/python}"
if [ -n "$MSF" ]; then export MSF_REQUIRE_ORACLE="${MSF_REQUIRE_ORACLE-1}"; else export MSF_REQUIRE_ORACLE="${MSF_REQUIRE_ORACLE-0}"; fi
if [ -n "${MSF_ORACLE_PYTHON:-}" ] && [ -x "$MSF_ORACLE_PYTHON" ]; then
  lines+=("- Oracle: msf-tools 0.3.0 at $MSF_ORACLE_PYTHON")
elif [ "$MSF_REQUIRE_ORACLE" = 1 ]; then
  lines+=("- Oracle: MISSING at ${MSF_ORACLE_PYTHON:-(MSF_ORACLE_PYTHON unset)}, and MSF_REQUIRE_ORACLE=1")
else
  lines+=("- Oracle: not found, so the differential tests skip (set MSF_ORACLE_PYTHON to a Python with msf-tools 0.3.0)")
fi
# 0.3.0 iterated sets of channel IDs; with one seed here and in the oracle, both sides order them alike.
export PYTHONHASHSEED="${PYTHONHASHSEED-0}"

# unittest prints "Ran N tests" and OK/FAILED last; without them the run died part way.
verdict_of() {
  if ! printf '%s\n' "$1" | grep -qE '^Ran '; then echo "CRASHED (no unittest summary, exit $2)"; return; fi
  printf '%s\n' "$1" | grep -E '^(OK|FAILED)' | tail -1
}

# tests/public is the gate a reimplementation must keep passing unchanged; tests/internal covers private modules.
# suites PYTHON PUBLIC_PATTERN INTERNAL_PATTERN runs the public and/or internal suite and prints both outputs.
suites() {
  local status=0
  if [ -n "$2" ]; then "$1" -B -m unittest discover -s tests/public -p "$2" 2>&1 || status=1; fi
  if [ -n "$3" ]; then "$1" -B -m unittest discover -s tests/internal -t tests -p "$3" 2>&1 || status=1; fi
  return $status
}
ran_of() { printf '%s\n' "$1" | grep -E '^Ran ' | awk '{n += $2} END {print n + 0}'; }
skipped_of() { printf '%s\n' "$1" | grep -oE 'skipped=[0-9]+' | awk -F= '{n += $2} END {print n + 0}'; }
# tier NAME STATUS OUTPUT [RUNS] adds the summary line for an optional tier.
tier() {
  if [ "$2" -eq 0 ] && [ "$(printf '%s\n' "$3" | grep -cE '^Ran ')" -eq "${4:-1}" ]; then
    lines+=("- $1: $(ran_of "$3") tests OK (skipped=$(skipped_of "$3"))")
  else
    lines+=("- $1: FAILED")
    printf '%s\n' "$3" | grep -E '^(FAIL|ERROR):' >&2
    failed=1
  fi
}

# A missing or broken reader fails the suites instead of skipping their tests: FBX is compiled
# in, so always; USD (usd-core, the usd extra) in a workspace, or when MSF_REQUIRE_FORMATS says so.
if [ -n "$MSF" ]; then export MSF_REQUIRE_FORMATS="${MSF_REQUIRE_FORMATS-fbx,usd}"; else export MSF_REQUIRE_FORMATS="${MSF_REQUIRE_FORMATS-fbx}"; fi

interpreters=0
for version in 3.11 3.12; do
  py=$(interpreter $version)
  if [ ! -x "$py" ]; then
    lines+=("- Python $version: SKIPPED (no interpreter at $py)")
    continue
  fi
  interpreters=$((interpreters + 1))
  exact=$("$py" -c 'import platform; print(platform.python_version())')
  summary=()
  for suite in public internal; do
    start=$(python3 -c 'import time; print(time.time())')
    if [ $suite = public ]; then output=$(suites "$py" 'test*.py' '' 2>&1); else output=$(suites "$py" '' 'test*.py' 2>&1); fi
    status=$?
    took=$(seconds "$start")
    ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
    verdict=$(verdict_of "$output" $status)
    if [ $status -ne 0 ] || [ "${verdict#CRASHED}" != "$verdict" ]; then
      failed=1
      printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    fi
    summary+=("$suite ${ran:-?} tests, ${verdict} in ${took} s")
  done
  if "$py" -B check.py >/dev/null 2>&1; then check="check.py OK"; else check="check.py FAILED"; failed=1; fi
  lines+=("- Python $exact: unittest ${summary[0]}; ${summary[1]}; $check")
done
if [ $interpreters -eq 0 ]; then
  lines+=("- Suites: FAILED (no Python 3.11 or 3.12 found; set MSF_PY311 or MSF_PY312)")
  failed=1
fi

py312=$(interpreter 3.12)
if [ -x "$py312" ]; then
  if unexercised=$(PYTHONPATH=.:tests "$py312" -B tests/internal/test_diagnostics_registry.py 2>&1); then
    lines+=("- Diagnostics registry: $unexercised")
  else
    lines+=("- Diagnostics registry: listing FAILED")
  fi
fi

# The core's exact paths alone, without its fast paths, must still pass the public gate.
if [ -x "$py312" ]; then
  output=$(MSF_TOOLS_PURE=1 suites "$py312" 'test*.py' '')
  tier "Public suite without the fast paths (MSF_TOOLS_PURE=1, Python 3.12)" $? "$output"
fi

# Gate tier (--gate): the G1 checks too slow for the fast suite.
if [ $gate -eq 1 ] && [ -x "$py312" ]; then
  for version in 3.11 3.12; do
    py=$(interpreter $version)
    [ -x "$py" ] || continue
    start=$(python3 -c 'import time; print(time.time())')
    output=$(MSF_GATE=1 suites "$py" '' 'test_core_*.py')
    tier "Gate tier, Python $version (10^7 floats vs repr, JSON and Unicode fuzzing, RCEF ${MSF_RCEF_COMMIT:-96ac4be} goldens and authoring, 10^6 hypot vectors per arity, 5000 random maps in partial evaluation; vs the oracle: 10^5 math3d cases, 2x10^4 authoring documents, 600 fragment directories, 2x10^4 mappings with samples, 10^4 glTF assets, 2x10^4 each of node paths, matrices, influence sets and GLB scenes; $(seconds "$start") s)" $? "$output"
  done
else
  lines+=("- Gate tier: SKIPPED (scripts/ci_local.sh --gate)")
fi

# Sanitizer tier (--sanitize). Isolated source readers start a worker with a
# cleared environment, which cannot load the ASan runtime, so their one public
# test is left out here. MSF_SANITIZE_CC / MSF_SANITIZE_CXX choose the compiler
# (for example a clang where the system compiler's libasan is not installed);
# the runtime preloaded into Python is that compiler's.
if [ $sanitize -eq 1 ] && [ -x "$py312" ]; then
  san_cc="${MSF_SANITIZE_CC:-cc}"
  compilers=()
  asan_dir=build/core-asan-3.12
  # A build directory per compiler: CMake will not switch compilers in an existing one.
  [ -n "${MSF_SANITIZE_CC:-}" ] && compilers=(-DCMAKE_C_COMPILER="$MSF_SANITIZE_CC" -DCMAKE_CXX_COMPILER="${MSF_SANITIZE_CXX:-c++}") \
    && asan_dir=build/core-asan-$(basename "$MSF_SANITIZE_CC")-3.12
  case "$(uname -s)" in
    Darwin) preload=(DYLD_INSERT_LIBRARIES="$(clang -print-file-name=libclang_rt.asan_osx_dynamic.dylib)") ;;
    *) if "$san_cc" --version 2>/dev/null | grep -q clang; then
         preload=(LD_PRELOAD="$("$san_cc" --print-runtime-dir)/libclang_rt.asan.so")
       else
         preload=(LD_PRELOAD="$("$san_cc" -print-file-name=libasan.so)")
       fi ;;
  esac
  if cmake -S . -B "$asan_dir" -G Ninja -DPython_EXECUTABLE="$py312" -DMSF_SANITIZE=ON -DMSF_CORE_IN_PLACE=ON ${compilers[@]+"${compilers[@]}"} >/dev/null 2>&1 \
      && cmake --build "$asan_dir" >/dev/null 2>&1; then
    output=$(env "${preload[@]}" ASAN_OPTIONS=detect_leaks=0:strip_env=0 UBSAN_OPTIONS=print_stacktrace=1 "$py312" -B - <<'PY' 2>&1
import sys, unittest
sys.path[:0] = ['tests', 'tests/public']
loader = unittest.defaultTestLoader
def flat(suite):
    for test in suite:
        yield from flat(test) if isinstance(test, unittest.TestSuite) else [test]
tests = [t for t in flat(loader.discover('tests/public', top_level_dir='tests/public')) if 'isolated_reader' not in t.id()]
for pattern in ('test_core*.py', 'test_record_integrity_internal.py', 'test_diagnostics_registry.py',
                'test_source_fbx_native.py', 'test_source_fbx_internal.py'):
    tests += list(flat(loader.discover('tests/internal', pattern=pattern, top_level_dir='tests')))
result = unittest.TextTestRunner(verbosity=0).run(unittest.TestSuite(tests))
sys.exit(not result.wasSuccessful())
PY
)
    tier "Sanitizer tier (ASan + UBSan core with ufbx; public suite less 1 isolated-worker test, core, record and FBX tests)" $? "$output"
  else
    lines+=("- Sanitizer tier: BUILD FAILED (cmake -S . -B $asan_dir -DMSF_SANITIZE=ON)")
    failed=1
  fi
  # Restore the normal 3.12 build. Copy only the newest extension: an older build directory can
  # still hold a version-specific one, which Python would load in preference to abi3.
  newest=$(ls -t build/core-3.12/_core.*.so 2>/dev/null | head -1)
  rm -f msf_character_tools/_core.abi3.so msf_character_tools/_core.cpython-312-*.so
  { [ -n "$newest" ] && cmake -E copy "$newest" msf_character_tools/; } >/dev/null 2>&1 || cmake --build build/core-3.12 >/dev/null 2>&1
else
  lines+=("- Sanitizer tier: SKIPPED (scripts/ci_local.sh --sanitize)")
fi

# Fuzz tier (--fuzz).
if [ $fuzz -eq 1 ]; then
  if output=$(scripts/fuzz.sh "${MSF_FUZZ_SECONDS:-300}" 2>&1); then
    lines+=("- Fuzz tier (libFuzzer, ASan + UBSan, ${MSF_FUZZ_SECONDS:-300} s per harness): $(printf '%s' "$output" | tr '\n' ';' | sed 's/;$//; s/;/; /g')")
  else
    lines+=("- Fuzz tier: FAILED: $(printf '%s' "$output" | tr '\n' ' ')")
    failed=1
  fi
else
  lines+=("- Fuzz tier: SKIPPED (scripts/ci_local.sh --fuzz)")
fi

# Optional tier on OpenUSD's own sample assets, kept out of the fast suite.
openusd="${MSF_OPENUSD_ASSETS:-$(workspace _viz/assets/openusd)}"
if [ -n "$openusd" ] && [ -f "$openusd/LICENSE.txt" ] && [ -x "$py312" ]; then
  output=$(MSF_OPENUSD_ASSETS="$openusd" suites "$py312" test_source_openusd.py '')
  tier "OpenUSD assets tier" $? "$output"
else
  lines+=("- OpenUSD assets tier: SKIPPED (no assets at ${openusd:-MSF_OPENUSD_ASSETS})")
fi

# Optional tier on ufbx's own FBX corpus, kept out of the fast suite.
corpus="${MSF_UFBX_CORPUS:-$(workspace _viz/assets/ufbx/ufbx-26a482ae66871d7de36eb722aa060bce95bce274)}"
if [ -n "$corpus" ] && [ -d "$corpus/data" ] && [ -x "$py312" ]; then
  output=$(MSF_UFBX_CORPUS="$corpus" suites "$py312" '' 'test_source_fbx_[cd]*.py')
  tier "ufbx corpus tier (loading, inspection, DCC reference frames, 0.3.0 oracle)" $? "$output"
else
  lines+=("- ufbx corpus tier: SKIPPED (no ufbx 0.23.1 source tree at ${corpus:-MSF_UFBX_CORPUS})")
fi

# Optional tier: Khronos sample assets re-authored as FBX, kept out of the fast suite.
khronos="${MSF_KHRONOS_ASSETS:-$(workspace _viz/assets/khronos)}"
if [ -n "$khronos" ] && [ -d "$khronos/Models" ] && [ -x "$py312" ]; then
  output=$(MSF_KHRONOS_ASSETS="$khronos" suites "$py312" test_source_twins.py '')
  tier "Khronos FBX twins tier" $? "$output"
else
  lines+=("- Khronos FBX twins tier: SKIPPED (no glTF-Sample-Assets checkout at ${khronos:-MSF_KHRONOS_ASSETS})")
fi

# Optional tier: the 09K real-asset harness recipes, one test per CASE_MATRIX ID.
real="${MSF_REAL_ASSETS:-$(workspace _viz/assets/real09K)}"
if [ -n "$real" ] && [ -f "$real/real-asset-harness-plan09K/CASE_MATRIX.json" ] && [ -x "$py312" ]; then
  output=$(MSF_REAL_ASSETS="$real" suites "$py312" test_real_assets.py test_real_assets_internal.py)
  tier "Real-asset recipe tier" $? "$output" 2
else
  lines+=("- Real-asset recipe tier: SKIPPED (no 09K inputs at ${real:-MSF_REAL_ASSETS})")
fi

# Optional tier: the end-to-end examples, run as scripts on the fetched assets.
examples="${MSF_EXAMPLE_ASSETS:-$(workspace _viz/assets/examples)}"
if [ -n "$examples" ] && [ -f "$examples/Fox.glb" ] && [ -x "$py312" ]; then
  output=$(MSF_EXAMPLE_ASSETS="$examples" MSF_REAL_ASSETS="$real" suites "$py312" test_examples.py test_examples_internal.py)
  tier "Examples tier" $? "$output" 2
else
  lines+=("- Examples tier: SKIPPED (run examples/fetch_assets.py --dest DIR and set MSF_EXAMPLE_ASSETS=DIR)")
fi

# docs/parity.md is generated from measurements; regenerate it when every input is present and compare.
# It is measured on macOS arm64, and usd-core's own arithmetic differs elsewhere, so on other platforms
# the fresh table is compared with 0.3.0's table measured on the same machine instead: MSF_ORACLE_SOURCE,
# a v0.3.0 checkout (default $MSF/_tools/oracle-src), run by the oracle interpreter with usd-core.
if [ -n "$real" ] && [ -f "$real/real-asset-harness-plan09K/CASE_MATRIX.json" ] && [ -n "$khronos" ] && [ -d "$khronos/Models" ] \
    && [ -d "$corpus/data" ] && [ -n "$examples" ] && [ -f "$examples/character-female-a.glb" ] && [ -x "$py312" ]; then
  mkdir -p build
  fresh=build/parity.md
  assets=(MSF_REAL_ASSETS="$real" MSF_KHRONOS_ASSETS="$khronos" MSF_UFBX_CORPUS="$corpus" MSF_EXAMPLE_ASSETS="$examples")
  oracle_source="${MSF_ORACLE_SOURCE:-$(workspace _tools/oracle-src)}"
  if ! env "${assets[@]}" "$py312" -B scripts/parity_table.py "$fresh" >/dev/null 2>&1; then
    lines+=("- docs/parity.md: generator FAILED (rerun python -B scripts/parity_table.py with the asset variables set)")
    failed=1
  elif [ "$(uname -s)" = Darwin ]; then
    if cmp -s "$fresh" docs/parity.md; then
      lines+=("- docs/parity.md: matches a fresh measurement")
    else
      lines+=("- docs/parity.md: STALE (rerun python -B scripts/parity_table.py with the asset variables set)")
      failed=1
    fi
  elif [ -n "$oracle_source" ] && [ -f "$oracle_source/scripts/parity_table.py" ] && [ -x "${MSF_ORACLE_PYTHON:-}" ] \
      && "$MSF_ORACLE_PYTHON" -c 'import pxr' 2>/dev/null; then
    root=$(pwd)
    if (cd "$oracle_source" && env "${assets[@]}" "$MSF_ORACLE_PYTHON" -B scripts/parity_table.py "$root/build/parity-0.3.0.md" >/dev/null 2>&1) \
        && grep -vE '^msf-(character-)?tools ' "$fresh" > build/parity-now.cmp && grep -vE '^msf-(character-)?tools ' build/parity-0.3.0.md > build/parity-0.3.0.cmp \
        && cmp -s build/parity-now.cmp build/parity-0.3.0.cmp; then
      lines+=("- docs/parity.md: a fresh measurement matches 0.3.0's on this machine ($(diff -q "$fresh" docs/parity.md >/dev/null && echo 'and the macOS table' || echo "usd-core's last digits differ from the macOS table"))")
    else
      lines+=("- docs/parity.md: a fresh measurement DIFFERS from 0.3.0's on this machine (compare build/parity.md and build/parity-0.3.0.md)")
      failed=1
    fi
  else
    lines+=("- docs/parity.md: NOT CHECKED (measured on macOS; elsewhere needs MSF_ORACLE_SOURCE and usd-core in the oracle)")
  fi
else
  lines+=("- docs/parity.md: NOT CHECKED (needs the real-asset, Khronos, example and ufbx corpus inputs)")
fi

# A wheel built from a clean clone of HEAD, through an sdist as `uv build` does, must record HEAD
# and hold exactly the tracked modules plus the extension.
if [ -n "$uv" ] && [ -x "$uv" ] && [ -x "$py312" ]; then
  scratch=$(mktemp -d)
  head=$(git rev-parse HEAD)
  if git clone -q --no-hardlinks . "$scratch/src" && git -C "$scratch/src" checkout -q "$head" \
      && (cd "$scratch/src" && "$uv" build -q --python "$py312" --out-dir "$scratch/dist" >/dev/null 2>&1) \
      && "$py312" -I - "$scratch/dist" "$head" $(git ls-files 'msf_character_tools/*.py') <<'PY'
import json, sys, tomllib, zipfile
from pathlib import Path
dist, head, modules = Path(sys.argv[1]), sys.argv[2], set(sys.argv[3:])
version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
[wheel] = dist.glob('*.whl')
names = set(zipfile.ZipFile(wheel).namelist())
package = {n for n in names if n.startswith('msf_character_tools/')}
extension = {n for n in package if n.startswith('msf_character_tools/_core.')}
ok = (json.loads(zipfile.ZipFile(wheel).read('msf_character_tools/_build_info.json')) == {'version': version, 'commit': head}
      and len(extension) == 1 and package == modules | extension | {'msf_character_tools/_build_info.json'})
sys.exit(not ok)
PY
  then
    lines+=("- Build record: a wheel built from HEAD via its sdist records HEAD and holds only tracked modules and _core")
  else
    lines+=("- Build record: FAILED (rerun uv build in a clean clone; read msf_character_tools/_build_info.json and the wheel's file list)")
    failed=1
  fi
  rm -rf "$scratch"
else
  lines+=("- Build record: SKIPPED (needs uv and Python 3.12)")
fi

# cmake and ninja for the C++ core: from PATH, which in a workspace starts with $MSF/_tools/bin.
if command -v cmake >/dev/null 2>&1 && command -v ninja >/dev/null 2>&1; then
  lines+=("- Build tools: cmake $(cmake --version | head -1 | cut -d' ' -f3), ninja $(ninja --version)")
else
  lines+=("- Build tools: cmake or ninja MISSING (see docs/building.md)")
fi

commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
dirty=$(git status --porcelain --untracked-files=no 2>/dev/null | grep -q . && echo ", uncommitted changes" || true)
echo
echo "### Local checks (scripts/ci_local.sh)"
echo "- Commit: $commit on $branch$dirty; $(uname -sm)"
printf '%s\n' "${lines[@]}"
[ $failed -eq 0 ] && echo "- Result: all run checks passed" || echo "- Result: FAILED"
exit $failed
