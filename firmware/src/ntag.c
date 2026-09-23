/*
 * NTAG I2C plus driver (datasheet NT3H2111_2211 rev 3.6).
 *   memory: 16-byte blocks, READ = [SA W][MEMA] P [SA R][16 bytes]
 *   session registers: block FEh, READ/WRITE REGISTER with REGA (+MASK)
 */
#include <cc2510fx.h>
#include "ntag.h"
#include "i2c.h"
#include "clock.h"

void ntag_power_on(void)
{
    P1_0 = 1;
    P1DIR |= 0x01;
    i2c_init();
    delay_ms(5);
}

void ntag_power_off(void)
{
    i2c_release();
    P1_0 = 0;
    P1DIR |= 0x01;
}

uint8_t ntag_read_block(uint8_t block, XDATA uint8_t *buf)
{
    uint8_t i;
    i2c_start();
    if (!i2c_write(NTAG_ADDR_W) || !i2c_write(block)) {
        i2c_stop();
        return 0;
    }
    i2c_stop();
    i2c_start();
    if (!i2c_write(NTAG_ADDR_R)) {
        i2c_stop();
        return 0;
    }
    for (i = 0; i < 16; i++)
        buf[i] = i2c_read(i < 15);
    i2c_stop();
    return 1;
}

uint8_t ntag_write_block(uint8_t block, XDATA uint8_t *buf)
{
    uint8_t i, ok;
    i2c_start();
    ok = i2c_write(NTAG_ADDR_W) && i2c_write(block);
    for (i = 0; ok && i < 16; i++)
        ok = i2c_write(buf[i]);
    i2c_stop();
    delay_ms(6);                       /* EEPROM programming time (~4 ms) */
    return ok;
}

uint8_t ntag_read_reg(uint8_t rega, uint8_t *val)
{
    i2c_start();
    if (!i2c_write(NTAG_ADDR_W) || !i2c_write(0xFE) || !i2c_write(rega)) {
        i2c_stop();
        return 0;
    }
    i2c_stop();
    i2c_start();
    if (!i2c_write(NTAG_ADDR_R)) {
        i2c_stop();
        return 0;
    }
    *val = i2c_read(0);
    i2c_stop();
    return 1;
}

uint8_t ntag_write_reg(uint8_t rega, uint8_t mask, uint8_t val)
{
    uint8_t ok;
    i2c_start();
    ok = i2c_write(NTAG_ADDR_W) && i2c_write(0xFE) && i2c_write(rega) &&
         i2c_write(mask) && i2c_write(val);
    i2c_stop();
    return ok;
}

void ntag_unlock_i2c(void)
{
    ntag_write_reg(NTAG_REG_NS, NS_I2C_LOCKED, 0x00);
}

uint8_t ntag_fd_probe(void)
{
    P1_1 = 0;
    P1DIR |= 0x02;                     /* discharge the line */
    delay_ms(1);
    P1DIR &= ~0x02;                    /* release, let a pull-up recharge it */
    delay_ms(3);
    return P1_1;
}
