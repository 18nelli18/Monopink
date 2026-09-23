#!/usr/bin/env bash
# Rebuild the MonopInk probe firmware (.uf2) for Raspberry Pi Pico / Pico 2.
#
# Only needed if you change the sketch: ready-made files are in prebuilt/.
# Requires arduino-cli with the earlephilhower "rp2040" core:
#   arduino-cli config add board_manager.additional_urls \
#     https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
#   arduino-cli core update-index && arduino-cli core install rp2040:rp2040
# (the arduino-cli bundled with Arduino IDE 2.x is found automatically.)
set -euo pipefail
cd "$(dirname "$0")"

CLI="${ARDUINO_CLI:-}"
if [ -z "$CLI" ]; then
    if command -v arduino-cli >/dev/null 2>&1; then
        CLI="arduino-cli"
    elif [ -x "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" ]; then
        CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
    else
        echo "error: arduino-cli not found (set ARDUINO_CLI=/path/to/arduino-cli)" >&2
        exit 1
    fi
fi

build() {
    local fqbn="$1" out="$2"
    echo "== $fqbn"
    rm -rf "build/$out"
    "$CLI" compile --fqbn "$fqbn" --output-dir "build/$out" monopink_probe
    cp "build/$out/monopink_probe.ino.uf2" "prebuilt/monopink-probe-$out.uf2"
}

mkdir -p build prebuilt
build rp2040:rp2040:rpipico  rp2040
build rp2040:rp2040:rpipico2 rp2350
ls -l prebuilt/
