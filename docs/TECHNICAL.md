# MonopInk — technical notes

How the pieces fit together, for people who want to modify or port the project.
The step-by-step story of the original hack (in French) is in
[JOURNAL.fr.md](JOURNAL.fr.md).

```
 computer (Python)  ──USB CDC──►  Pico (probe firmware)  ──2-wire debug──►  CC2510  ──SPI──►  IL0373 e-paper
 monopink/                       pico/monopink_probe/                       firmware/
```

## 1. Target hardware

| | |
|---|---|
| MCU | TI CC2510F32: 8051 core, 32 KB flash (1 KB pages, 16-bit words), 4 KB RAM at XDATA 0xF000–0xFFFF, chip ID `0x81xx` (seen: `0x8104`) |
| Display | 2.6" 152 × 296 black/white/red, IL0373-compatible controller |
| Debug port | TI 2-wire protocol: DD = P2_1 (data, bidirectional), DC = P2_2 (clock), RESET_N |

CC2510 pin usage on the label (from angrymew / andrei-tatar, confirmed on hardware):

| Pin | Function |
|---|---|
| P0_0 | EPD power, **active low** (P-FET) |
| P0_1 | EPD CS |
| P0_3 / P0_5 | EPD SDI / CLK (USART0 SPI, alternative location 1) |
| P0_4 / P0_6 | NFC SDA / SCL |
| P1_0 | NFC chip + SPI flash supply |
| P1_2 | EPD DC |
| P1_3 | EPD BUSY (low = busy) |
| P1_4–P1_7 | SPI NOR flash |
| P2_0 | EPD RESET |
| P2_1 | debug DD + white LED |
| P2_2 | debug DC + LED boost converter enable |

## 2. Probe firmware (`pico/monopink_probe`)

Derived from CCLib_proxy (GPLv3). Same 4-byte command / 3-byte answer framing
(`[cmd, c1, c2, c3]` → `[status, hi, lo]`, status `01` OK, `02` error, `03` ready),
so CCLib's Python library can still drive it. Differences:

- **Pins are runtime settings** stored in the Pico's flash (EEPROM emulation).
  Defaults: RST GP3, DC GP4, DD_IN GP6, DD_OUT GP7. DD_IN may equal DD_OUT.
- **Debug mode on demand.** The original sketch enters debug mode at boot, which
  halts the label as soon as the Pico is powered. Here the label runs freely until
  a command that needs debug mode arrives.
- **Weak pull-up on DD while reading**, so a missing chip gives a clean
  "not responding" error (`0x03`) instead of reading `0x00` forever.
- Default instruction table = CC111x/CC251x (version 2).
- **Debug entry holds RESET_N low for 1 ms** before the two DC edges. The original
  `cc_delay(200)` lasts ~100 µs on a 16 MHz AVR but only a few µs on the RP2040;
  measured: a CC2510 sleeping in PM3 then misses the first entry (its regulator
  is off). With 1 ms it answers on the first try. The host also retries.

Extension commands:

| Cmd | Name | Arguments | Answer |
|---|---|---|---|
| `E1` | READ_CODE | c1:c2 address, c3 count (0 = 256) | frame `OK n`, then n bytes (MOVC loop run by the Pico) |
| `E2` | READ_XDATA | idem | idem (MOVX loop) |
| `E3` | WRITE_XDATA | c1:c2 address, c3 count | `READY`, host sends n bytes, then `OK n` |
| `E4` | RESET_RUN | c1 bit0 keep RESET_N low, bit1 keep DC low, bit2 keep DD low | `OK` — 20 ms hardware reset without debug entry, lines released |
| `E5` | RELEASE | – | `OK` — RESET_N high, DD/DC floating |
| `E8` | SET_PINS | – | `READY`, host sends `rst dc dd_i dd_o led flags` (led `FE` = on-board, `FF` = none; flags bit0 = save) |
| `E9` | GET_PINS | c1 = 0 / 1 / 2 | `(rst,dc)` / `(dd_i,dd_o)` / `(led,saved)` |
| `EA` | RESET_PINS | – | back to defaults, forget saved pins |
| `EF` | IDENT | c1 = 0 / 1 | `('M', version)` / `(chip: 0x20 RP2040, 0x35 RP2350, 0)` |

