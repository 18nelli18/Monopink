/*
 * MonopInk probe - turns a Raspberry Pi Pico (RP2040) or Pico 2 (RP2350)
 * into a TI CC-Debugger for the CC2510 of the VUSION 2.6 GL420 label.
 *
 * Wire protocol: 100% compatible with CCLib_proxy (wavesoft/CCLib), so the
 * original CCLib Python tools keep working, plus MonopInk extensions:
 *   - GPIO assignment set over USB and stored in flash (no recompiling)
 *   - block read/write of CODE/XDATA (a 1 KB page written + verified in ~0.3 s)
 *   - reset-and-run / release of the debug lines
 *   - debug mode is entered on demand (the label runs normally until the
 *     host talks to it, so it can display its picture while powered)
 *
 * Based on CCLib_proxy by Ioannis Charalampidis and Simon Schulz.
 * (C) 2014 Ioannis Charalampidis, (C) 2015 Simon Schulz, (C) 2026 MonopInk
 * Licensed under the GNU GPL v3 (see LICENSE at the root of the archive).
 *
 * Build: see pico/build.sh (arduino-cli + earlephilhower arduino-pico core).
 */
#include <EEPROM.h>
#include "cc_debugger.h"

#define PROBE_VERSION   2

/* Default wiring (the one documented in the MonopInk README) */
#define DEF_RST   3
#define DEF_DC    4
#define DEF_DD_I  6
#define DEF_DD_O  7
#define DEF_LED   LED_BUILTIN

/* ---- CCLib_proxy commands ---- */
#define CMD_ENTER     0x01
#define CMD_EXIT      0x02
#define CMD_CHIP_ID   0x03
#define CMD_STATUS    0x04
#define CMD_PC        0x05
#define CMD_STEP      0x06
#define CMD_EXEC_1    0x07
#define CMD_EXEC_2    0x08
#define CMD_EXEC_3    0x09
#define CMD_BRUSTWR   0x0A
#define CMD_RD_CFG    0x0B
#define CMD_WR_CFG    0x0C
#define CMD_CHPERASE  0x0D
#define CMD_RESUME    0x0E
#define CMD_HALT      0x0F
#define CMD_PING      0xF0
#define CMD_INSTR_VER 0xF1
#define CMD_INSTR_UPD 0xF2

/* ---- MonopInk extensions ---- */
#define CMD_READ_CODE   0xE1  /* c1:c2 addr, c3 count (0=256) -> frame + data */
#define CMD_READ_XDATA  0xE2  /* same, from XDATA */
#define CMD_WRITE_XDATA 0xE3  /* c1:c2 addr, c3 count -> READY, data, frame */
#define CMD_RESET_RUN   0xE4  /* c1 bit0 keep RESET_N low, bit1 DC low, bit2 DD low */
#define CMD_RELEASE     0xE5  /* RESET_N high, DD/DC floating */
#define CMD_SET_PINS    0xE8  /* READY, 6 bytes: rst dc ddi ddo led flags */
#define CMD_GET_PINS    0xE9  /* c1 = 0:(rst,dc) 1:(ddi,ddo) 2:(led,saved) */
#define CMD_RESET_PINS  0xEA  /* back to defaults, forget saved config */
#define CMD_IDENT       0xEF  /* c1 = 0: ('M', version) 1: (chip, 0) */

#define ANS_OK     0x01
#define ANS_ERROR  0x02
#define ANS_READY  0x03

#define ERR_BAD_LENGTH  0x03
#define ERR_TIMEOUT     0x04
#define ERR_BAD_PINS    0x10
#define ERR_UNKNOWN     0xFF

#define LED_NONE     0xFF
#define LED_DEFAULT  0xFE

#define EE_MAGIC0 0x4D  /* 'M' */
#define EE_MAGIC1 0x50  /* 'P' */

CCDebugger dbg;
int pRST, pDC, pDDI, pDDO, pLED;
bool pinsFromFlash = false;

byte buf[256];

/* ------------------------------------------------------------------ */

void sendFrame(byte ans, byte b0 = 0, byte b1 = 0)
{
  Serial.write(ans);
  Serial.write(b1);   /* high byte first */
  Serial.write(b0);
  Serial.flush();
}

bool handleError()
{
  if (dbg.error()) {
    sendFrame(ANS_ERROR, dbg.error());
    return true;
  }
  return false;
}

void ledOn()  { if (pLED >= 0) digitalWrite(pLED, HIGH); }
void ledOff() { if (pLED >= 0) digitalWrite(pLED, LOW); }

/* Enter debug mode on demand */
void ensureDebug()
{
  if (!dbg.inDebug()) dbg.enter();
}

/* Read n bytes from USB with a 2 s idle timeout */
bool readPayload(byte *dst, int n)
{
  int got = 0;
  unsigned long last = millis();
  while (got < n) {
    if (Serial.available() > 0) {
      dst[got++] = Serial.read();
      last = millis();
    } else if (millis() - last > 2000) {
      return false;
    }
  }
  return true;
}

bool validPin(int p)
{
  return p >= 0 && p <= 29;
}

