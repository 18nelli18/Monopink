/*
 * CC-Debugger protocol (TI "ChipCon" 2-wire debug interface) bit-banged
 * on any Arduino-compatible board.
 *
 * Based on CCLib by Ioannis Charalampidis and Simon Schulz
 *   https://github.com/wavesoft/CCLib
 * Copyright (c) 2014-2016 Ioannis Charalampidis
 * Copyright (c) 2015 Simon Schulz - github.com/fishpepper
 * MonopInk changes (c) 2026: runtime pin configuration, single-pin DD
 * support, release/reset-run, weak pull-up on DD for wiring detection.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 */
#ifndef CC_DEBUGGER_H
#define CC_DEBUGGER_H

#include <Arduino.h>

#define CC_ERROR_NONE           0
#define CC_ERROR_NOT_ACTIVE     1
#define CC_ERROR_NOT_DEBUGGING  2
#define CC_ERROR_NOT_WIRED      3

class CCDebugger {
public:
  CCDebugger();

  /* (Re)assign the GPIOs. pinDD_I may equal pinDD_O (one wire to DD). */
  void setPins(int pinRST, int pinDC, int pinDD_I, int pinDD_O);

  /* Drive RESET_N high and leave DD/DC floating: the target runs freely. */
  void release();

  /* Hardware reset without entering debug mode, then release the lines.
   * flags: bit0 = keep RESET_N low (target held in reset),
   *        bit1 = keep driving DC low, bit2 = keep driving DD low. */
  void resetRun(byte flags);

  byte enter();
  byte exit();
  bool inDebug() { return inDebugMode; }
  byte error() { return errorFlag; }

  byte write(byte data);
  byte switchRead(byte maxWaitCycles = 255);
  byte switchWrite();
  byte read();

  byte getConfig();
  byte setConfig(byte config);
  byte exec(byte oc0);
  byte exec(byte oc0, byte oc1);
  byte exec(byte oc0, byte oc1, byte oc2);
  byte execi(byte oc0, unsigned short c0);
  unsigned short getChipID();
  unsigned short getPC();
  byte getStatus();
  byte step();
  byte resume();
  byte halt();
  byte chipErase();

  byte updateInstructionTable(byte newTable[16]);
  byte getInstructionTableVersion();

private:
  void setDDDirection(byte direction);
  void activateLines();

  int pinRST, pinDC, pinDD_I, pinDD_O;
  byte errorFlag;
  byte ddIsOutput;
  bool linesActive;
  bool inDebugMode;
  byte instr[16];
};

#endif
