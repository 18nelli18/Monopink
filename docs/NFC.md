# MonopInk — pictures from a phone over NFC

The GL420 label has an NFC chip (NXP **NTAG I2C plus**, NT3H2111/2211) wired to
the CC2510. With the MonopInk label firmware **1.3+**, an Android phone can send
a new picture to the label, with no Pico and no computer: the label wakes up
when the phone comes close, even on batteries, and goes back to sleep afterwards.

*Résumé en français : voir la section « Images depuis un téléphone (NFC) » du
[README.fr.md](../README.fr.md#images-depuis-un-téléphone-nfc).*

- [1. Requirements](#1-requirements)
- [2. Publishing the phone page (HTTPS)](#2-publishing-the-phone-page-https)
- [3. Using it](#3-using-it)
- [4. How a transfer works](#4-how-a-transfer-works)
- [5. Protocol reference](#5-protocol-reference)
- [6. Picture codec ("MPK" v1)](#6-picture-codec-mpk-v1)
- [7. Label firmware](#7-label-firmware)
- [8. Tests](#8-tests)
- [9. Status and limits](#9-status-and-limits)

## 1. Requirements

| | |
|---|---|
| Phone | Android with NFC, **Chrome** (Web NFC exists only in Chrome for Android; not on iPhone, not on computers) |
| Phone page | `docs/nfc/` served over **https://** (Web NFC refuses plain http pages) |
| Label | MonopInk label firmware **1.3** or newer (install it from the web app, step *Label*) |
| Power | batteries in the label (or the Pico's 3.3 V) — the NFC chip can't run the CC2510 from the phone's field |

## 2. Publishing the phone page (HTTPS)

The page is static (HTML/CSS/JS, no server code, nothing is uploaded anywhere),
so any HTTPS static host works. The simplest is **GitHub Pages**:

1. Push the MonopInk folder to a GitHub repository.
2. Repository → *Settings* → *Pages* → *Build and deployment*: source
   *Deploy from a branch*, branch `main`, folder **`/docs`** → *Save*.
3. After a minute the page is at
   `https://<your-user>.github.io/<repository>/nfc/`.
4. In the MonopInk web app, step **NFC (phone)**, paste that address and click
   *Save*: the app then shows a link that also carries the language and the
   display calibration (`?lang=fr&rot=0&mirror=0`). Open it on the phone (send
   it to yourself, or type it).

The desktop app also serves the page at `http://127.0.0.1:8420/nfc/` for a
preview on the computer (conversion and preview work; sending needs a phone).

## 3. Using it

1. On the phone, open the page in Chrome. Pick a picture (camera roll, files…).
2. Adjust it: orientation, framing, rendering (*Threshold* gives the fewest
   taps, *Dithering* suits photos), same settings as the desktop app. The
   preview shows the result and the number of **taps** needed.
3. Press **Send to the label**, then tap the phone on the label: hold it still
   until it vibrates, move it away, wait a second, tap again for the next part.
   The dots count the parts. The page tells you what to do at each step
   (re-tap, wait, errors).
4. After the last part the label rebuilds the picture and refreshes its screen
   (~20 s). A last tap confirms *Picture displayed ✓*.

Typical sizes: text/logo in *Threshold* 0.3–1 KB (**1 tap**), drawings 1–2 KB
(1–3 taps), dithered photos 3–6 KB (4–8 taps). A tap carries up to 832 bytes;
the label accepts up to 6 KB (compressed).

*Read the label's status* (bottom of the page) shows the firmware version, the
transfer state and the last error, without sending anything.

## 4. How a transfer works

Web NFC only gives access to NDEF messages, and the NTAG lets either the phone
or the CC2510 use its memory at a time. So each tap is one exchange:

```
 phone                          NTAG memory                     CC2510 (asleep)
   | ---- tap: read ---------->  status "x/mps"  
   | <--- status (next part = i)
   | ---- write part i ------->  part "x/mpk"      FD line low -> wakes up
   | (vibrates, user moves away)                    waits until the field is gone
   |                                                reads part i over I2C,
   |                                                checks it, stores it in flash,
   |                             status "x/mps" <-- writes the new status
   | ---- next tap: read ------> status (next part = i+1) ...
```

When the last part is in, the label checks the whole stream (CRC), decodes it
into the picture area of its flash, refreshes the display and publishes
*complete*. If anything goes wrong, the status says which part is expected next
and the page simply sends that one: a tap interrupted halfway, a duplicate, a
part from another picture or a label that lost power are all handled.

## 5. Protocol reference

The NTAG user memory is a Type 2 Tag area: `03 <len> <NDEF message> FE`. The
label formats the chip at boot if needed (capability container `E1 10 6D 00`,
i.e. 872 bytes, static locks cleared) so that Android sees an NDEF tag.

**Part** — written by the phone: one MIME record, type `x/mpk`, payload =
15-byte header + data (all little endian):

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | `"MK"` |
| 2 | 1 | protocol version (1) |
| 3 | 2 | picture id (random, chosen by the phone) |
| 5 | 1 | part index |
| 6 | 1 | part count |
| 7 | 2 | stream length (≤ 6144) |
| 9 | 2 | CRC-16 of the whole stream |
| 11 | 2 | CRC-16 of this part's data |
| 13 | 2 | chunk size (≤ 832; part *i* holds stream bytes `[i·chunk, (i+1)·chunk)`) |
| 15 | … | data |

CRC-16 = CCITT-FALSE (poly 1021h, init FFFFh, no reflection, no final xor).

**Status** — written by the label: one MIME record, type `x/mps`, 16 bytes, at
the start of the NTAG memory (`03 18 D2 05 10 "x/mps" <status> FE`):

| Offset | Field |
|---|---|
| 0–1 | `"MS"` |
| 2 | protocol version (1) |
| 3 | firmware version (major << 4 \| minor) |
| 4 | state: 0 ready, 1 receiving, 2 complete, 3 error |
| 5 | last error: 0 ok, 1 NFC chip, 2 bad header, 3 part CRC, 4 unexpected part, 5 too big, 6 stream CRC, 7 decode |
| 6–7 | picture id of the current / last transfer |
| 8 | next expected part |
| 9 | part count |
| 10–11 | max part data (832) |
| 12–13 | max stream (6144) |
| 14 | NDEF area layout (1) |

Rules applied by the label: parts must arrive in order (`next`); a part already
stored is ignored; part 0 of a *different* picture starts a new transfer; part 0
of the picture already displayed is ignored; a part of an unknown transfer is
refused (`unexpected part`) — the phone then restarts from part 0. The phone
page applies the matching logic (`docs/nfc/nfc.js`).

## 6. Picture codec ("MPK" v1)

The 152 × 296 three-colour picture (panel orientation, raster order, 0 white /
1 black / 2 red) is compressed with a **context-adaptive binary range coder**
(LZMA-style: 11-bit probabilities, shift 5):

- per pixel an *ink* bit (white or not), then, if ink, a *red* bit;
- context = the 5 already-decoded neighbours (left, left-left, up-left, up,
  up-right; outside = white): 243 contexts for *ink*, 81 for *red*;
- stream = `01` (format byte) + range coder bytes.

It beats deflate on these pictures (text ≈ 0.4 KB, dithered photo ≈ 3–6 KB),
decodes one row at a time in ~1 KB of RAM on the 8051, and has three
bit-identical implementations: `monopink/codec.py` (reference),
`firmware/src/codec.c` (decoder) and `docs/nfc/codec.js` (encoder).

## 7. Label firmware

**Wiring** (GL420): P1_0 = NTAG supply, P1_1 = NTAG field detect (FD, open
drain), P0_4 = SDA, P0_6 = SCL (bit-banged I2C, address 55h). P1_0 apparently
also feeds the SPI flash chip, which MonopInk does not use.

**Normal life** (`firmware/src/main.c`): boot → draw the picture → format the
NTAG and publish the status → sleep. Two wake-up modes, chosen at boot:

| Mode | When | Sleep | Wake-up |
|---|---|---|---|
| **FD** | FD reads high with the NTAG unpowered (the board has a pull-up) | PM3, NTAG off, ≈ 1 µA | P1_1 falling edge = a phone's field |
| **Polling** | FD floats (the CC2510 has **no** internal pull-up on P1_0/P1_1) | PM2, sleep timer every ~2 s, ≈ 10–20 µA average (estimate) | powers the NTAG, looks at its field flag and first NDEF block |

`./monopink.sh nfc-info` (or *Check the NFC chip*) tells which mode the label
uses. If FD stays low for a minute three times in a row, the firmware falls back
to polling.

After a wake-up, the firmware waits until the field has been gone for 100 ms
(the phone has left: I2C access while the phone talks would make the phone's
commands fail), powers the NTAG, reads and handles the part, writes the status,
releases the NTAG to the RF side and powers it off.

**Memory** (`firmware/src/layout.h`):

| Area | Use |
|---|---|
| flash 0x0000–0x2FFF | code (build fails above 0x3000) |
| flash 0x3000 (1 page) | receive state, written **once per picture** |
| flash 0x3400–0x4BFF | staging for the compressed stream (6 KB) |
| flash 0x5000–0x7BFF | picture planes (the decoder writes them in place) |
| XDATA 0xFC50 | receive state (RAM copy with checksum) |
| XDATA 0xFD00–0xFDA1 | C variables — the CC2510F32 loses 0xFDA2–0xFEFF in PM2/PM3; the linker is limited to 0xA2 bytes there |

Flash endurance is only **1000 erase cycles** (CC2510 datasheet), so the receive
state lives in RAM (kept in PM2/PM3) and is copied to flash only when a transfer
ends; after a power loss the flash copy is used and the phone starts over. Per
picture the flash sees: 1 state page write, ~2 writes per staging page and 1 per
picture page — about the same as sending a picture with the Pico.

**Debug-port modes** (for the host tool, like the other MonopInk modes):
`MPNF` dumps the NTAG state into RAM (`nfc-info`), `MPNW` makes the firmware
play the label for an NDEF area the host placed in RAM — the Pico plays the
phone (`nfc-send`). Both follow exactly the code paths of a real tap, except
the RF part.

## 8. Tests

`tests/test_nfc.py` (no hardware needed):

- codec round trips (Python), C decoder = Python decoder, JS encoder and part
  splitter = Python, byte for byte (Node);
- the **real** `firmware/src/nfc.c` + `codec.c`, compiled natively, against a
  mock NTAG and flash (`tests/native/nfc_test.c`), **side by side with the
  Python model** `monopink/nfclabel.py` — same statuses, same flash writes:
  single/multi-part pictures, damaged part, out-of-order part, duplicates,
  foreign part, new picture after a complete one, damaged first part, power
  loss mid-transfer, polling-mode detection;
- the simulator (`--sim`) answers `MPNF`/`MPNW` with that model, so
  `nfc-info`, `nfc-send` and the web app's NFC step are tested end to end;
- the phone page's translation keys, and the web server's `/nfc/` route.

The phone page itself was also driven in a browser with a mock `NDEFReader`
whose "label" was the native firmware build: the picture decoded by the
firmware was pixel-identical to the page's preview, including the recovery of a
damaged part.

## 9. Status and limits

- **Not yet validated on the real label** (the Pico was not connected while
  this was developed): the I2C driver, the NTAG formatting, the flash
  self-programming from the firmware, the decoder's speed on the 8051, both
  wake-up modes and the phone taps. Start with `nfc-info`, then `nfc-send`
  (both with the Pico), then *Phone mode* and a real phone.
- Web NFC: Chrome for Android only; the page must be in the foreground with the
  screen on.
- Polling mode (no FD pull-up): wait 2–3 s between taps; the page says so if
  the label has not taken the previous part yet.
- One picture at a time, up to 6 KB compressed (very detailed dithered photos
  may be refused: use *Threshold* or *Levels*).
- No authentication: any phone running this page can change the picture. The
  NTAG password (AUTH0) is left untouched.