bool applyPins(int rst, int dc, int ddi, int ddo, int led)
{
  if (!validPin(rst) || !validPin(dc) || !validPin(ddi) || !validPin(ddo))
    return false;
  if (rst == dc || rst == ddi || rst == ddo || dc == ddi || dc == ddo)
    return false;
  if (led >= 0 && (led == rst || led == dc || led == ddi || led == ddo))
    return false;

  if (pLED >= 0 && pLED != led) pinMode(pLED, INPUT);
  pRST = rst; pDC = dc; pDDI = ddi; pDDO = ddo; pLED = led;
  dbg.setPins(pRST, pDC, pDDI, pDDO);
  if (pLED >= 0) {
    pinMode(pLED, OUTPUT);
    digitalWrite(pLED, LOW);
  }
  return true;
}

int decodeLed(byte v)
{
  if (v == LED_NONE) return -1;
  if (v == LED_DEFAULT) return DEF_LED;
  return v;
}

byte encodeLed(int v)
{
  return v < 0 ? LED_NONE : (byte)v;
}

void savePins()
{
  EEPROM.write(0, EE_MAGIC0);
  EEPROM.write(1, EE_MAGIC1);
  EEPROM.write(2, pRST);
  EEPROM.write(3, pDC);
  EEPROM.write(4, pDDI);
  EEPROM.write(5, pDDO);
  EEPROM.write(6, encodeLed(pLED));
  EEPROM.commit();
  pinsFromFlash = true;
}

void loadPins()
{
  if (EEPROM.read(0) == EE_MAGIC0 && EEPROM.read(1) == EE_MAGIC1 &&
      applyPins(EEPROM.read(2), EEPROM.read(3), EEPROM.read(4),
                EEPROM.read(5), decodeLed(EEPROM.read(6)))) {
    pinsFromFlash = true;
    return;
  }
  pinsFromFlash = false;
  applyPins(DEF_RST, DEF_DC, DEF_DD_I, DEF_DD_O, DEF_LED);
}

/* ------------------------------------------------------------------ */

void setup()
{
  pLED = -1;
  EEPROM.begin(256);
  loadPins();
  Serial.begin(115200);

  /* two short blinks = probe alive */
  for (int i = 0; i < 2; i++) {
    ledOn(); delay(80); ledOff(); delay(120);
  }
}

void cmdReadBlock(bool code, byte c1, byte c2, byte c3)
{
  int n = c3 ? c3 : 256;
  unsigned short addr = (c1 << 8) | c2;

  ensureDebug();
  dbg.execi(0x90, addr);                 /* MOV DPTR,#addr */
  for (int i = 0; i < n && !dbg.error(); i++) {
    if (code) {
      dbg.exec(0xE4);                    /* CLR A */
      buf[i] = dbg.exec(0x93);           /* MOVC A,@A+DPTR */
    } else {
      buf[i] = dbg.exec(0xE0);           /* MOVX A,@DPTR */
    }
    dbg.exec(0xA3);                      /* INC DPTR */
  }
  if (handleError()) return;
  sendFrame(ANS_OK, n & 0xFF, (n >> 8) & 0xFF);
  Serial.write(buf, n);
  Serial.flush();
}

void cmdWriteXdata(byte c1, byte c2, byte c3)
{
  int n = c3 ? c3 : 256;
  unsigned short addr = (c1 << 8) | c2;

  ensureDebug();
  if (handleError()) return;
  sendFrame(ANS_READY);
  if (!readPayload(buf, n)) {
    sendFrame(ANS_ERROR, ERR_TIMEOUT);
    return;
  }
  dbg.execi(0x90, addr);                 /* MOV DPTR,#addr */
  for (int i = 0; i < n && !dbg.error(); i++) {
    dbg.exec(0x74, buf[i]);              /* MOV A,#data */
    dbg.exec(0xF0);                      /* MOVX @DPTR,A */
    dbg.exec(0xA3);                      /* INC DPTR */
  }
  if (handleError()) return;
  sendFrame(ANS_OK, n & 0xFF, (n >> 8) & 0xFF);
}

void cmdBurstWrite(byte c1, byte c2)
{
  int iLen = (c1 << 8) | c2;
  if (iLen > 2048) {
    sendFrame(ANS_ERROR, ERR_BAD_LENGTH);
    return;
  }
  ensureDebug();
  sendFrame(ANS_READY);
  dbg.write(0x80 | (c1 & 0x07));
  dbg.write(c2);

  int iRead = iLen;
  unsigned long last = millis();
  while (iRead > 0) {
    if (Serial.available() >= 1) {
      dbg.write(Serial.read());
      iRead--;
      last = millis();
    } else if (millis() - last > 10000) {
      while (iRead > 0) { dbg.write(0); iRead--; }
      dbg.switchRead();
      dbg.read();
      dbg.switchWrite();
      sendFrame(ANS_ERROR, ERR_TIMEOUT);
      return;
    }
  }
  dbg.switchRead();
  byte bAns = dbg.read();
  dbg.switchWrite();
  if (handleError()) return;
  sendFrame(ANS_OK, bAns);
}

