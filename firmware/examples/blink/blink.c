// Déclaration des registres du CC2510 (adresses tirées du datasheet TI)
__sfr __at (0x80) P0;
__sfr __at (0x90) P1;
__sfr __at (0xA0) P2;

__sfr __at (0xFD) P0DIR;
__sfr __at (0xFE) P1DIR;
__sfr __at (0xFF) P2DIR;

__sfr __at (0xF3) P0SEL;
__sfr __at (0xF4) P1SEL;
__sfr __at (0xF5) P2SEL;

void delay(void) {
    volatile unsigned long i;
    for (i = 0; i < 60000UL; i++);
}

void main(void) {
    P0SEL = 0x00;  P1SEL = 0x00;  P2SEL = 0x00;   // tout en GPIO
    P0DIR = 0xFF;  P1DIR = 0xFF;  P2DIR = 0xFF;   // tout en sortie

    while (1) {
        P0 = 0xFF; P1 = 0xFF; P2 = 0xFF;
        delay();
        P0 = 0x00; P1 = 0x00; P2 = 0x00;
        delay();
    }
}