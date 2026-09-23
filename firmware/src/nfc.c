/*
 * Picture upload through NFC (see nfc.h and docs/NFC.md).
 *
 * NTAG user memory (NFC pages 04h.., I2C blocks 01h..) holds a Type 2 Tag
 * NDEF TLV.  The phone writes:   03 len [record "x/mpk" + part]  FE
 * and we answer with:            03 len [record "x/mps" + status] FE
 *
 * Part payload (little endian):
 *   0 'M' 1 'K' 2 proto  3-4 image id  5 index  6 count  7-8 stream length
 *   9-10 stream CRC  11-12 part CRC  13-14 chunk size  15.. data
 * Part i is stored at staging + i * chunk.  Parts must arrive in order
 * (the status tells the phone which one comes next).
 */
#include "platform.h"
#include "nfc.h"
#include "ntag.h"
#include "flash.h"
#include "codec.h"
#include "clock.h"
#include "layout.h"

#define USER_BYTES     872          /* CC E1 10 6D 00 -> 0x6D * 8 */
#define MAX_PART_DATA  (USER_BYTES - 40)   /* margin: Android NDEF capacity */
#define PART_HDR       15
#define STATUS_LEN     16

#define WHITE 0
#define BLACK 1
#define RED   2

/* Receive state.  It lives in RAM (XDATA 0xF000-0xFDA1 is kept in PM2/PM3),
 * protected by a checksum; the flash copy (min. 1000 erase cycles) is only
 * written when a transfer ends, and used when the RAM copy is lost
 * (batteries removed). */
typedef struct {
    uint8_t magic0, magic1;          /* 'M' 'R' */
    uint8_t id_lo, id_hi;
    uint8_t count, next;
    uint8_t total_lo, total_hi;
    uint8_t scrc_lo, scrc_hi;
    uint8_t chunk_lo, chunk_hi;
    uint8_t state, err;
    uint8_t sum, pad1;               /* sum: RAM copy checksum */
} desc_t;

#define blk     XRAM(XRAM_NTAG_BLK)       /* 16-byte NTAG block cache */
#define work    XRAM(XRAM_WORK)           /* 32-byte work area        */
#define status  XRAM(XRAM_NFC_STATUS)
#define info    XRAM(XRAM_NFC_INFO)
#define desc    (*(XDATA desc_t *)XRAM(XRAM_NFC_DESC))
static XLOCAL uint8_t blk_no;
static XLOCAL uint8_t stored_new;

/* -------------------------------------------------------------- helpers */
static uint16_t crc16_byte(uint16_t crc, uint8_t b)
{
    XLOCAL uint8_t i;
    crc ^= (uint16_t)b << 8;
    for (i = 0; i < 8; i++)
        crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    return crc;
}

static uint8_t mem_byte(uint16_t off)
{
    uint8_t b = 1 + (uint8_t)(off >> 4);
    if (b != blk_no) {
        if (!ntag_read_block(b, blk)) {
            blk_no = 0xFF;
            return 0;
        }
        blk_no = b;
    }
    return blk[off & 15];
}

static uint16_t mem_u16(uint16_t off)
{
    return mem_byte(off) | ((uint16_t)mem_byte(off + 1) << 8);
}

static uint8_t desc_sum(void)
{
    XDATA uint8_t *d = XRAM(XRAM_NFC_DESC);
    XLOCAL uint8_t i, v = 0x5A;
    for (i = 0; i < 14; i++)
        v = (v << 1 | v >> 7) ^ d[i];
    return v;
}

static void desc_load(void)
{
    XLOCAL uint8_t i;
    flash_ptr_t p = FLASH_PTR(NFC_DESC_ADDR);
    XDATA uint8_t *dst = XRAM(XRAM_NFC_DESC);
    if (desc.magic0 == 'M' && desc.magic1 == 'R' && desc.sum == desc_sum())
        return;                      /* RAM copy survived the sleep */
    for (i = 0; i < sizeof(desc_t); i++)
        dst[i] = p[i];
    if (desc.magic0 != 'M' || desc.magic1 != 'R') {
        for (i = 0; i < sizeof(desc_t); i++)
            dst[i] = 0;
        desc.magic0 = 'M';
        desc.magic1 = 'R';
    }
    desc.sum = desc_sum();
}

