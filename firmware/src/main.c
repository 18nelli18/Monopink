/*
 * MonopInk display firmware for the SES-imagotag VUSION 2.6 BWR (GL420)
 * electronic shelf label (TI CC2510F32 + IL0373 e-paper, 152 x 296 BWR).
 *
 * At every boot: power the panel, send the image stored at a fixed flash
 * address (see layout.h), refresh once, switch the panel off, then sleep.
 * The picture stays on the e-paper without any power.  A phone can send a
 * new picture over NFC (see nfc.h): the label sleeps in PM3 until the NFC
 * chip's field-detect line wakes it up, or - if the board gives that line
 * no pull-up - wakes up every 2 s from PM2 to look at the NFC chip.
 *
 * Progress is written to a mailbox in RAM so the host tool can follow the
 * refresh through the debug port and report problems.
 */
#include <cc2510fx.h>
#include <stdint.h>
#include "layout.h"
#include "clock.h"
#include "epd.h"
#include "nfcdiag.h"
#include "nfc.h"
#include "ntag.h"

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
#define MODE_WATCHED  1     /* "MPHD": debug-mode run, host watching          */
#define MODE_DIAG     2     /* "MPNR": normal boot test, no PM3 at the end     */
#define MODE_NFCDIAG  3     /* "MPNF": dump the NFC chip state, no display     */
#define MODE_NFCTEST  4     /* "MPNW": host plays the phone (debug mode)       */

static uint8_t boot_mode(void)
{
    if (mailbox[0] != 'M' || mailbox[1] != 'P')
        return MODE_NORMAL;
    if (mailbox[2] == 'H' && mailbox[3] == 'D')
        return MODE_WATCHED;
    if (mailbox[2] == 'N' && mailbox[3] == 'R')
        return MODE_DIAG;
    if (mailbox[2] == 'N' && mailbox[3] == 'F')
        return MODE_NFCDIAG;
    if (mailbox[2] == 'N' && mailbox[3] == 'W')
        return MODE_NFCTEST;
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

static void enter_pm3(void)
{
    SLEEP = (SLEEP & ~0x03) | 0x03;      /* PM3 */
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

/* NTAG field detect (FD, open drain) on P1_1: low while a phone is near.
 * It works from the phone's field alone, so the NTAG itself stays off. */
void p1_isr(void) __interrupt(P1INT_VECTOR)
{
    P1IFG = 0;
    P1IF = 0;
}

void st_isr(void) __interrupt(ST_VECTOR)
{
    WORIRQ = 0x10;                       /* keep EVENT0_MASK, clear the flag */
    STIF = 0;
}

static void wait_32k_edge(void)
{
    uint8_t t = WORTIME0;
    while (t == WORTIME0) {
    }
}

/* Polling mode: PM2 for ~2 s, woken up by the sleep timer (clocked by the
 * low power RC oscillator, 26 MHz / 750; resolution 32 periods = 0.92 ms). */
#define POLL_EVENT0  2167

static void sleep_poll(void)
{
    low_power_io();
    P1_1 = 0;                            /* FD unused: no floating input */
    P1DIR |= 0x02;
    clock_stop();
    MEMCTR |= 0x02;
    WORIRQ = 0x10;
    STIF = 0;
    STIE = 1;
    EA = 1;
    WORCTL = 0x01 | 0x04;                /* resolution 2^5, reset the timer */
    wait_32k_edge();
    wait_32k_edge();
    WOREVT1 = POLL_EVENT0 >> 8;
    WOREVT0 = POLL_EVENT0 & 0xFF;
    SLEEP = (SLEEP & ~0x03) | 0x02;      /* PM2 */
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
    STIE = 0;
    MEMCTR &= ~0x02;
    clock_init();
}

static void sleep_until_phone(void)
{
    low_power_io();
    P1DIR &= ~0x02;                      /* FD: input (pulled up on the board) */
    PICTL |= 0x02;                       /* port 1: falling edge */
    P1IFG = 0;
    P1IF = 0;
    P1IEN |= 0x02;
    IEN2 |= 0x10;                        /* P1IE */
    clock_stop();
    MEMCTR |= 0x02;
    EA = 1;
    while (P1_1)                         /* no field: sleep */
        enter_pm3();
    P1IEN &= ~0x02;
    IEN2 &= ~0x10;
    MEMCTR &= ~0x02;
    clock_init();
}

static uint8_t show_image(void)
{
    uint32_t t0, t1;
    uint8_t err;

    mailbox[MB_T_REFRESH_L] = 0;
    mailbox[MB_T_REFRESH_H] = 0;
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
    return mailbox[MB_ERROR];
}

static void hold(uint8_t state)
{
    set_state(state);
    for (;;) {
    }
}

void main(void)
{
    uint8_t mode, r, timeouts, fd_wake;
    uint16_t len;

    /* The RAM survives a reset: read the host's request once and clear it,
     * so that a later plain reset boots normally (and ends in PM3). */
    mode = boot_mode();
    len = mailbox[12] | ((uint16_t)mailbox[13] << 8);
    mailbox[0] = 0; mailbox[1] = 0; mailbox[2] = 0; mailbox[3] = 0;
    mailbox[MB_BOOTS]++;
    mailbox[MB_RESET_CAUSE] = SLEEP;
    if (mode == MODE_NORMAL || mode == MODE_DIAG)
        led_off();

    set_state(ST_BOOT);
    mailbox[MB_ERROR] = ERR_NONE;
    mailbox[MB_FW_VERSION] = (FW_VERSION_MAJOR << 4) | FW_VERSION_MINOR;

    clock_init();

    if (mode == MODE_NFCDIAG) {
        nfc_diag();
        hold(ST_NFC_DIAG_DONE);
    }
    if (mode == MODE_NFCTEST) {
        r = nfc_test_phone_write(len);
        mailbox[MB_NFC_RESULT] = r;
        if (r == NFC_IMAGE)
            show_image();
        hold(ST_NFC_DONE);
    }

    show_image();
    if (mode != MODE_NORMAL)
        hold(ST_IDLE_HOLD);

    /* Normal life: sleep until a phone comes with a new picture. */
    nfc_prepare();
    low_power_io();
    fd_wake = ntag_fd_probe();
    timeouts = 0;
    for (;;) {
        if (fd_wake && timeouts >= 3)    /* FD stuck low: poll instead */
            fd_wake = 0;
        if (fd_wake) {
            sleep_until_phone();
            r = nfc_session(NFC_WAIT_FD);
        } else {
            sleep_poll();
            if (!nfc_poll())
                continue;
            r = nfc_session(NFC_WAIT_POLL);
        }
        if (r == NFC_TIMEOUT)
            timeouts++;
        else
            timeouts = 0;
        if (r == NFC_IMAGE)
            show_image();
    }
}
