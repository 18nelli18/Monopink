#ifndef _FLASH_H_
#define _FLASH_H_

#include <stdint.h>
#include "platform.h"

#define FLASH_PAGE 1024

/* Erase and program one 1 KB page (page-aligned addr) from a RAM buffer.
 * Runs a small routine copied to RAM: the CPU cannot execute from flash
 * while the flash controller is busy. */
void flash_write_page(uint16_t addr, XDATA uint8_t *src);

/* Copy len bytes of flash into RAM */
void flash_read(uint16_t addr, XDATA uint8_t *dst, uint16_t len);

#endif
