"""User settings, stored in data/config.json next to the tool."""
import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("MONOPINK_DATA", os.path.join(ROOT, "data"))
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_PINS = {"rst": 3, "dc": 4, "dd_i": 6, "dd_o": 7}

DEFAULTS = {
    "lang": "",                   # "" = auto (system / browser)
    "port": "auto",
    "pins": DEFAULT_PINS,
    "display": {"rotate180": False, "mirror": False},
    "image": {},
    "nfc_url": "",                # phone page (https), see docs/NFC.md
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _merge(DEFAULTS, json.load(f))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def update(changes):
    cfg = _merge(load(), changes)
    save(cfg)
    return cfg


def validate_pins(pins, allowed=None):
    """Return an error key or None.  DD_I may equal DD_O (single wire)."""
    try:
        rst, dc, ddi, ddo = (int(pins[k]) for k in ("rst", "dc", "dd_i", "dd_o"))
    except (KeyError, TypeError, ValueError):
        return "pins.invalid"
    for p in (rst, dc, ddi, ddo):
        if allowed is not None and p not in allowed:
            return "pins.not_on_header"
    if len({rst, dc, ddi}) < 3 or ddo in (rst, dc):
        return "pins.duplicate"
    return None
