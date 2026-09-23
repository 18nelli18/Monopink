#ifndef _NTAG_H_
#define _NTAG_H_

#include <stdint.h>
#include "platform.h"

/* NXP NTAG I2C plus (NT3H2111 / NT3H2211) on the label.
 * P1_0 powers it (VCC), P1_1 is its field-detect output (open drain). */

#define NTAG_ADDR_W   0xAA
#define NTAG_ADDR_R   0xAB

#define NTAG_REG_NC        0
#define NTAG_REG_LAST_NDEF 1
#define NTAG_REG_MIRROR    2
#define NTAG_REG_WDT_LS    3
#define NTAG_REG_WDT_MS    4
#define NTAG_REG_CLK_STR   5
#define NTAG_REG_NS        6

#define NS_RF_FIELD   0x01
#define NS_EEPROM_BSY 0x02
#define NS_RF_LOCKED  0x20
#define NS_I2C_LOCKED 0x40

void    ntag_power_on(void);
void    ntag_power_off(void);
uint8_t ntag_read_block(uint8_t block, XDATA uint8_t *buf);    /* 1 = ok */
uint8_t ntag_write_block(uint8_t block, XDATA uint8_t *buf);   /* 1 = ok */
uint8_t ntag_read_reg(uint8_t rega, uint8_t *val);               /* 1 = ok */
uint8_t ntag_write_reg(uint8_t rega, uint8_t mask, uint8_t val); /* 1 = ok */
void    ntag_unlock_i2c(void);   /* give the memory back to the NFC side */

/* FD level after discharging the pin: 1 = something pulls it high.
 * P1_0/P1_1 have no internal pull-up (CC2510 datasheet 12.1.8), so FD can
 * only wake us up if the board has a pull-up that works with the NTAG off. */
uint8_t ntag_fd_probe(void);

#endif
