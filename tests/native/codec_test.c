/* Native test harness: decode a stream file, print the 45024 pixel values
 * as one text line of digits (0 white, 1 black, 2 red). */
#include <stdio.h>
#include <stdlib.h>
#include "../../firmware/src/codec.h"

int main(int argc, char **argv)
{
    static uint8_t buf[65536];
    static codec_state_t st;
    static codec_mem_t m;
    FILE *f = fopen(argv[1], "rb");
    size_t n;
    int y, x;
    if (!f) return 2;
    n = fread(buf, 1, sizeof(buf) - 16, f);
    fclose(f);
    (void)n;
    if (!codec_begin(&st, &m, buf)) { puts("BADFORMAT"); return 1; }
    for (y = 0; y < CODEC_H; y++) {
        codec_row(&st, &m);
        for (x = 0; x < CODEC_W; x++) putchar('0' + m.cur[x]);
    }
    putchar('\n');
    return 0;
}
