/*
 * Native test harness for firmware/src/nfc.c: the real protocol code runs
 * against a mock NTAG (I2C block memory) and a mock flash.
 *
 * usage: nfc_test <scenario file> <out planes file>
 * scenario: sequence of  [u16 LE length][area bytes]  = what the phone writes
 *   length 0xFFFF (no bytes): batteries removed - the RAM is lost
 *   length 0xFFFE (no bytes): polling-mode check, prints "poll <0|1>"
 *   length | 0x8000: the phone writes the area but the label does not run
 * For each area: prints "result <r> status <16 hex bytes> area <32 hex>".
 * At the end writes the 11264-byte picture region (0x5000-0x7BFF) and
 * prints the flash page write counts on stderr.
 */
#include <stdio.h>
#include <string.h>
#include "../../firmware/src/platform.h"
#include "../../firmware/src/layout.h"
#include "../../firmware/src/nfc.h"
#include "../../firmware/src/ntag.h"
#include "../../firmware/src/flash.h"

uint8_t mock_xram[0x1000];
uint8_t mock_flash[0x8000];
static uint8_t ntag_mem[256][16];
int flash_writes = 0, desc_writes = 0;

/* ---- mocks ---- */
void delay_ms(uint16_t ms) { (void)ms; }
uint32_t millis(void) { return 0; }
void ntag_power_on(void) {}
void ntag_power_off(void) {}
void ntag_unlock_i2c(void) {}
uint8_t ntag_read_block(uint8_t block, uint8_t *buf)
{
    memcpy(buf, ntag_mem[block], 16);
    if (block == 0) buf[0] = 0x04;         /* byte 0 always reads 04h */
    return 1;
}
uint8_t ntag_write_block(uint8_t block, uint8_t *buf)
{
    memcpy(ntag_mem[block], buf, 16);
    return 1;
}
uint8_t ntag_read_reg(uint8_t rega, uint8_t *val) { (void)rega; *val = 0; return 1; }  /* no field */
uint8_t ntag_write_reg(uint8_t rega, uint8_t mask, uint8_t val) { (void)rega; (void)mask; (void)val; return 1; }
void flash_write_page(uint16_t addr, uint8_t *src)
{
    if (addr & 0x3FF) { fprintf(stderr, "unaligned page write %04x\n", addr); return; }
    if (addr < CODE_LIMIT) { fprintf(stderr, "write into code area %04x\n", addr); return; }
    memcpy(&mock_flash[addr], src, 1024);
    flash_writes++;
    if (addr == NFC_DESC_ADDR)
        desc_writes++;
}
void flash_read(uint16_t addr, uint8_t *dst, uint16_t len) { memcpy(dst, &mock_flash[addr], len); }

int main(int argc, char **argv)
{
    static uint8_t area[2048];
    FILE *f, *o;
    uint8_t lenb[2];
    int i;

    memset(mock_flash, 0xFF, sizeof(mock_flash));
    memset(ntag_mem, 0, sizeof(ntag_mem));
    f = fopen(argv[1], "rb");
    if (!f) return 2;

    nfc_prepare();
    printf("prepare status ");
    for (i = 0; i < 16; i++) printf("%02x", mock_xram[XRAM_NFC_STATUS - 0xF000 + i]);
    printf(" cc %02x%02x%02x%02x\n", ntag_mem[0][12], ntag_mem[0][13], ntag_mem[0][14], ntag_mem[0][15]);

    while (fread(lenb, 1, 2, f) == 2) {
        uint16_t n = lenb[0] | (lenb[1] << 8);
        uint8_t r;
        if (n == 0xFFFF) {                 /* power loss: RAM content is gone */
            memset(mock_xram, 0, sizeof(mock_xram));
            nfc_prepare();                 /* what main() does at boot */
            printf("reboot\n");
            continue;
        }
        if (n == 0xFFFE) {
            printf("poll %d\n", nfc_poll());
            continue;
        }
        if (n & 0x8000) {                  /* phone write only */
            n &= 0x7FFF;
            if (fread(area, 1, n, f) != n) return 3;
            for (i = 0; i < n; i++)
                ntag_mem[1 + i / 16][i % 16] = area[i];
            printf("written\n");
            continue;
        }
        if (fread(area, 1, n, f) != n) return 3;
        memcpy(&mock_xram[XRAM_BUF_B - 0xF000], area, n);
        r = nfc_test_phone_write(n);
        printf("result %d status ", r);
        for (i = 0; i < 16; i++) printf("%02x", mock_xram[XRAM_NFC_STATUS - 0xF000 + i]);
        printf(" area ");
        for (i = 0; i < 32; i++) printf("%02x", ntag_mem[1 + i / 16][i % 16]);
        printf("\n");
    }
    fclose(f);
    o = fopen(argv[2], "wb");
    fwrite(&mock_flash[IMG_BW_ADDR], 1, 0x7C00 - 0x5000, o);
    fclose(o);
    fprintf(stderr, "flash page writes: %d, state page: %d\n", flash_writes, desc_writes);
    return 0;
}
