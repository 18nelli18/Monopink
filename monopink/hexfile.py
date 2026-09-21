"""Minimal Intel HEX reader / writer (enough for SDCC .ihx and CCLib)."""


class HexError(ValueError):
    pass


def parse_hex(text: str) -> dict:
    """Return {address: byte} from Intel HEX text."""
    mem = {}
    base = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise HexError(f"line {lineno}: missing ':'")
        try:
            rec = bytes.fromhex(line[1:])
        except ValueError:
            raise HexError(f"line {lineno}: not hexadecimal")
        if len(rec) < 5 or len(rec) != rec[0] + 5:
            raise HexError(f"line {lineno}: bad length")
        if sum(rec) & 0xFF:
            raise HexError(f"line {lineno}: bad checksum")
        n, addr, rtype, data = rec[0], (rec[1] << 8) | rec[2], rec[3], rec[4:-1]
        if rtype == 0x00:
            for i, b in enumerate(data):
                mem[base + addr + i] = b
        elif rtype == 0x01:
            break
        elif rtype == 0x02:
            base = ((data[0] << 8) | data[1]) << 4
        elif rtype == 0x04:
            base = ((data[0] << 8) | data[1]) << 16
        elif rtype in (0x03, 0x05):
            pass
        else:
            raise HexError(f"line {lineno}: unsupported record type {rtype}")
    return mem


def load_hex(path) -> dict:
    with open(path, "r", encoding="ascii", errors="replace") as f:
        return parse_hex(f.read())


def to_flash_image(mem: dict, size: int) -> bytearray:
    """Flatten sparse memory into a flash image (blank = 0xFF)."""
    img = bytearray(b"\xff" * size)
    for addr, b in mem.items():
        if addr >= size:
            raise HexError(f"address 0x{addr:04x} is outside the {size // 1024} KB flash")
        img[addr] = b
    return img


def used_pages(mem: dict, page_size: int) -> list:
    return sorted({addr // page_size for addr in mem})


def dump_hex(image: bytes, base: int = 0, skip_blank=True) -> str:
    """Serialise bytes to Intel HEX (16-byte records, blank 0xFF lines skipped)."""
    out = []
    for off in range(0, len(image), 16):
        chunk = image[off:off + 16]
        if skip_blank and all(b == 0xFF for b in chunk):
            continue
        addr = base + off
        if addr > 0xFFFF:
            raise HexError("addresses above 64 KB are not supported")
        rec = bytes([len(chunk), addr >> 8, addr & 0xFF, 0]) + bytes(chunk)
        out.append(":" + (rec + bytes([(-sum(rec)) & 0xFF])).hex().upper())
    out.append(":00000001FF")
    return "\n".join(out) + "\n"