static void desc_save(void)
{
    XDATA uint8_t *buf = XRAM(XRAM_BUF_A);
    XDATA uint8_t *src = XRAM(XRAM_NFC_DESC);
    flash_ptr_t p = FLASH_PTR(NFC_DESC_ADDR);
    XLOCAL uint16_t i;
    desc.magic0 = 'M';
    desc.magic1 = 'R';
    desc.sum = desc_sum();
    if (desc.state != NFC_ST_COMPLETE && desc.state != NFC_ST_ERROR)
        return;                      /* transfer in progress: RAM only */
    /* flash copy: only when a transfer ends (new id or new final state) */
    if (p[0] == 'M' && p[1] == 'R' && p[2] == desc.id_lo && p[3] == desc.id_hi &&
        p[12] == desc.state)
        return;
    for (i = 0; i < FLASH_PAGE; i++)
        buf[i] = i < sizeof(desc_t) ? src[i] : 0xFF;
    flash_write_page(NFC_DESC_ADDR, buf);
}

/* -------------------------------------------------------------- NTAG format */
/* Dynamic lock bytes (NFC page E2h = I2C block 38h, bytes 8-10).  Store
 * labels leave the factory with them set to FF 3F 7F: every page from 10h
 * on is read-only for phones (irreversible from NFC), so a phone could only
 * write 48 bytes.  From I2C they can be cleared (NT3H2111 datasheet 8.3.7).
 * Bytes 12-15 (AUTH0 page) are written back unchanged. */
static uint8_t unlock_dynamic(void)
{
    XDATA uint8_t *b = work;
    if (!ntag_read_block(0x38, b))
        return 0;
    if (b[8] == 0 && b[9] == 0 && b[10] == 0)
        return 1;
    b[8] = 0;
    b[9] = 0;
    b[10] = 0;
    return ntag_write_block(0x38, b);
}

static uint8_t ensure_format(void)
{
    XDATA uint8_t *b = work;
    XLOCAL uint8_t i;

    if (!unlock_dynamic())
        return 0;
    if (!ntag_read_block(0x00, b))
        return 0;
    if (b[12] == 0xE1 && b[13] == 0x10 && b[14] == 0x6D && b[15] == 0x00 &&
        b[10] == 0x00 && b[11] == 0x00)
        return 1;
    /* byte 0 of block 0 is the I2C address (reads as 04h, keep 55h) */
    b[0] = 0xAA;
    b[10] = 0x00;                   /* static lock bytes: unlocked */
    b[11] = 0x00;
    b[12] = 0xE1;                   /* capability container */
    b[13] = 0x10;
    b[14] = 0x6D;
    b[15] = 0x00;
    if (!ntag_write_block(0x00, b))
        return 0;
    for (i = 0; i < 16; i++)
        b[i] = 0;
    b[0] = 0x03;                    /* empty NDEF TLV + terminator */
    b[1] = 0x00;
    b[2] = 0xFE;
    return ntag_write_block(0x01, b);
}

static void build_status(void)
{
    status[0] = 'M';
    status[1] = 'S';
    status[2] = NFC_PROTO;
    status[3] = (FW_VERSION_MAJOR << 4) | FW_VERSION_MINOR;
    status[4] = desc.state;
    status[5] = desc.err;
    status[6] = desc.id_lo;
    status[7] = desc.id_hi;
    status[8] = desc.next;
    status[9] = desc.count;
    status[10] = MAX_PART_DATA & 0xFF;
    status[11] = MAX_PART_DATA >> 8;
    status[12] = NFC_STAGING_SIZE & 0xFF;
    status[13] = NFC_STAGING_SIZE >> 8;
    status[14] = 1;                  /* NDEF area: sector 0 (872 bytes) */
    status[15] = 0;
}

/* NDEF TLV + record header of the status, then the status' own magic */
static const uint8_t head[12] = {0x03, 0x18, 0xD2, 0x05, 0x10, 'x', '/', 'm', 'p', 's', 'M', 'S'};

/* write  03 18 [D2 05 10 "x/mps" status] FE  into blocks 1-2 if needed */
static void write_status(void)
{
    XDATA uint8_t *b = work;
    XLOCAL uint8_t i, n, same;

    build_status();
    for (n = 0; n < 2; n++) {
        for (i = 0; i < 16; i++) {
            uint8_t k = n * 16 + i;
            uint8_t v;
            if (k < 10)
                v = head[k];
            else if (k < 26)
                v = status[k - 10];
            else if (k == 26)
                v = 0xFE;
            else
                v = 0x00;
            b[16 + i] = v;
        }
        same = ntag_read_block(1 + n, b);
        for (i = 0; same && i < 16; i++)
            if (b[i] != b[16 + i])
                same = 0;
        if (!same)
            ntag_write_block(1 + n, b + 16);
    }
    blk_no = 0xFF;
}

