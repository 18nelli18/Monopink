#ifndef _PLATFORM_H_
#define _PLATFORM_H_

/* Lets the NFC protocol code build both for the CC2510 (SDCC) and natively
 * for the tests (tests/native/), where RAM, flash and the NTAG are mocks. */

#include <stdint.h>

#ifdef __SDCC
#include <cc2510fx.h>
#define XDATA            __xdata
#define XLOCAL           __xdata   /* local variable kept out of internal RAM */
#define XRAM(addr)       ((__xdata uint8_t *)(addr))
#define FLASH_PTR(addr)  ((const __code uint8_t *)(addr))
typedef const __code uint8_t *flash_ptr_t;
#else
extern uint8_t mock_xram[0x1000];
extern uint8_t mock_flash[0x8000];
#define XDATA
#define XLOCAL
#define XRAM(addr)       (&mock_xram[(addr) - 0xF000])
#define FLASH_PTR(addr)  ((const uint8_t *)&mock_flash[(addr)])
typedef const uint8_t *flash_ptr_t;
#endif

#endif
