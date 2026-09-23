/*
 * MonopInk NFC image codec - decoder.  Bit-exact with monopink/codec.py.
 * Context-adaptive binary range decoder (LZMA-style bit model, 11-bit
 * probabilities, adaptation shift 5).
 */
#include "codec.h"

#define WHITE 0
#define BLACK 1
#define RED   2

static uint8_t next_byte(CODEC_XDATA codec_state_t *st)
{
    return *st->src++;
}

static uint8_t get_bit(CODEC_XDATA codec_state_t *st, CODEC_XDATA uint16_t *p)
{
    CODEC_FAST uint16_t prob = *p;
    CODEC_FAST uint32_t bound = (st->rng >> 11) * prob;
    CODEC_FAST uint8_t b;

    if (st->code < bound) {
        st->rng = bound;
        *p = prob + ((2048 - prob) >> 5);
        b = 0;
    } else {
        st->code -= bound;
        st->rng -= bound;
        *p = prob - (prob >> 5);
        b = 1;
    }
    while (st->rng < 0x01000000UL) {
        st->rng <<= 8;
        st->code = (st->code << 8) | next_byte(st);
    }
    return b;
}

uint8_t codec_begin(CODEC_XDATA codec_state_t *st, CODEC_XDATA codec_mem_t *m, CODEC_SRC src)
{
    uint16_t i;
    uint8_t k;

    st->src = src;
    if (next_byte(st) != CODEC_FORMAT)
        return 0;
    st->rng = 0xFFFFFFFFUL;
    st->code = 0;
    for (k = 0; k < 5; k++)
        st->code = (st->code << 8) | next_byte(st);
    for (i = 0; i < 243; i++)
        m->p_ink[i] = 1024;
    for (i = 0; i < 81; i++)
        m->p_red[i] = 1024;
    for (i = 0; i < CODEC_W; i++) {
        m->prev[i] = WHITE;
        m->cur[i] = WHITE;
    }
    return 1;
}

void codec_row(CODEC_XDATA codec_state_t *st, CODEC_XDATA codec_mem_t *m)
{
    CODEC_FAST uint8_t x, a, b, c, d, e, v;
    CODEC_FAST uint8_t r;

    for (x = 0; x < CODEC_W; x++)
        m->prev[x] = m->cur[x];

    for (x = 0; x < CODEC_W; x++) {
        a = x >= 1 ? m->cur[x - 1] : WHITE;
        b = x >= 2 ? m->cur[x - 2] : WHITE;
        c = x >= 1 ? m->prev[x - 1] : WHITE;
        d = m->prev[x];
        e = (x + 1 < CODEC_W) ? m->prev[x + 1] : WHITE;
        r = ((a * 3 + b) * 3 + c) * 3 + d;          /* 0..80 */
        v = WHITE;
        if (get_bit(st, &m->p_ink[(uint16_t)r * 3 + e]))
            v = get_bit(st, &m->p_red[r]) ? RED : BLACK;
        m->cur[x] = v;
    }
}
