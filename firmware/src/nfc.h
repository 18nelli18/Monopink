#ifndef _NFC_H_
#define _NFC_H_

#include <stdint.h>

/* Picture upload from a phone through the NTAG (Web NFC on Android).
 *
 * The phone writes one NDEF message per tap holding one "part" of a
 * compressed picture (MIME record "x/mpk"); when the phone leaves the
 * field, the CC2510 reads it over I2C, stores it in flash, and answers with
 * a status record ("x/mps") that the phone reads at the next tap.
 * When all parts are in, the stream is checked, decoded into the picture
 * area and the display is refreshed.  Format: see docs/NFC.md.
 */

/* nfc_session() results */
#define NFC_NOTHING   0     /* no new part (e.g. the phone only read)  */
#define NFC_PART_OK   1     /* a part was stored, more to come          */
#define NFC_IMAGE     2     /* picture complete and decoded: refresh!   */
#define NFC_FAILED    3     /* see the status error code                */
#define NFC_TIMEOUT   4     /* the field never went away                */

/* status states */
#define NFC_ST_READY      0
#define NFC_ST_RECEIVING  1
#define NFC_ST_COMPLETE   2
#define NFC_ST_ERROR      3

/* status errors */
#define NFC_OK            0
#define NFC_E_CHIP        1   /* NTAG does not answer on I2C          */
#define NFC_E_HEADER      2   /* malformed part                       */
#define NFC_E_PART_CRC    3   /* part corrupted                       */
#define NFC_E_ORDER       4   /* unexpected part: resend from `next`  */
#define NFC_E_TOO_BIG     5   /* stream larger than the staging area  */
#define NFC_E_STREAM_CRC  6   /* assembled stream corrupted           */
#define NFC_E_DECODE      7   /* unknown stream format                */

/* nfc_session() wait modes: how to know that the phone has left */
#define NFC_WAIT_NONE  0    /* test harness                                */
#define NFC_WAIT_FD    1    /* FD pin (woken up by FD)                     */
#define NFC_WAIT_POLL  2    /* NTAG session register (polling mode)        */

/* Handle one phone visit: wait until the phone is gone, then read what it
 * wrote, store it and publish the new status. */
uint8_t nfc_session(uint8_t wait);

/* Polling mode (FD unusable): 1 if a phone is here or has written to the
 * NTAG since our last status, 0 if nothing happened. */
uint8_t nfc_poll(void);

/* Make sure the NTAG holds a valid NDEF area and our status record
 * (called at boot so that the very first tap already finds it). */
void nfc_prepare(void);

/* Test harness: write `len` bytes from RAM (XRAM_BUF_B) into the NTAG user
 * memory, as a phone would, then nfc_session(NFC_WAIT_NONE). */
uint8_t nfc_test_phone_write(uint16_t len);

#endif