An original CCLib_proxy answers `ERROR FF` to `EF`: the host then falls back to
per-instruction transfers (slower but equivalent).

Flashing the Pico: the host opens the Pico's serial port at 1200 baud (the
arduino-pico "1200 baud touch") to reboot it into the ROM bootloader, waits for
the `RPI-RP2` / `RP2350` drive, reads `Board-ID` in `INFO_UF2.TXT`, copies the
matching `.uf2`, waits for the probe to come back and stores the pins.

## 3. Host tool (`monopink/`)

| Module | Role |
|---|---|
| `probe.py` | serial protocol, auto-sync, CCLib fallback |
| `chip.py` | CC2510 operations: identify, mass erase, page programming, verify, monitored run |
| `ops.py` | workflows used by both the CLI and the web app (with i18n messages) |
| `image.py` | conversion to the 3-colour planes, preview, test card |
| `pico.py` | serial ports, BOOTSEL drives, UF2 copy (real or simulated environment) |
| `sim.py` | simulated Pico + CC2510 (flash, lock, page routine, firmware refresh sequence) |
| `web/server.py` | local HTTP server (127.0.0.1 only), job queue, JSON API |
| `cli.py` | command line |

### Erase

`CHIP_ERASE` (debug command `0x14` on CC251x) wipes the whole flash **and the
lock bits**. TI documents status bit 7 as *CHIP_ERASE_DONE* for the CC111x/CC251x
family, while CCLib names it *CHIP_ERASE_BUSY* (CC253x meaning). The host waits
for the bit (bounded), but does not rely on it: it then re-enters debug mode (the
lock state is latched at reset), checks that `DEBUG_LOCKED` is clear and that the
flash reads blank.

### Page programming (no DMA)

CCLib's generic `writeCODE` uses DMA, never ported to the CC2510. Instead, for
each 1 KB page:

1. halt the CPU, write the 1024 data bytes to XDATA `0xF000`,
2. write this routine to `0xF400` and jump to it (`LJMP` executed as a debug
   instruction sets the PC):

```
MOV FADDRH,#page*2  MOV FADDRL,#0
MOV FLC,#01         ; page erase, wait while FLC.BUSY
MOV DPTR,#F000h     MOV R7,#2  MOV R6,#0   MOV FLC,#02 ; write
loop: 2 × (MOVX A,@DPTR / INC DPTR / MOV FWDATA,A), wait FLC.SWBSY, DJNZ R6/R7
DB A5h              ; breakpoint -> CPU halts
```

3. resume, poll the debug status until *CPU_HALTED*.

After all pages, the host resets into debug mode (fresh flash cache) and reads
every page back (`READ_CODE`) to compare.

### Monitored run

After programming, the host re-enters debug mode, writes `"MPHD"` at XDATA
`0xF800` and resumes the CPU. The firmware writes its progress to the same
mailbox; every 0.4 s the host halts the CPU, reads the mailbox (saving and
restoring `A` and `DPTR`, which the reads clobber) and resumes it. `"MPHD"` also
tells the firmware to stay awake at the end instead of entering PM3, so the
last state can be read.

| Offset | Content |
|---|---|
| 0–3 | `MPHD` written by the host |
| 4 | state: `10` boot, `30` panel ready, `40` data sent, `50` refreshing, `60` refresh done, `70` panel off, `80` done (hold) |
| 5 | error: `1` BUSY at power-on, `2` refresh timeout, `3` power-off timeout |
| 6–7 | refresh duration, ms (little endian) |
| 8–9 | total time since boot, ms |
| 10 | firmware version |
| 11 | BUSY level just before the power-on command |
| 12–13 | ms waited for BUSY after power-on (`FFFF` = timeout) |
| 14 | boot counter (the RAM survives a reset) |
| 15 | `SLEEP` register at boot (bits 4:3 = reset cause) |

