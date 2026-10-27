#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# libFuzzer over the core's input parsers, on an ASan and UBSan build in build/fuzz:
# glTF and GLB inspection with everything an admitted asset feeds (fuzz_gltf),
# data: URIs, source node paths and target keys, and FBX conversion through ufbx.
#
#   scripts/fuzz.sh [SECONDS]   seconds per harness, run side by side (default 60)
#
# Compilers without the fuzzer runtime (Apple clang) need MSF_LIBFUZZER, a
# libFuzzer.a built from compiler-rt; see docs/testing.md. Seeds come from the
# tracked fixtures and, when present, the ufbx corpus (MSF_UFBX_CORPUS) and the
# Khronos assets (MSF_KHRONOS_ASSETS). Corpora persist in build/fuzz/corpus and
# findings land in build/fuzz/artifacts. Exits nonzero on any finding.
set -u
cd "$(dirname "$0")/.." || exit 2
seconds="${1:-60}"
MSF="${MSF:-$HOME/.local/share/msf}"
export PATH="$MSF/_tools/bin:$PATH"
py="${MSF_PY312:-$MSF/_tools/venv3.12/bin/python}"
out=build/fuzz
flags=(-DMSF_FUZZ=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo -DPython_EXECUTABLE="$py")
[ -n "${MSF_LIBFUZZER:-}" ] && flags+=(-DMSF_LIBFUZZER="$MSF_LIBFUZZER")
harnesses=(gltf data_uri paths fbx)
cmake -S . -B "$out" -G Ninja "${flags[@]}" >/dev/null || exit 2
cmake --build "$out" --target "${harnesses[@]/#/fuzz_}" >/dev/null || exit 2

ufbx="${MSF_UFBX_CORPUS:-$(ls -d "$MSF"/_viz/assets/ufbx/ufbx-26a482ae66871d7de36eb722aa060bce95bce274 2>/dev/null)}"
khronos="${MSF_KHRONOS_ASSETS:-$MSF/_viz/assets/khronos}"
python3 -B - "$out/seed" "$ufbx" "$khronos" <<'PY' || exit 2
import hashlib, pathlib, re, subprocess, sys
seed, ufbx, khronos = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
def put(kind, data):
    (seed / kind).mkdir(parents=True, exist_ok=True)
    (seed / kind / hashlib.sha1(data).hexdigest()).write_bytes(data)
# The first byte of a glTF input picks the container (bit 0) and the resolver (bit 1).
tracked = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True).stdout.split()
glbs = [pathlib.Path(f) for f in tracked if f.endswith('.glb')] + sorted((khronos / 'Models').rglob('*.glb'))
for path in glbs:
    if path.stat().st_size < 200_000:
        put('gltf', b'\x01' + path.read_bytes())
for path in [pathlib.Path(f) for f in tracked if f.endswith('.gltf')]:
    text = path.read_bytes()
    if len(text) < 200_000:
        put('gltf', b'\x00' + text)
        put('gltf', b'\x02' + text)
        for uri in re.findall(rb'"(data:[^"]{0,4000})"', text):
            put('data_uri', b'\x00' + uri)
put('data_uri', b'\x01AAAA')
for path in (b'/a', b'/a/b[2]', b'/a\\/b', b'/root/arm#helper:geometry', b'/x[0]#helper:scale', b'/a/b|/c'):
    put('paths', path)
fbx = [pathlib.Path('examples/data/AnimatedMorphCube.writer.fbx')]
if ufbx:
    fbx += sorted(p for p in pathlib.Path(ufbx, 'data').glob('*.fbx') if p.stat().st_size < 64_000)
# The first byte of an FBX input picks the options.
for i, path in enumerate(fbx):
    put('fbx', bytes([i % 16]) + path.read_bytes())
PY

pids=()
for h in "${harnesses[@]}"; do
  mkdir -p "$out/corpus/$h" "$out/artifacts"
  ASAN_OPTIONS=detect_leaks=0 "$out/fuzz_$h" "$out/corpus/$h" "$out/seed/$h" -max_total_time="$seconds" -max_len=200000 \
    -timeout=20 -rss_limit_mb=4096 -artifact_prefix="$out/artifacts/$h-" >"$out/log-$h.txt" 2>&1 &
  pids+=($!)
done
status=0
for i in "${!harnesses[@]}"; do
  h=${harnesses[$i]}
  if wait "${pids[$i]}"; then
    echo "fuzz_$h: clean, $(grep -oE 'Done [0-9]+ runs' "$out/log-$h.txt" | awk '{print $2}') runs in ${seconds} s, corpus $(ls "$out/corpus/$h" | wc -l | tr -d ' ')"
  else
    echo "fuzz_$h: FINDING (see $out/log-$h.txt and $out/artifacts)"
    status=1
  fi
done
exit $status