/* -------------------------------------------------------------- staging */
/* copy len bytes of NTAG memory (from off) to flash at dst; returns CRC */
static uint16_t stage_copy(uint16_t dst, uint16_t off, uint16_t len)
{
    XDATA uint8_t *buf = XRAM(XRAM_BUF_A);
    XLOCAL uint16_t crc = 0xFFFF, page, o, lo;
    XLOCAL uint8_t v;

    while (len) {
        page = dst & 0xFC00;
        lo = dst & 0x3FF;
        flash_read(page, buf, FLASH_PAGE);
        for (o = lo; o < FLASH_PAGE && len; o++, len--) {
            v = mem_byte(off++);
            crc = crc16_byte(crc, v);
            buf[o] = v;
            dst++;
        }
        flash_write_page(page, buf);
    }
    return crc;
}

static uint16_t stream_crc(uint16_t total)
{
    XLOCAL uint16_t crc = 0xFFFF;
    flash_ptr_t p = FLASH_PTR(NFC_STAGING_ADDR);
    while (total--)
        crc = crc16_byte(crc, *p++);
    return crc;
}

/* -------------------------------------------------------------- decoding */
typedef struct {
    uint16_t page;
    uint16_t lo, hi;
    XDATA uint8_t *buf;
} pw_t;

static XLOCAL pw_t w_bw, w_r;

static void pw_flush(pw_t *w)
{
    XLOCAL uint16_t i;
    XLOCAL flash_ptr_t p;
    if (w->page == 0)
        return;
    p = FLASH_PTR(w->page);
    for (i = 0; i < w->lo; i++)
        w->buf[i] = p[i];
    for (i = w->hi; i < FLASH_PAGE; i++)
        w->buf[i] = p[i];
    flash_write_page(w->page, w->buf);
    w->page = 0;
}

static void pw_put(pw_t *w, uint16_t addr, uint8_t v)
{
    XLOCAL uint16_t page = addr & 0xFC00;
    XLOCAL uint16_t o = addr & 0x3FF;
    if (page != w->page) {
        pw_flush(w);
        w->page = page;
        w->lo = o;
    }
    w->buf[o] = v;
    w->hi = o + 1;
}

static uint8_t decode_image(void)
{
    XDATA codec_state_t *st = (XDATA codec_state_t *)XRAM(XRAM_MISC);
    XDATA codec_mem_t *m = (XDATA codec_mem_t *)XRAM(XRAM_CODEC);
    XLOCAL uint16_t y, a;
    XLOCAL uint8_t xb, bit, v, bw, r;
    XDATA uint8_t *px;

    if (!codec_begin(st, m, FLASH_PTR(NFC_STAGING_ADDR)))
        return 0;
    w_bw.page = 0;
    w_bw.buf = XRAM(XRAM_BUF_A);
    w_r.page = 0;
    w_r.buf = XRAM(XRAM_BUF_B);
    for (y = 0; y < EPD_HEIGHT; y++) {
        codec_row(st, m);
        px = m->cur;
        a = y * (EPD_WIDTH / 8);
        for (xb = 0; xb < EPD_WIDTH / 8; xb++) {
            bw = 0;
            r = 0;
            for (bit = 0; bit < 8; bit++) {
                v = *px++;
                bw = (bw << 1) | (v != BLACK ? 1 : 0);
                r = (r << 1) | (v != RED ? 1 : 0);
            }
            pw_put(&w_bw, IMG_BW_ADDR + a + xb, bw);
            pw_put(&w_r, IMG_R_ADDR + a + xb, r);
        }
    }
    pw_flush(&w_bw);
    pw_flush(&w_r);
    return 1;
}

