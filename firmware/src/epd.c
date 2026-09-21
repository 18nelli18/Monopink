/*
 * IL0373 e-paper driver for the SES-imagotag VUSION 2.6 BWR (GL420) label.
 * 152 x 296 pixels, black / white / red.
 *
 * Wiring on the label PCB (CC2510 side):
 *   P0_0  EPD power enable, ACTIVE LOW (P-channel FET)
 *   P0_1  EPD CS
 *   P0_3  EPD SDI (USART0 SPI, alt. location 1, MOSI)
 *   P0_5  EPD CLK (USART0 SPI, alt. location 1, SCK)
 *   P1_2  EPD DC   (low = command, high = data)
 *   P1_3  EPD BUSY (low = busy)
 *   P2_0  EPD RESET (active low)
 *
 * Init sequence and pin map from angrymew/firmware-cc2510 and
 * andrei-tatar/imagotag-hack, both proven on this label.
 */
#include <cc2510fx.h>
#include "epd.h"
#include "clock.h"
#include "layout.h"

#define EPD_PWR    P0_0
#define EPD_CS     P0_1
#define EPD_DC     P1_2
#define EPD_BUSY   P1_3
#define EPD_RST    P2_0

#define BUSY_TIMEOUT_POWER    5000u    /* ms */
#define BUSY_TIMEOUT_REFRESH  60000u   /* 3-colour refresh is ~15 s, longer when cold */

static void spi_tx(uint8_t b)
{
    EPD_CS = 0;
    U0CSR &= ~0x02;              /* clear TX_BYTE */
    U0DBUF = b;
    while (!(U0CSR & 0x02)) {    /* wait TX_BYTE */
    }
    while (U0CSR & 0x01) {       /* wait not ACTIVE */
    }
    EPD_CS = 1;
}

static void cmd(uint8_t c)
{
    EPD_DC = 0;
    spi_tx(c);
    EPD_DC = 1;
}

static void data(uint8_t d)
{
    spi_tx(d);
}

uint16_t epd_last_wait_ms;
uint8_t epd_busy_before_on;

/* returns 1 when BUSY went high (ready) before the timeout */
static uint8_t wait_ready(uint16_t timeout_ms)
{
    uint32_t start = millis();
    uint32_t t;
    while (EPD_BUSY == 0) {
        t = millis() - start;
        if (t > timeout_ms) {
            epd_last_wait_ms = 0xFFFF;
            return 0;
        }
    }
    t = millis() - start;
    epd_last_wait_ms = t > 0xFFFE ? 0xFFFE : (uint16_t)t;
    delay_ms(20);
    return 1;
}

/* Clean "off" state: supply cut and every panel line driven low.
 * After a reset the CC2510 pins are inputs with pull-ups, which half-powers
 * an unpowered IL0373 through its I/O protection diodes; its power-on reset
 * then misbehaves and BUSY gets stuck.  BUSY itself gets no pull-up. */
void epd_hold_off(void)
{
    U0CSR &= ~0x40;
    P0SEL &= ~((1 << 3) | (1 << 5));
    EPD_PWR = 1;                 /* supply off (active low) */
    EPD_CS = 0;
    P0_3 = 0;
    P0_5 = 0;
    EPD_DC = 0;
    EPD_RST = 0;
    P0DIR |= (1 << 0) | (1 << 1) | (1 << 3) | (1 << 5);
    P1DIR |= (1 << 2);
    P2DIR |= (1 << 0);
    P1DIR &= ~(1 << 3);
    P1INP |= (1 << 3);           /* BUSY: no pull-up */
}

uint8_t epd_power_on(void)
{
    epd_hold_off();
    delay_ms(200);               /* let the panel fully discharge */

    EPD_PWR = 0;                 /* supply on, lines still low */
    delay_ms(100);

    /* USART0 in SPI master mode, alternative location 1 */
    PERCFG &= ~0x01;
    U0CSR = 0x00;                /* SPI, master */
    U0GCR = (1 << 5) | 17;       /* CPOL=0, CPHA=0, MSB first, BAUD_E=17 */
    U0BAUD = 0;                  /* BAUD_M */
    U0CSR |= 0x40;               /* enable */
    P0SEL |= (1 << 3) | (1 << 5);

    EPD_CS = 1;
    EPD_DC = 1;
    EPD_RST = 1;
    delay_ms(20);
    EPD_RST = 0;                 /* hardware reset */
    delay_ms(20);
    EPD_RST = 1;
    delay_ms(20);
    if (!wait_ready(BUSY_TIMEOUT_POWER))
        return ERR_BUSY_POWER_ON;

    cmd(0x06);                   /* booster soft start */
    data(0x17);
    data(0x17);
    data(0x17);

    epd_busy_before_on = EPD_BUSY;
    cmd(0x04);                   /* power on */
    if (!wait_ready(BUSY_TIMEOUT_POWER))
        return ERR_BUSY_POWER_ON;

    cmd(0x00);                   /* panel setting: KWR mode, LUT from OTP */
    data(0x0F);
    data(0x0D);

    cmd(0x61);                   /* resolution */
    data(EPD_WIDTH);
    data(EPD_HEIGHT >> 8);
    data(EPD_HEIGHT & 0xFF);

    cmd(0x50);                   /* VCOM and data interval */
    data(0x77);

    return ERR_NONE;
}

void epd_write_image(void)
{
    const __code uint8_t *p;
    uint16_t i;

    cmd(0x10);                   /* black/white plane: 1 = white, 0 = black */
    p = (const __code uint8_t *)IMG_BW_ADDR;
    for (i = 0; i < EPD_PLANE_SIZE; i++)
        data(p[i]);

    cmd(0x13);                   /* red plane: 0 = red, 1 = no red */
    p = (const __code uint8_t *)IMG_R_ADDR;
    for (i = 0; i < EPD_PLANE_SIZE; i++)
        data(p[i]);
}

uint8_t epd_refresh(void)
{
    cmd(0x12);                   /* display refresh */
    delay_ms(100);
    if (!wait_ready(BUSY_TIMEOUT_REFRESH))
        return ERR_BUSY_REFRESH;
    return ERR_NONE;
}

uint8_t epd_power_off(void)
{
    uint8_t err = ERR_NONE;

    cmd(0x02);                   /* power off */
    if (!wait_ready(BUSY_TIMEOUT_POWER))
        err = ERR_BUSY_POWER_OFF;
    cmd(0x07);                   /* deep sleep */
    data(0xA5);
    delay_ms(10);

    /* Cut the panel supply and pull every line low so the panel is not
     * back-powered through its I/O pins. */
    epd_hold_off();

    return err;
}
