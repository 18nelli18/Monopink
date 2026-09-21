/*
 * CC-Debugger protocol - see cc_debugger.h for credits and license (GPLv3).
 */
#include "cc_debugger.h"

#define INSTR_VERSION   0
#define I_HALT          1
#define I_RESUME        2
#define I_RD_CONFIG     3
#define I_WR_CONFIG     4
#define I_DEBUG_INSTR_1 5
#define I_DEBUG_INSTR_2 6
#define I_DEBUG_INSTR_3 7
#define I_GET_CHIP_ID   8
#define I_GET_PC        9
#define I_READ_STATUS   10
#define I_STEP_INSTR    11
#define I_CHIP_ERASE    12

#define DD_UNKNOWN      2

/* Same (proven) timing as the original CCLib */
static void cc_delay(unsigned char d)
{
  volatile unsigned char i = d;
  while (i--);
}

CCDebugger::CCDebugger()
{
  pinRST = pinDC = pinDD_I = pinDD_O = -1;
  errorFlag = CC_ERROR_NONE;
  ddIsOutput = DD_UNKNOWN;
  linesActive = false;
  inDebugMode = false;

  /* Default instruction table: CC111x / CC251x family (version 2).
   * Hosts can still replace it with CMD_INSTR_UPD (CCLib does). */
  instr[INSTR_VERSION]   = 2;
  instr[I_HALT]          = 0x44;
  instr[I_RESUME]        = 0x4C;
  instr[I_RD_CONFIG]     = 0x24;
  instr[I_WR_CONFIG]     = 0x1D;
  instr[I_DEBUG_INSTR_1] = 0x55;
  instr[I_DEBUG_INSTR_2] = 0x56;
  instr[I_DEBUG_INSTR_3] = 0x57;
  instr[I_GET_CHIP_ID]   = 0x68;
  instr[I_GET_PC]        = 0x28;
  instr[I_READ_STATUS]   = 0x34;
  instr[I_STEP_INSTR]    = 0x5C;
  instr[I_CHIP_ERASE]    = 0x14;
  instr[13] = instr[14] = instr[15] = 0;
}

void CCDebugger::setPins(int rst, int dc, int ddi, int ddo)
{
  if (pinRST >= 0) {
    pinMode(pinRST, INPUT);
    pinMode(pinDC, INPUT);
    pinMode(pinDD_I, INPUT);
    pinMode(pinDD_O, INPUT);
  }
  pinRST = rst;
  pinDC = dc;
  pinDD_I = ddi;
  pinDD_O = ddo;
  release();
}

void CCDebugger::release()
{
  pinMode(pinDD_O, INPUT);
  pinMode(pinDD_I, INPUT);
  pinMode(pinDC, INPUT);
  pinMode(pinRST, OUTPUT);
  digitalWrite(pinRST, HIGH);
  ddIsOutput = DD_UNKNOWN;
  linesActive = false;
  inDebugMode = false;
}

void CCDebugger::activateLines()
{
  pinMode(pinDC, OUTPUT);
  digitalWrite(pinDC, LOW);
  pinMode(pinRST, OUTPUT);
  digitalWrite(pinRST, HIGH);
  ddIsOutput = DD_UNKNOWN;
  setDDDirection(INPUT);
  linesActive = true;
}

void CCDebugger::resetRun(byte flags)
{
  bool hold = flags & 0x01;
  /* DC must stay still while RESET_N is low, otherwise the chip would
   * enter debug mode. */
  pinMode(pinDD_O, INPUT);
  pinMode(pinDD_I, INPUT);
  pinMode(pinDC, OUTPUT);
  digitalWrite(pinDC, LOW);
  pinMode(pinRST, OUTPUT);
  digitalWrite(pinRST, LOW);
  delay(20);
  if (!hold) {
    digitalWrite(pinRST, HIGH);
    delay(2);
  }
  if (!(flags & 0x02)) pinMode(pinDC, INPUT);
  if (flags & 0x04) {
    pinMode(pinDD_O, OUTPUT);
    digitalWrite(pinDD_O, LOW);
  }
  ddIsOutput = DD_UNKNOWN;
  linesActive = false;
  inDebugMode = false;
}

/////////////////////////////////////////////////////////////////////
//                      LOW LEVEL FUNCTIONS                        //
/////////////////////////////////////////////////////////////////////

byte CCDebugger::enter()
{
  errorFlag = CC_ERROR_NONE;
  if (!linesActive) activateLines();

  digitalWrite(pinRST, LOW);
  /* The original 200-loop delay was ~100 us on a 16 MHz AVR but only a few
   * us on a 133 MHz RP2040: too short for a CC2510 sleeping in PM3, whose
   * regulator must restart.  Measured: the first entry then fails.  Hold
   * RESET_N low for 1 ms before the two DC edges. */
  delayMicroseconds(1000);
  digitalWrite(pinDC, HIGH);
  cc_delay(3);
  digitalWrite(pinDC, LOW);
  cc_delay(3);
  digitalWrite(pinDC, HIGH);
  cc_delay(3);
  digitalWrite(pinDC, LOW);
  cc_delay(200);
  digitalWrite(pinRST, HIGH);
  delayMicroseconds(200);

  inDebugMode = true;
  return 0;
}