/* -------------------------------------------------------------- protocol */
static uint8_t handle_part(uint16_t p, uint16_t plen)
{
    XLOCAL uint16_t id, total, scrc, pcrc, chunk, dlen, expect, crc;
    XLOCAL uint8_t idx, count, same;

    if (plen < PART_HDR || mem_byte(p) != 'M' || mem_byte(p + 1) != 'K' ||
        mem_byte(p + 2) != NFC_PROTO)
        return NFC_E_HEADER;
    id = mem_u16(p + 3);
    idx = mem_byte(p + 5);
    count = mem_byte(p + 6);
    total = mem_u16(p + 7);
    scrc = mem_u16(p + 9);
    pcrc = mem_u16(p + 11);
    chunk = mem_u16(p + 13);
    dlen = plen - PART_HDR;
    if (total > NFC_STAGING_SIZE)
        return NFC_E_TOO_BIG;
    if (count == 0 || idx >= count || chunk == 0 || chunk > MAX_PART_DATA ||
        (uint32_t)chunk * (count - 1) >= total || (uint32_t)chunk * count < total)
        return NFC_E_HEADER;
    expect = (idx + 1 < count) ? chunk : total - chunk * (count - 1);
    if (dlen != expect)
        return NFC_E_HEADER;

    same = desc.id_lo == (id & 0xFF) && desc.id_hi == (id >> 8) && desc.count == count;
    if (idx == 0 && same && desc.state == NFC_ST_COMPLETE)
        return NFC_OK;                 /* this picture is already displayed */
    if (idx == 0 && !(same && desc.state == NFC_ST_RECEIVING)) {
        /* first part of a new transfer: forget the previous one */
        desc.state = NFC_ST_RECEIVING;
        desc.id_lo = id & 0xFF;
        desc.id_hi = id >> 8;
        desc.count = count;
        desc.next = 0;
        desc.total_lo = total & 0xFF;
        desc.total_hi = total >> 8;
        desc.scrc_lo = scrc & 0xFF;
        desc.scrc_hi = scrc >> 8;
        desc.chunk_lo = chunk & 0xFF;
        desc.chunk_hi = chunk >> 8;
    } else if (!same || desc.state != NFC_ST_RECEIVING) {
        return NFC_E_ORDER;
    }
    if (idx < desc.next)
        return NFC_OK;                 /* duplicate, already stored */
    if (idx > desc.next)
        return NFC_E_ORDER;

    crc = stage_copy(NFC_STAGING_ADDR + chunk * idx, p + PART_HDR, dlen);
    if (crc != pcrc)
        return NFC_E_PART_CRC;
    desc.next = idx + 1;
    desc.state = NFC_ST_RECEIVING;
    stored_new = 1;
    return NFC_OK;
}

/* find our part record in the NDEF message: returns payload offset or 0 */
static uint16_t find_part(uint16_t *plen)
{
    XLOCAL uint16_t off = 0, len, end, p, pl;
    XLOCAL uint8_t t, hdr, tl, il;

    /* TLVs */
    for (;;) {
        if (off >= USER_BYTES)
            return 0;
        t = mem_byte(off++);
        if (t == 0x00)
            continue;
        if (t == 0xFE)
            return 0;
        len = mem_byte(off++);
        if (len == 0xFF) {
            len = ((uint16_t)mem_byte(off) << 8) | mem_byte(off + 1);
            off += 2;
        }
        if (t == 0x03)
            break;
        off += len;
    }
    end = off + len;
    if (end > USER_BYTES)
        return 0;
    /* records */
    while (off + 3 <= end) {
        hdr = mem_byte(off);
        tl = mem_byte(off + 1);
        if (hdr & 0x10) {                         /* SR */
            pl = mem_byte(off + 2);
            p = off + 3;
        } else {
            if (mem_byte(off + 2) || mem_byte(off + 3))
                return 0;
            pl = ((uint16_t)mem_byte(off + 4) << 8) | mem_byte(off + 5);
            p = off + 6;
        }
        il = 0;
        if (hdr & 0x08)                           /* IL */
            il = mem_byte(p++);
        if ((hdr & 0x07) == 0x02 && tl == 5 && mem_byte(p) == 'x' &&
            mem_byte(p + 1) == '/' && mem_byte(p + 2) == 'm' &&
            mem_byte(p + 3) == 'p' && mem_byte(p + 4) == 'k') {
            *plen = pl;
            return p + tl + il;
        }
        off = p + tl + il + pl;
        if (hdr & 0x40)                           /* ME */
            break;
    }
    return 0;
}