`"MPNR"` instead of `"MPHD"` runs the **autonomous start test**: the host writes
it, then does a plain reset (`RESET_RUN`, not debug mode). The firmware behaves
exactly like a battery boot but skips PM3 at the end; the RAM survives the next
reset, so the host reads the result after re-entering debug mode.

A refresh shorter than 3 s is reported as suspicious: the BUSY line never went
low, so the panel is probably not connected.

## 4. Label firmware (`firmware/`)

Flash layout (also in `firmware/src/layout.h` and `monopink/layout.py`):

| Address | Content |
|---|---|
| `0x0000–0x4FEF` | code (~1.2 KB used) |
| `0x4FF0–0x4FFF` | info block: `MONOPINK`, version major/minor, layout version, width, height |
| `0x5000–0x65F7` | black/white plane, 5624 bytes |
| `0x6600–0x7BF7` | red plane, 5624 bytes |
| `0x7C00–0x7FFF` | unused |

Boot sequence (firmware 1.2): read and clear the host flag in RAM; white LED
and its boost converter off (P2_1/P2_2 low, only when no debug session is
running); WDT in timer mode as a 2 ms tick; **panel held off** (supply cut, every
panel line low, BUSY without pull-up) for 200 ms; supply on with the lines still
low, 100 ms; SPI on, CS/DC high, hardware reset, wait BUSY; booster soft-start
`06 17 17 17`, power on `04` (wait BUSY, ~50 ms), panel setting `00 0F 0D` (KWR
mode), resolution `61 98 01 28`, VCOM/data interval `50 77`, planes `10` + `13`,
refresh `12` (wait BUSY, ~20 s), power off `02`, deep sleep `07 A5`, back to the
held-off state, NFC/SPI-flash supply off, then PM3 forever (only a reset wakes
the chip; the debug interface resets it anyway).

Only **one** refresh per boot (the angrymew example cleared the screen first,
i.e. two ~15 s refreshes) and the panel is never left powered.

### Plane format

- 19 bytes per row (152 / 8), MSB = leftmost pixel, 296 rows.
- Black/white plane (cmd `0x10`): 1 = white, 0 = black.
- Red plane (cmd `0x13`): 0 = red, 1 = no red. Red wins over black.

`monopink export --bin` writes the two planes back to back; `--c` writes them as
`imageBW[]` / `imageR[]` for the angrymew firmware; `--hex` writes a complete
flash image (firmware + picture) usable with any CC-Debugger tool.

## 5. Image conversion

1. EXIF orientation, alpha flattened on white.
2. Resize to 152 × 296 (portrait) or 296 × 152 (landscape): *cover* crops,
   *contain* pads with the border colour, *stretch* distorts; Lanczos, or nearest
   neighbour with *sharp*.
3. Invert / brightness / contrast.
4. **Red mask by hue**: a pixel is red when `R > 90` and `R − max(G, B)` exceeds a
   threshold set by *red sensitivity*. This keeps greys from turning into red
   speckles, which a plain 3-colour nearest-colour match does.
5. The rest is black/white: Floyd–Steinberg dithering, a 50 % threshold, or
   *levels* (dark → black, mid → red, light → white).
6. Optional: white regions not connected to the border become red (flood fill
   from the edges — the trick from the original log).
7. Landscape designs are rotated 90° clockwise onto the panel; calibration
   (rotate 180°, mirror) is applied last, only to the panel data.

## 6. Web app

`monopink web` serves `web/static/` and a JSON API on `127.0.0.1:8420`
(next free port if busy). Hardware operations are background jobs; the page polls
`/api/jobs/<id>` for log lines (already translated), progress and firmware
states. POST requests require the header `X-MonopInk: 1` and a local `Host`,
which stops other web sites from driving the hardware through your browser.

