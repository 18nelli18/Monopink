#ifndef _CLOCK_H_
#define _CLOCK_H_

#include <stdint.h>

void clock_init(void);
void clock_stop(void);
uint32_t millis(void);
void delay_ms(uint16_t ms);

#ifdef __SDCC
/* SDCC needs the ISR prototype visible from the file that holds main() */
void clock_isr(void) __interrupt(17);   /* WDT_VECTOR */
#endif

#endif
