/*
 * MonopInk display firmware for the SES-imagotag VUSION 2.6 BWR (GL420)
 * electronic shelf label (TI CC2510F32 + IL0373 e-paper, 152 x 296 BWR).
 *
 * At every boot: power the panel, send the image stored at a fixed flash
 * address (see layout.h), refresh once, switch the panel off, then put the
 * CC2510 into PM3 (deepest sleep, only a reset wakes it up).  The picture
 * stays on the e-paper without any power.
 *
 * Progress is written to a mailbox in RAM so the host tool can follow the
 * refresh through the debug port and report problems.
 */
#include <cc2510fx.h>
#include <stdint.h>
#include "layout.h"
#include "clock.h"
#include "epd.h"

/* Identification block read by the host to detect this firmware */
__code __at (FW_INFO_ADDR) const uint8_t fw_info[16] = {
    'M', 'O', 'N', 'O', 'P', 'I', 'N', 'K',
    FW_VERSION_MAJOR, FW_VERSION_MINOR, LAYOUT_VERSION,
    EPD_WIDTH, (EPD_HEIGHT >> 8), (EPD_HEIGHT & 0xFF), 0x00, 0x00
};

__xdata __at (MAILBOX_ADDR) volatile uint8_t mailbox[16];

static void set_state(uint8_t s)
{
    mailbox[MB_STATE] = s;
}

#define MODE_NORMAL   0
#define MODE_WATCHED  1     /* "MPHD": debug-mode run, host watching */
#define MODE_DIAG     2     /* "MPNR": normal boot test, no PM3 at the end */

static uint8_t boot_mode(void)
{
    if (mailbox[0] != 'M' || mailbox[1] != 'P')
        return MODE_NORMAL;
    if (mailbox[2] == 'H' && mailbox[3] == 'D')
        return MODE_WATCHED;
    if (mailbox[2] == 'N' && mailbox[3] == 'R')
        return MODE_DIAG;
    return MODE_NORMAL;
}

/* P2_1 = white LED, P2_2 = LED boost converter enable.  After reset they
 * are inputs with pull-ups, which switches the boost converter ON: on the
 * real label this loads the supply so much that the e-paper never powers up
 * (BUSY stuck).  Drive both low before touching the panel.
 * These are also the debug lines DD/DC: never touch them while the host is
 * attached in debug mode (it drives DC low itself). */
static void led_off(void)
{
    P2_1 = 0; P2_2 = 0;
    P2DIR |= (1 << 1) | (1 << 2);
}

static void low_power_io(void)
{
    /* NFC chip + SPI flash supply (P1_0) off, their data lines low */
    P1_0 = 0; P1_4 = 0; P1_5 = 0; P1_6 = 0; P1_7 = 0;
    P1DIR |= (1 << 0) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7);
    P0_4 = 0; P0_6 = 0;
    P0DIR |= (1 << 4) | (1 << 6);
    P1_3 = 0;                    /* BUSY: the panel is off, no floating input */
    P1DIR |= (1 << 3);
    led_off();
}

static void enter_pm3_forever(void)
{
    EA = 0;
    clock_stop();
    MEMCTR |= 0x02;                      /* flash cache off before PM2/3 */
    for (;;) {
        SLEEP = (SLEEP & ~0x03) | 0x03;  /* PM3 */
        __asm
            nop
            nop
            nop
        __endasm;
        if (SLEEP & 0x03) {
            PCON |= 0x01;
            __asm
                nop
            __endasm;
        }
    }
}

void main(void)
{
    uint32_t t0, t1;
    uint8_t err;
    uint8_t mode;

    /* The RAM survives a reset: read the host's request once and clear it,
     * so that a later plain reset boots normally (and ends in PM3). */
    mode = boot_mode();
    mailbox[0] = 0; mailbox[1] = 0; mailbox[2] = 0; mailbox[3] = 0;
    mailbox[MB_BOOTS]++;
    mailbox[MB_RESET_CAUSE] = SLEEP;
    if (mode != MODE_WATCHED)
        led_off();

    set_state(ST_BOOT);
    mailbox[MB_ERROR] = ERR_NONE;
    mailbox[MB_FW_VERSION] = (FW_VERSION_MAJOR << 4) | FW_VERSION_MINOR;
    mailbox[MB_T_REFRESH_L] = 0;
    mailbox[MB_T_REFRESH_H] = 0;

    clock_init();

    err = epd_power_on();
    mailbox[MB_BUSY_AT_ON] = epd_busy_before_on;
    mailbox[MB_T_PWRON_L] = epd_last_wait_ms & 0xFF;
    mailbox[MB_T_PWRON_H] = epd_last_wait_ms >> 8;
    set_state(ST_EPD_READY);
    if (err == ERR_NONE) {
        epd_write_image();
        set_state(ST_DATA_SENT);

        t0 = millis();
        set_state(ST_REFRESHING);
        err = epd_refresh();
        t1 = millis() - t0;
        if (t1 > 0xFFFF)
            t1 = 0xFFFF;
        mailbox[MB_T_REFRESH_L] = t1 & 0xFF;
        mailbox[MB_T_REFRESH_H] = (t1 >> 8) & 0xFF;
        set_state(ST_REFRESH_DONE);
    }
    mailbox[MB_ERROR] = err;

    err = epd_power_off();
    if (mailbox[MB_ERROR] == ERR_NONE)
        mailbox[MB_ERROR] = err;
    t1 = millis();
    if (t1 > 0xFFFF)
        t1 = 0xFFFF;
    mailbox[MB_T_TOTAL_L] = t1 & 0xFF;
    mailbox[MB_T_TOTAL_H] = (t1 >> 8) & 0xFF;
    set_state(ST_EPD_OFF);

    if (mode != MODE_NORMAL) {
        /* Host session: stay awake so the host can read the mailbox. */
        set_state(ST_IDLE_HOLD);
        for (;;) {
        }
    }

    low_power_io();
    enter_pm3_forever();
}
