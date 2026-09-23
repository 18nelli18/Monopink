/*
 * NFC diagnostic ("MPNF" in the mailbox): dump what the CC2510 sees of the
 * NTAG I2C chip into RAM, for the host to read through the debug port.
 *
 *   NFCDIAG_ADDR + 0x00  flags: bit0 chip answers, bit1 block 0x40 answers (2k)
 *                + 0x01  FD (P1_1) pulled high, chip unpowered (probe)
 *                + 0x02  FD (P1_1) pulled high, chip powered (probe)
 *                + 0x03  number of session registers read
 *                + 0x04  wake-up mode the firmware uses: 1 = FD, 2 = polling
 *                + 0x08  session registers 0..7
 *                + 0x10  block 0x00 (addr/UID/lock/CC)
 *                + 0x20  block 0x38 (end of user memory, dyn. lock, AUTH0)
 *                + 0x30  block 0x39 (ACCESS, PWD, PACK, PT_I2C)
 *                + 0x40  block 0x3A (configuration registers)
 *                + 0x50  blocks 0x01..0x04 (start of the NDEF area)
 *                + 0x90  block 0x40 (2k variant only)
 */
#include <cc2510fx.h>
#include "nfcdiag.h"
#include "ntag.h"
#include "clock.h"

__xdata __at (NFCDIAG_ADDR) volatile uint8_t diag[NFCDIAG_SIZE];

static void read_into(uint8_t block, uint8_t off)
{
    if (!ntag_read_block(block, (XDATA uint8_t *)&diag[off]))
        diag[0] &= ~0x01;
}

void nfc_diag(void)
{
    uint8_t i, v;

    for (i = 0; i < NFCDIAG_SIZE; i++)
        diag[i] = 0xEE;
    diag[0] = 0;

    ntag_power_off();
    delay_ms(20);
    diag[1] = ntag_fd_probe();
    diag[4] = diag[1] ? 1 : 2;

    ntag_power_on();
    delay_ms(20);
    diag[2] = ntag_fd_probe();

    diag[0] = 0x01;
    read_into(0x00, 0x10);
    read_into(0x38, 0x20);
    read_into(0x39, 0x30);
    read_into(0x3A, 0x40);
    for (i = 0; i < 4; i++)
        read_into(0x01 + i, 0x50 + 16 * i);

    diag[3] = 0;
    for (i = 0; i < 8; i++) {
        if (ntag_read_reg(i, &v)) {
            diag[8 + i] = v;
            diag[3]++;
        }
    }

    /* 2k version answers on block 0x40, the 1k one NAKs */
    if (ntag_read_block(0x40, (XDATA uint8_t *)&diag[0x90]))
        diag[0] |= 0x02;

    ntag_unlock_i2c();
    ntag_power_off();
}