byte CCDebugger::write(byte data)
{
  if (!inDebugMode) {
    errorFlag = CC_ERROR_NOT_DEBUGGING;
    return 0;
  }
  byte cnt;
  setDDDirection(OUTPUT);
  for (cnt = 8; cnt; cnt--) {
    digitalWrite(pinDD_O, (data & 0x80) ? HIGH : LOW);
    digitalWrite(pinDC, HIGH);
    data <<= 1;
    cc_delay(2);
    digitalWrite(pinDC, LOW);
    cc_delay(2);
  }
  return 0;
}

byte CCDebugger::switchRead(byte maxWaitCycles)
{
  if (!inDebugMode) {
    errorFlag = CC_ERROR_NOT_DEBUGGING;
    return 0;
  }
  byte cnt;
  byte didWait = 0;

  setDDDirection(INPUT);
  cc_delay(2);

  /* Wait for DD to go LOW (chip ready) */
  while (digitalRead(pinDD_I) == HIGH) {
    for (cnt = 8; cnt; cnt--) {
      digitalWrite(pinDC, HIGH);
      cc_delay(2);
      digitalWrite(pinDC, LOW);
      cc_delay(2);
    }
    didWait = 1;
    if (!--maxWaitCycles) {
      /* Lost the chip: nothing is driving DD (it stays pulled up) */
      errorFlag = CC_ERROR_NOT_WIRED;
      inDebugMode = false;
      return 0;
    }
  }
  if (didWait) cc_delay(2);
  return 0;
}

byte CCDebugger::switchWrite()
{
  setDDDirection(OUTPUT);
  return 0;
}

byte CCDebugger::read()
{
  byte cnt;
  byte data = 0;
  setDDDirection(INPUT);
  for (cnt = 8; cnt; cnt--) {
    digitalWrite(pinDC, HIGH);
    cc_delay(2);
    data <<= 1;
    if (digitalRead(pinDD_I) == HIGH)
      data |= 0x01;
    digitalWrite(pinDC, LOW);
    cc_delay(2);
  }
  return data;
}

void CCDebugger::setDDDirection(byte direction)
{
  if (direction == ddIsOutput) return;
  ddIsOutput = direction;

  if (ddIsOutput) {
    if (pinDD_I != pinDD_O) pinMode(pinDD_I, INPUT);
    pinMode(pinDD_O, OUTPUT);           /* gpio_init() => latch at 0 */
    digitalWrite(pinDD_O, LOW);
  } else {
    pinMode(pinDD_O, INPUT);
    /* weak pull-up: a line with no chip on it reads 1, which makes
     * switchRead() report CC_ERROR_NOT_WIRED instead of garbage */
    pinMode(pinDD_I, INPUT_PULLUP);
  }
}

/////////////////////////////////////////////////////////////////////
//                      HIGH LEVEL FUNCTIONS                       //
/////////////////////////////////////////////////////////////////////

byte CCDebugger::exit()
{
  if (!inDebugMode) {
    errorFlag = CC_ERROR_NOT_DEBUGGING;
    return 0;
  }
  byte bAns;
  write(instr[I_RESUME]);
  switchRead();
  bAns = read();
  switchWrite();
  inDebugMode = false;
  return bAns;
}

byte CCDebugger::getConfig()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_RD_CONFIG]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::setConfig(byte config)
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_WR_CONFIG]);
  write(config);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::exec(byte oc0)
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_DEBUG_INSTR_1]);
  write(oc0);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::exec(byte oc0, byte oc1)
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_DEBUG_INSTR_2]);
  write(oc0);
  write(oc1);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::exec(byte oc0, byte oc1, byte oc2)
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_DEBUG_INSTR_3]);
  write(oc0);
  write(oc1);
  write(oc2);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::execi(byte oc0, unsigned short c0)
{
  return exec(oc0, (c0 >> 8) & 0xFF, c0 & 0xFF);
}

unsigned short CCDebugger::getChipID()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  unsigned short bAns;
  write(instr[I_GET_CHIP_ID]);
  switchRead();
  bAns = read() << 8;
  bAns |= read();
  switchWrite();
  return bAns;
}

unsigned short CCDebugger::getPC()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  unsigned short bAns;
  write(instr[I_GET_PC]);
  switchRead();
  bAns = read() << 8;
  bAns |= read();
  switchWrite();
  return bAns;
}

byte CCDebugger::getStatus()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_READ_STATUS]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::step()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_STEP_INSTR]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::resume()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_RESUME]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::halt()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_HALT]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::chipErase()
{
  if (!inDebugMode) { errorFlag = CC_ERROR_NOT_DEBUGGING; return 0; }
  byte bAns;
  write(instr[I_CHIP_ERASE]);
  switchRead();
  bAns = read();
  switchWrite();
  return bAns;
}

byte CCDebugger::updateInstructionTable(byte newTable[16])
{
  for (byte i = 0; i < 16; i++)
    instr[i] = newTable[i];
  return instr[INSTR_VERSION];
}

byte CCDebugger::getInstructionTableVersion()
{
  return instr[INSTR_VERSION];
}
