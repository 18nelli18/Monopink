/*
 * MonopInk - flash / RAM layout shared with the host tool.
 *
 * !! Keep in sync with monopink/layout.py !!
 *
 *   0x0000 - 0x4FEF  firmware code (uses < 2 KB)
 *   0x4FF0 - 0x4FFF  firmware info block ("MONOPINK" + version)
 *   0x5000 - 0x65F7  image, black/white plane (5624 bytes)
 *   0x6600 - 0x7BF7  image, red plane         (5624 bytes)
 *   0x7C00 - 0x7FFF  unused (last page)
 *
 * The image lives at a fixed address so the host can replace it by rewriting
 * only flash pages 20..30, without recompiling anything.
 */
#ifndef _LAYOUT_H_
#define _LAYOUT_H_

#define FW_VERSION_MAJOR   1
#define FW_VERSION_MINOR   2
#define LAYOUT_VERSION     1

#define FW_INFO_ADDR       0x4FF0
#define IMG_BW_ADDR        0x5000
#define IMG_R_ADDR         0x6600

#define EPD_WIDTH          152
#define EPD_HEIGHT         296
#define EPD_PLANE_SIZE     (EPD_WIDTH / 8 * EPD_HEIGHT)   /* 5624 */

/* Mailbox in XDATA RAM, used by the host to watch the refresh through the
 * debug port.  mb[0..3] written by the host before starting the CPU:
 *   "MPHD"  debug-mode run watched by the host: stay awake at the end
 *   "MPNR"  diagnostic: behave exactly like a normal (battery) boot, but stay
 *           awake at the end instead of entering PM3 so the host can read
 *           the result after the next reset (the RAM survives a reset). */
#define MAILBOX_ADDR       0xF800

#define MB_STATE           4
#define MB_ERROR           5
#define MB_T_REFRESH_L     6
#define MB_T_REFRESH_H     7
#define MB_T_TOTAL_L       8
#define MB_T_TOTAL_H       9
#define MB_FW_VERSION      10
#define MB_BUSY_AT_ON      11   /* BUSY level just before the power-on command */
#define MB_T_PWRON_L       12   /* ms waited for BUSY after power-on */
#define MB_T_PWRON_H       13
#define MB_BOOTS           14   /* boot counter (RAM survives a reset) */
#define MB_RESET_CAUSE     15   /* SLEEP register at boot (bits 4:3 = cause) */

/* MB_STATE values */
#define ST_BOOT            0x10
#define ST_EPD_POWERED     0x20
#define ST_EPD_READY       0x30
#define ST_DATA_SENT       0x40
#define ST_REFRESHING      0x50
#define ST_REFRESH_DONE    0x60
#define ST_EPD_OFF         0x70
#define ST_IDLE_HOLD       0x80

/* MB_ERROR values */
#define ERR_NONE           0x00
#define ERR_BUSY_POWER_ON  0x01
#define ERR_BUSY_REFRESH   0x02
#define ERR_BUSY_POWER_OFF 0x03

#endif