static uint8_t process(void)
{
    XLOCAL uint16_t p, plen, total;
    XLOCAL uint8_t err;

    blk_no = 0xFF;
    stored_new = 0;
    desc_load();
    if (!ensure_format()) {
        info[0] = NFC_E_CHIP;
        return NFC_FAILED;
    }
    p = find_part(&plen);
    info[1] = p & 0xFF;
    info[2] = p >> 8;
    info[3] = plen & 0xFF;
    info[4] = plen >> 8;
    if (!p) {
        write_status();
        return NFC_NOTHING;
    }

    err = handle_part(p, plen);
    desc.err = err;
    if (err == NFC_E_ORDER && desc.state != NFC_ST_RECEIVING)
        desc.next = 0;
    if (err == NFC_OK && desc.next == desc.count && desc.state == NFC_ST_RECEIVING) {
        total = desc.total_lo | ((uint16_t)desc.total_hi << 8);
        if (stream_crc(total) != (desc.scrc_lo | ((uint16_t)desc.scrc_hi << 8)))
            desc.err = NFC_E_STREAM_CRC;
        else if (!decode_image())
            desc.err = NFC_E_DECODE;
        desc.state = desc.err ? NFC_ST_ERROR : NFC_ST_COMPLETE;
    }
    desc_save();
    write_status();
    info[0] = desc.err;
    if (desc.err)
        return NFC_FAILED;
    if (!stored_new)
        return NFC_NOTHING;
    return desc.state == NFC_ST_COMPLETE ? NFC_IMAGE : NFC_PART_OK;
}

/* -------------------------------------------------------------- entry points */
/* polling mode: the NTAG is powered, watch its RF_FIELD_PRESENT flag */
static uint8_t wait_field_gone_reg(void)
{
    XLOCAL uint16_t t;
    XLOCAL uint8_t quiet = 0;
    uint8_t v;
    for (t = 0; t < 3000; t++) {        /* 60 s max */
        if (!ntag_read_reg(NTAG_REG_NS, &v))
            return 1;                   /* chip silent: process() reports it */
        if (v & NS_RF_FIELD)
            quiet = 0;
        else if (++quiet >= 5)          /* 100 ms without field */
            return 1;
        delay_ms(20);
    }
    return 0;
}

uint8_t nfc_poll(void)
{
    XDATA uint8_t *b = work;
    XLOCAL uint8_t i, r = 0;
    uint8_t v;
    ntag_power_on();
    if (ntag_read_reg(NTAG_REG_NS, &v)) {
        if (v & NS_RF_FIELD) {
            r = 1;                      /* a phone is here */
        } else if (ntag_read_block(0x01, b)) {
            for (i = 0; i < 12 && b[i] == head[i]; i++)
                ;
            r = i < 12;                 /* our status was overwritten */
        }
    }
    ntag_unlock_i2c();
    ntag_power_off();
    return r;
}

#ifdef __SDCC
/* FD (P1_1) is pulled low by the NTAG while a phone's field is present */
static uint8_t wait_field_gone(void)
{
    XLOCAL uint16_t quiet = 0, t;
    for (t = 0; t < 6000; t++) {        /* 60 s max */
        if (P1_1) {
            if (++quiet >= 10)          /* 100 ms without field */
                return 1;
        } else {
            quiet = 0;
        }
        delay_ms(10);
    }
    return 0;
}
#else
static uint8_t wait_field_gone(void) { return 1; }
#endif

uint8_t nfc_session(uint8_t wait)
{
    XLOCAL uint8_t r;
    XLOCAL uint8_t i;
    for (i = 0; i < 16; i++)
        info[i] = 0;
    if (wait == NFC_WAIT_FD && !wait_field_gone())
        return NFC_TIMEOUT;
    ntag_power_on();
    if (wait == NFC_WAIT_POLL && !wait_field_gone_reg()) {
        ntag_power_off();
        return NFC_TIMEOUT;
    }
    r = process();
    ntag_unlock_i2c();
    ntag_power_off();
    return r;
}

void nfc_prepare(void)
{
    ntag_power_on();
    blk_no = 0xFF;
    desc_load();
    if (ensure_format()) {
        /* keep a pending transfer, otherwise announce "ready" */
        write_status();
    }
    ntag_unlock_i2c();
    ntag_power_off();
}

uint8_t nfc_test_phone_write(uint16_t len)
{
    XDATA uint8_t *src = XRAM(XRAM_BUF_B);
    XDATA uint8_t *b = work;
    XLOCAL uint16_t off;
    XLOCAL uint8_t i;

    if (len > USER_BYTES)
        len = USER_BYTES;
    ntag_power_on();
    ensure_format();
    for (off = 0; off < len; off += 16) {
        for (i = 0; i < 16; i++)
            b[i] = (off + i < len) ? src[off + i] : 0;
        ntag_write_block(1 + (off >> 4), b);
    }
    ntag_unlock_i2c();
    ntag_power_off();
    return nfc_session(NFC_WAIT_NONE);
}