void loop()
{
  if (Serial.available() < 4)
    return;

  byte cmd = Serial.read();
  byte c1 = Serial.read();
  byte c2 = Serial.read();
  byte c3 = Serial.read();
  byte bAns;
  unsigned short s1;

  ledOn();
  switch (cmd) {

  case CMD_PING:
    sendFrame(ANS_OK);
    break;

  case CMD_IDENT:
    if (c1 == 1) {
#if defined(PICO_RP2350)
      sendFrame(ANS_OK, 0, 0x35);
#else
      sendFrame(ANS_OK, 0, 0x20);
#endif
    } else {
      sendFrame(ANS_OK, PROBE_VERSION, 'M');
    }
    break;

  case CMD_ENTER:
    dbg.enter();
    if (handleError()) break;
    sendFrame(ANS_OK);
    break;

  case CMD_EXIT:
    if (dbg.inDebug()) {
      dbg.exit();
      if (handleError()) break;
    }
    sendFrame(ANS_OK);
    break;

  case CMD_CHIP_ID:
    ensureDebug();
    s1 = dbg.getChipID();
    if (handleError()) break;
    sendFrame(ANS_OK, s1 & 0xFF, (s1 >> 8) & 0xFF);
    break;

  case CMD_PC:
    ensureDebug();
    s1 = dbg.getPC();
    if (handleError()) break;
    sendFrame(ANS_OK, s1 & 0xFF, (s1 >> 8) & 0xFF);
    break;

  case CMD_STATUS:
    ensureDebug();
    bAns = dbg.getStatus();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_HALT:
    ensureDebug();
    bAns = dbg.halt();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_RESUME:
    ensureDebug();
    bAns = dbg.resume();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_STEP:
    ensureDebug();
    bAns = dbg.step();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_EXEC_1:
    ensureDebug();
    bAns = dbg.exec(c1);
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_EXEC_2:
    ensureDebug();
    bAns = dbg.exec(c1, c2);
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_EXEC_3:
    ensureDebug();
    bAns = dbg.exec(c1, c2, c3);
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_BRUSTWR:
    cmdBurstWrite(c1, c2);
    break;

  case CMD_RD_CFG:
    ensureDebug();
    bAns = dbg.getConfig();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_WR_CFG:
    ensureDebug();
    bAns = dbg.setConfig(c1);
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_CHPERASE:
    ensureDebug();
    bAns = dbg.chipErase();
    if (handleError()) break;
    sendFrame(ANS_OK, bAns);
    break;

  case CMD_INSTR_VER:
    sendFrame(ANS_OK, dbg.getInstructionTableVersion());
    break;

  case CMD_INSTR_UPD: {
    sendFrame(ANS_READY);
    byte table[16];
    if (!readPayload(table, 16)) {
      sendFrame(ANS_ERROR, ERR_TIMEOUT);
      break;
    }
    sendFrame(ANS_OK, dbg.updateInstructionTable(table));
    break;
  }

  case CMD_READ_CODE:
    cmdReadBlock(true, c1, c2, c3);
    break;

  case CMD_READ_XDATA:
    cmdReadBlock(false, c1, c2, c3);
    break;

  case CMD_WRITE_XDATA:
    cmdWriteXdata(c1, c2, c3);
    break;

  case CMD_RESET_RUN:
    dbg.resetRun(c1);
    sendFrame(ANS_OK);
    break;

  case CMD_RELEASE:
    dbg.release();
    sendFrame(ANS_OK);
    break;

  case CMD_SET_PINS: {
    sendFrame(ANS_READY);
    byte p[6];
    if (!readPayload(p, 6)) {
      sendFrame(ANS_ERROR, ERR_TIMEOUT);
      break;
    }
    int oRST = pRST, oDC = pDC, oDDI = pDDI, oDDO = pDDO, oLED = pLED;
    if (!applyPins(p[0], p[1], p[2], p[3], decodeLed(p[4]))) {
      applyPins(oRST, oDC, oDDI, oDDO, oLED);
      sendFrame(ANS_ERROR, ERR_BAD_PINS);
      break;
    }
    if (p[5] & 0x01) savePins();
    sendFrame(ANS_OK);
    break;
  }

  case CMD_GET_PINS:
    if (c1 == 0)      sendFrame(ANS_OK, pDC, pRST);
    else if (c1 == 1) sendFrame(ANS_OK, pDDO, pDDI);
    else              sendFrame(ANS_OK, pinsFromFlash ? 1 : 0, encodeLed(pLED));
    break;

  case CMD_RESET_PINS:
    EEPROM.write(0, 0xFF);
    EEPROM.write(1, 0xFF);
    EEPROM.commit();
    applyPins(DEF_RST, DEF_DC, DEF_DD_I, DEF_DD_O, DEF_LED);
    pinsFromFlash = false;
    sendFrame(ANS_OK);
    break;

  default:
    sendFrame(ANS_ERROR, ERR_UNKNOWN);
    break;
  }
  ledOff();
}
