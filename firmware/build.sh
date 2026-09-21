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

CFLAGS="-mmcs51 --model-small --opt-code-size --std-sdcc11"
LDFLAGS="--code-size 0x8000 --iram-size 256 --xram-loc 0xF000 --xram-size 0x0800"

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
echo "OK -> firmware/build/monopink-tag.hex"
if [ "${1:-}" = "--install" ]; then
    cp build/monopink-tag.hex prebuilt/monopink-tag.hex
    echo "copied to firmware/prebuilt/monopink-tag.hex"
fi