| Endpoint | |
|---|---|
| `GET /api/state` | version, settings, dependencies, current job |
| `GET /api/pico/status` | BOOTSEL drive / probe kind / stored pins |
| `GET /api/ports` | serial ports and drives |
| `POST /api/config` | pins, port, language, calibration |
| `POST /api/jobs` | `pico_flash`, `pico_pins`, `tag_info`, `tag_install`, `tag_image`, `tag_run`, `tag_reset`, `tag_dump` |
| `GET /api/jobs/<id>?since=n` / `POST …/cancel` | job log / cancel |
| `POST /api/image/upload` (raw body) · `/preview` · `/test-pattern` | picture |
| `GET /api/image/export?fmt=png\|hex\|bin\|c` · `/api/label/preview` · `/api/label/dump` | files |

## 7. Findings on real hardware

Measured on a GL420 (CC2510F32 rev 4) with a Pico; each one changed the code.

1. **False `DEBUG_LOCKED`.** Right after debug entry the status reads `0xB6`
   (bit 2 set) and becomes `0xB2` after the first debug instruction, on a chip
   whose flash reads back perfectly. The lock test is therefore functional
   (`MOV A,#A5h` / `#5Ah` must come back), which is what "locked" really means:
   a locked CC2510 refuses debug instructions. The original log's "locked" chip
   was very likely not locked.
2. **The RAM survives an external reset** (not PM3). A flag left by a previous
   debug session made a later plain boot stay awake: the firmware now consumes
   the flag at boot.
3. **PM3 wake-up** needs a longer RESET_N pulse before debug entry (see §2).
4. **The display is powered from the battery rail.** With 3.3 V only on DVDD,
   debug-mode runs polled by the host refreshed fine, but autonomous boots never
   powered the panel (BUSY stuck). With 3.3 V on the battery contacts they do.
5. **Back-powering the panel.** After a reset every CC2510 pin is an input with
   pull-up, which half-powers the unpowered IL0373 through its I/O pins; its
   power-on reset then fails randomly (BUSY stuck low or high). Firmware 1.2
   first drives every panel line low with the supply off for 200 ms, powers the
   panel with the lines still low, then enables SPI, resets the panel and waits
   for BUSY. Result: 8/8 autonomous boots and 4/4 host-watched runs, versus
   random results before.

## 8. What changed compared to the original log

The manual steps of [JOURNAL.fr.md](JOURNAL.fr.md) are all automated or made
unnecessary:

| Original | Now |
|---|---|
| Install Arduino IDE + core + CCLib, edit pins, upload with BOOTSEL | prebuilt `.uf2`, copied by the app; pins set from the UI |
| Patch CCLib for Python 3 (`chr`→`bytes`, `/`→`//`), flash size 16→32, add `setPC`, `debug_active` | clean host implementation (`probe.py`, `chip.py`) |
| `cc_write_flash.py` DMA path broken → custom `flash_page.py` | page routine built in, block transfers, read-back verification |
| `y` prompt confusion / stale input → `Aborted` | web confirmation checkbox; CLI flushes pending keystrokes and accepts y/yes/o/oui |
| Rewrite `make.sh` for macOS, `.ihx`→`.hex` | prebuilt firmware; `firmware/build.sh` for macOS/Linux |
| Regenerate `images.c`, fix *multiple definition* | picture at a fixed flash address, no compilation |
| Display left powered in `while(1)` | panel deep sleep + supply cut + CC2510 PM3 |
| 3.3 V on DVDD | 3.3 V on the battery contacts (the display lives on the battery rail) |
| "Debug lock active" read right after `-E` | functional lock test (false positive explained, §7) |
| Hard-coded `/dev/cu.usbmodem101` | port auto-detection (Raspberry Pi USB VID) |
