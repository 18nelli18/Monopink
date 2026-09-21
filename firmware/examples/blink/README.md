# Blink (hardware sanity check)

The very first test from the original log: sets every pin of ports 0, 1 and 2
as output and toggles them, which blinks the white LED (P2_1) among others.
It proves that code you compiled runs on the CC2510.

```bash
./monopink.sh flash-hex firmware/examples/blink/blink.hex          # add --erase on a locked chip
```

`blink.hex` is prebuilt. To rebuild: `sdcc -mmcs51 --model-small blink.c && cp blink.ihx blink.hex`.

This replaces the MonopInk firmware; reinstall it afterwards with
`./monopink.sh install` (or the *Label* step of the web app).
