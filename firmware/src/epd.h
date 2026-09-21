#ifndef _EPD_H_
#define _EPD_H_

#include <stdint.h>

/* All functions return ERR_NONE (0) or an ERR_* code from layout.h */
extern uint16_t epd_last_wait_ms;     /* diagnostics */
extern uint8_t epd_busy_before_on;
void    epd_hold_off(void);
uint8_t epd_power_on(void);
void    epd_write_image(void);
uint8_t epd_refresh(void);
uint8_t epd_power_off(void);

#endif
