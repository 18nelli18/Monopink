/*
 * Bit-banged I2C master (the CC2510 has no I2C peripheral).
 * SDA = P0_4, SCL = P0_6, ~50 kHz.  The NTAG may stretch the clock.
 */
#include <cc2510fx.h>
#include "i2c.h"

#define SDA_BIT  (1 << 4)
#define SCL_BIT  (1 << 6)

static void dly(void)
{
    volatile uint8_t i;
    for (i = 0; i < 6; i++) {
    }
}

static void sda_low(void)  { P0_4 = 0; P0DIR |= SDA_BIT; }
static void sda_high(void) { P0DIR &= ~SDA_BIT; }
static void scl_low(void)  { P0_6 = 0; P0DIR |= SCL_BIT; }

static void scl_high(void)
{
    uint16_t guard = 2000;
    P0DIR &= ~SCL_BIT;
    while (!P0_6 && --guard) {       /* clock stretching */
    }
}

void i2c_init(void)
{
    P0SEL &= ~(SDA_BIT | SCL_BIT);
    P0INP &= ~(SDA_BIT | SCL_BIT);   /* pull-ups on (P2INP.PDUP0 = 0) */
    sda_high();
    scl_high();
}

void i2c_release(void)
{
    /* NFC chip unpowered: drive both lines low (no back-powering) */
    P0_4 = 0;
    P0_6 = 0;
    P0DIR |= SDA_BIT | SCL_BIT;
}

void i2c_start(void)
{
    sda_high();
    scl_high();
    dly();
    sda_low();
    dly();
    scl_low();
    dly();
}

void i2c_stop(void)
{
    sda_low();
    dly();
    scl_high();
    dly();
    sda_high();
    dly();
}

uint8_t i2c_write(uint8_t b)
{
    uint8_t i, ack;
    for (i = 0; i < 8; i++) {
        if (b & 0x80)
            sda_high();
        else
            sda_low();
        b <<= 1;
        dly();
        scl_high();
        dly();
        scl_low();
    }
    sda_high();
    dly();
    scl_high();
    dly();
    ack = P0_4 ? 0 : 1;
    scl_low();
    dly();
    return ack;
}

uint8_t i2c_read(uint8_t ack)
{
    uint8_t i, b = 0;
    sda_high();
    for (i = 0; i < 8; i++) {
        dly();
        scl_high();
        dly();
        b = (b << 1) | (P0_4 ? 1 : 0);
        scl_low();
    }
    if (ack)
        sda_low();
    else
        sda_high();
    dly();
    scl_high();
    dly();
    scl_low();
    sda_high();
    dly();
    return b;
}
