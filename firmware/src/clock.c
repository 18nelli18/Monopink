/*
 * Millisecond tick from the watchdog timer running in timer mode
 * (32.768 kHz RC oscillator / 64 = one interrupt every ~1.95 ms).
 */
#include <cc2510fx.h>
#include "clock.h"

static volatile uint32_t ticks_ms = 0;

void clock_isr(void) __interrupt(WDT_VECTOR)
{
    ticks_ms += 2;
    WDTIF = 0;
}

void clock_init(void)
{
    WDCTL = 0x08 | 0x04 | 0x03;   /* EN, timer mode, period = 64 clocks */
    IEN2 |= 0x20;                 /* WDTIE */
    EA = 1;
}

void clock_stop(void)
{
    IEN2 &= ~0x20;
    WDCTL = 0x04;                 /* timer mode, disabled */
}

uint32_t millis(void)
{
    uint32_t v;
    uint8_t ea = EA;
    EA = 0;
    v = ticks_ms;
    EA = ea;
    return v;
}

void delay_ms(uint16_t ms)
{
    uint32_t start = millis();
    while ((millis() - start) < ms) {
    }
}
