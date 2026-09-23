#!/usr/bin/env bash
# Build the MonopInk label firmware with SDCC (https://sdcc.sourceforge.net).
#   macOS : brew install sdcc        Debian/Ubuntu : sudo apt install sdcc
#
# Output: build/monopink-tag.hex  (code only - the picture is added by the
# host tool at flash time, at the fixed address described in src/layout.h)
#
# Only needed if you modify the firmware: a ready-made copy lives in
# prebuilt/monopink-tag.hex and is what the tool flashes by default.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v sdcc >/dev/null 2>&1; then
    echo "error: sdcc not found (macOS: brew install sdcc, Linux: apt install sdcc)" >&2
    exit 1
fi

CFLAGS="-mmcs51 --model-medium --opt-code-size --std-sdcc11"
# pdata/xdata variables at 0xFD00-0xFDA1: the CC2510F32 loses 0xFDA2-0xFEFF
# in PM2/PM3 (datasheet 10.2.3.1), and the firmware sleeps in them
LDFLAGS="--code-size 0x8000 --iram-size 256 --xram-loc 0xFD00 --xram-size 0x00A2"

rm -rf build
mkdir -p build
for src in src/*.c; do
    sdcc $CFLAGS -c "$src" -o "build/$(basename "${src%.c}").rel"
done
# main.rel must come first on the link line
objs="build/main.rel $(ls build/*.rel | grep -v '/main.rel$' | tr '\n' ' ')"
sdcc $CFLAGS $LDFLAGS -o build/monopink-tag.ihx $objs
cp build/monopink-tag.ihx build/monopink-tag.hex

echo
grep -E "ROM/EPROM/FLASH" build/monopink-tag.mem || true
# code must stay below the NFC state/staging area (CODE_LIMIT, see layout.h)
end=$(python3 - <<'PY'
top = 0
for line in open("build/monopink-tag.ihx"):
    n, a, t = int(line[1:3], 16), int(line[3:7], 16), int(line[7:9], 16)
    if t == 0 and a < 0x4FF0:
        top = max(top, a + n)
print(top)
PY
)
if [ "$end" -gt $((0x3000)) ]; then
    echo "error: code ends at $end, above 0x3000 (NFC state/staging area)" >&2
    exit 1
fi
echo "code: $end bytes (limit 12288)"
echo "OK -> firmware/build/monopink-tag.hex"
if [ "${1:-}" = "--install" ]; then
    cp build/monopink-tag.hex prebuilt/monopink-tag.hex
    echo "copied to firmware/prebuilt/monopink-tag.hex"
fi
