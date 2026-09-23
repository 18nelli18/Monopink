#ifndef _CODEC_H_
#define _CODEC_H_

/* MonopInk NFC image codec, decoder side (see monopink/codec.py).
 * Portable C: compiled by SDCC for the CC2510 and by a native compiler
 * for the tests (tests/native/). */

#include <stdint.h>

#ifdef __SDCC
#define CODEC_SRC   const __code uint8_t *
#define CODEC_XDATA __xdata
#define CODEC_FAST              /* (was __data: internal RAM is too small) */
#else
#define CODEC_SRC   const uint8_t *
#define CODEC_XDATA
#define CODEC_FAST
#endif

#define CODEC_W       152
#define CODEC_H       296
#define CODEC_FORMAT  0x01

typedef struct {
    CODEC_SRC src;
    uint32_t rng;
    uint32_t code;
} codec_state_t;

/* tables and rows live where the caller wants (fixed XDATA on the CC2510) */
typedef struct {
    uint16_t p_ink[243];
    uint16_t p_red[81];
    uint8_t prev[CODEC_W];
    uint8_t cur[CODEC_W];
} codec_mem_t;

/* 1 = ok, 0 = unknown format */
uint8_t codec_begin(CODEC_XDATA codec_state_t *st, CODEC_XDATA codec_mem_t *m, CODEC_SRC src);
/* decode the next row into m->cur (after moving the previous one to m->prev) */
void codec_row(CODEC_XDATA codec_state_t *st, CODEC_XDATA codec_mem_t *m);

#endif
