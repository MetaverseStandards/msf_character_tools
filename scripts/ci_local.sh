#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run what .github/workflows/check.yml runs, on local Python 3.11 and 3.12
# environments, then print a summary block for a pull-request description.
# Interpreters default to $MSF/_tools/venv3.11 and venv3.12; override with
# MSF_PY311 / MSF_PY312.
set -u
cd "$(dirname "$0")/.." || exit 2
MSF="${MSF:-$HOME/.local/share/msf}"
failed=0
lines=()

seconds() { python3 -c 'import sys, time; print(f"{time.time() - float(sys.argv[1]):.1f}")' "$1"; }

for version in 3.11 3.12; do
  var="MSF_PY${version/./}"
  py="${!var:-$MSF/_tools/venv$version/bin/python}"
  if [ ! -x "$py" ]; then
    lines+=("- Python $version: SKIPPED (no interpreter at $py)")
    continue
  fi
  exact=$("$py" -c 'import platform; print(platform.python_version())')
  start=$(python3 -c 'import time; print(time.time())')
  output=$("$py" -B -m unittest discover -s tests 2>&1)
  status=$?
  took=$(seconds "$start")
  ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
  verdict=$(printf '%s\n' "$output" | grep -E '^(OK|FAILED)' | tail -1)
  if [ $status -ne 0 ]; then
    failed=1
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
  fi
  if "$py" -B check.py >/dev/null 2>&1; then check="check.py OK"; else check="check.py FAILED"; failed=1; fi
  lines+=("- Python $exact: unittest ${ran:-?} tests, ${verdict:-no result} in ${took} s; $check")
done

if ! command -v cmake >/dev/null 2>&1; then
  lines+=("- Native pilot: SKIPPED (cmake not found)")
elif ! command -v c++ >/dev/null 2>&1; then
  lines+=("- Native pilot: SKIPPED (no C++ compiler)")
else
  build=$(mktemp -d)
  if cmake -S . -B "$build" -DMSF_BUILD_NATIVE_PILOT=ON >/dev/null \
      && cmake --build "$build" --config Release >/dev/null \
      && ctest --test-dir "$build" -C Release --output-on-failure >/dev/null; then
    lines+=("- Native pilot: build and ctest OK")
  else
    lines+=("- Native pilot: FAILED (rerun cmake/ctest in $build for details)")
    failed=1
  fi
  [ $failed -eq 0 ] && rm -rf "$build"
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
