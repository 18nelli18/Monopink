#ifndef _I2C_H_
#define _I2C_H_

#include <stdint.h>

/* Bit-banged I2C master on P0_4 (SDA) / P0_6 (SCL), open-drain style:
 * a line is driven low, or released (input + pull-up). */
void    i2c_init(void);
void    i2c_release(void);
void    i2c_start(void);
void    i2c_stop(void);
uint8_t i2c_write(uint8_t b);          /* returns 1 on ACK */
uint8_t i2c_read(uint8_t ack);

#endif
