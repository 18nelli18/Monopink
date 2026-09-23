"""Flash / RAM layout of the MonopInk label firmware.

Keep in sync with firmware/src/layout.h.
"""

FLASH_SIZE = 0x8000          # CC2510F32
PAGE_SIZE = 0x400            # 1 KB flash pages
WORD_SIZE = 2                # CC251x flash words are 16-bit

EPD_WIDTH = 152
EPD_HEIGHT = 296
ROW_BYTES = EPD_WIDTH // 8   # 19
PLANE_SIZE = ROW_BYTES * EPD_HEIGHT   # 5624

CODE_LIMIT = 0x3000
NFC_DESC_ADDR = 0x3000          # NFC receive state (1 page)
NFC_STAGING_ADDR = 0x3400       # compressed picture received over NFC
NFC_STAGING_SIZE = 0x1800
FW_INFO_ADDR = 0x4FF0
FW_MAGIC = b"MONOPINK"
IMG_BW_ADDR = 0x5000
IMG_R_ADDR = 0x6600
IMG_REGION_START = 0x5000    # pages 20..30
IMG_REGION_END = 0x7C00

MAILBOX_ADDR = 0xF800
MAILBOX_SIZE = 16
MAILBOX_HOLD = b"MPHD"          # debug-mode run watched by the host
MAILBOX_BOOT_TEST = b"MPNR"     # normal boot, but no PM3 at the end

# Scratch RAM used while programming a flash page
XDATA_BUF = 0xF000
XDATA_ROUTINE = XDATA_BUF + PAGE_SIZE

# MB_STATE values (firmware progress)
ST_BOOT = 0x10
ST_EPD_POWERED = 0x20
ST_EPD_READY = 0x30
ST_DATA_SENT = 0x40
ST_REFRESHING = 0x50
ST_REFRESH_DONE = 0x60
ST_EPD_OFF = 0x70
ST_IDLE_HOLD = 0x80
KNOWN_STATES = (ST_BOOT, ST_EPD_POWERED, ST_EPD_READY, ST_DATA_SENT,
                ST_REFRESHING, ST_REFRESH_DONE, ST_EPD_OFF, ST_IDLE_HOLD)

ST_NFC_DIAG_DONE = 0x90
ST_NFC_DONE = 0xA0

MAILBOX_NFC_DIAG = b"MPNF"      # dump the NFC chip state
MAILBOX_NFC_TEST = b"MPNW"      # host plays the phone
NFCDIAG_ADDR = 0xF810
NFCDIAG_SIZE = 0xA0
XRAM_BUF_B = 0xF810             # NDEF area written by the "MPNW" test
XRAM_NFC_STATUS = 0xFC60
XRAM_NFC_INFO = 0xFC70

ERR_NONE = 0
ERR_BUSY_POWER_ON = 1
ERR_BUSY_REFRESH = 2
ERR_BUSY_POWER_OFF = 3


def image_region(bw: bytes, red: bytes) -> bytes:
    """Build the 11 KB flash region (pages 20..30) holding both planes."""
    assert len(bw) == PLANE_SIZE and len(red) == PLANE_SIZE
    region = bytearray(b"\xff" * (IMG_REGION_END - IMG_REGION_START))
    o = IMG_BW_ADDR - IMG_REGION_START
    region[o:o + PLANE_SIZE] = bw
    o = IMG_R_ADDR - IMG_REGION_START
    region[o:o + PLANE_SIZE] = red
    return bytes(region)
