/*
 * Flash self-programming.  Same routine as the one the host runs through the
 * debug port (TI SWRA124, proven on this chip), but ending with a wait for
 * the flash controller and a RET so the firmware can call it.
 */
#include <cc2510fx.h>
#include "flash.h"
#include "layout.h"

__xdata __at (XRAM_FLASH_ROUTINE) uint8_t routine[48];

static const __code uint8_t routine_template[] = {
    0x75, 0xAD, 0x00,               /* 0  MOV FADDRH,#page*2      (patched) */
    0x75, 0xAC, 0x00,               /* 3  MOV FADDRL,#0                     */
    0x75, 0xAE, 0x01,               /* 6  MOV FLC,#01  erase                */
    0xE5, 0xAE, 0x20, 0xE7, 0xFB,   /* 9  wait FLC.BUSY                     */
    0x90, 0x00, 0x00,               /* 14 MOV DPTR,#src           (patched) */
    0x7F, 0x02,                     /* 17 MOV R7,#2                          */
    0x7E, 0x00,                     /* 19 MOV R6,#0     (512 words)          */
    0x75, 0xAE, 0x02,               /* 21 MOV FLC,#02  write                */
    0x7D, 0x02,                     /* 24 loop: MOV R5,#2                    */
    0xE0,                           /* 26 word: MOVX A,@DPTR                 */
    0xA3,                           /* 27 INC DPTR                           */
    0xF5, 0xAF,                     /* 28 MOV FWDATA,A                       */
    0xDD, 0xFA,                     /* 30 DJNZ R5,word                       */
    0xE5, 0xAE, 0x20, 0xE6, 0xFB,   /* 32 wait FLC.SWBSY                     */
    0xDE, 0xF1,                     /* 37 DJNZ R6,loop                       */
    0xDF, 0xEF,                     /* 39 DJNZ R7,loop                       */
    0xE5, 0xAE, 0x20, 0xE7, 0xFB,   /* 41 wait FLC.BUSY                      */
    0x22                            /* 46 RET                                */
};

void flash_write_page(uint16_t addr, XDATA uint8_t *src)
{
    uint8_t i, ea, memctr;
    void (*run)(void) = (void (*)(void))XRAM_FLASH_ROUTINE;

    for (i = 0; i < sizeof(routine_template); i++)
        routine[i] = routine_template[i];
    routine[2] = (uint8_t)((addr >> 9) & 0x7E); /* word address >> 8, page aligned */
    routine[15] = (uint16_t)src >> 8;
    routine[16] = (uint16_t)src & 0xFF;

    ea = EA;
    EA = 0;
    memctr = MEMCTR;
    MEMCTR |= 0x02;                  /* flash cache off */
    run();
    MEMCTR = memctr;
    EA = ea;
}

void flash_read(uint16_t addr, XDATA uint8_t *dst, uint16_t len)
{
    const __code uint8_t *p = (const __code uint8_t *)addr;
    while (len--)
        *dst++ = *p++;
}
