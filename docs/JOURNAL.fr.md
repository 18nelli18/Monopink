# Détournement étiquette VUSION 2.6 GL420 — journal technique complet

Prise de contrôle d'une étiquette électronique Monoprix (SES-imagotag VUSION 2.6
BWR GL420) pour y afficher ses propres images. Aucun composant dessoudé : tout
passe par le port de debug d'usine du microcontrôleur.

---

## 1. Le matériel

| Élément | Détail |
|---|---|
| Étiquette | SES-imagotag VUSION 2.6 BWR GL420 |
| MCU | Texas Instruments **CC2510F32** (cœur 8051, 32 Ko flash, 4 Ko RAM, radio 2.4 GHz) |
| Dalle | e-paper 3 couleurs (noir/blanc/rouge), 152×296, Pervasive Displays, contrôleur **IL0373** |
| Programmeur | Raspberry Pi **Pico** (RP2040) transformé en CC-Debugger |
| Poste | MacBook Pro (macOS) |

Le Chip ID lu en debug est `0x8104` (famille CC251x).

---

## 2. Comprendre le problème avant d'agir

**La radio est fermée.** Le protocole 2.4 GHz des VUSION est propriétaire, chiffré
(clé AES par site), conçu pour les seuls points d'accès SES. Il n'a jamais été
rétro-ingénié publiquement → inutile d'essayer de « parler » à l'étiquette telle
quelle.

**La bonne porte : le debug d'usine.** Le CC2510 expose un port de debug **2 fils**
(protocole ChipCon de TI) que le constructeur utilise pour programmer la puce en
sortie de chaîne. Ce port n'est jamais retiré, juste non connecté à un connecteur.
On s'en sert pour effacer le firmware d'origine et flasher le nôtre.

**Le seul obstacle : le debug lock.** Un bit dans la puce interdit la *lecture* du
flash (protection du firmware SES). Point crucial : **le lock n'empêche pas
l'effacement + réécriture**, et un effacement complet (mass erase) *lève le lock au
passage*. On perd le firmware d'origine (illisible de toute façon), on ne perd pas
la puce.

**Architecture du montage :**
- un **firmware fixe sur le Pico** (projet CCLib) qui génère le protocole ChipCon bit à bit ;
- un **script Python sur le Mac** qui pilote le Pico en USB (« lis le chip ID », « efface », « écris ce .hex »).
- Le Pico = traducteur, le Mac = cerveau, le CC2510 = cible.

---

## 3. Brochage du CC2510 sur cette carte

Relevé (repos kylix34 / angrymew, confirmé au multimètre) :

### Port 0
- **P0_0** — EPD power enable (**actif bas**, via FET canal P) → indispensable pour alimenter la dalle
- **P0_1** — EPD CS (SPI chip select)
- **P0_2** — debug port
- **P0_3** — EPD SDI (SPI MOSI)
- **P0_4** — SDA vers puce NFC
- **P0_5** — EPD CLK (SPI clock)
- **P0_6** — SCL vers puce NFC

### Port 1
- **P1_2** — EPD DC (data/command)
- **P1_3** — EPD BUSY

### Port 2
- **P2_0** — EPD Reset
- **P2_1** — **debug data (DD)** + LED blanche
- **P2_2** — **debug clock (DC)** + enable boost LED (TPS61071)

> Astuce de repérage : DD et DC étant partagés avec les LED, ils sont routés vers
> des composants visibles (LED blanche, chip TPS61071) → points de soudure
> accessibles sans aller sous le QFN36.

### Alimentation — le piège DCOUPL
- **DVDD / AVDD** = broches d'alim, à **3.3 V** (la puce tolère 2.0–3.6 V).
- **DCOUPL** = sortie du régulateur **1.8 V interne**, condo de découplage seulement.
  **Ne JAMAIS y injecter 3.3 V** (destruction). C'est aussi la broche attaquée en cas de glitch de tension.
- **Alimenter sur DVDD** (cœur numérique), pas AVDD (analogique/RF, filtré derrière une
  éventuelle ferrite). Si une ferrite sépare les deux rails : se brancher **côté DVDD**,
  l'AVDD se remplit tout seul à travers sa ferrite.

---

## 4. Câblage final Pico ↔ étiquette

Le Pico est en 3.3 V comme le CC2510 → **aucun pont diviseur nécessaire** (les
résistances 100k/200k du montage CCLib d'origine servaient à diviser le 5 V d'un
Arduino). DD_I et DD_O reliés sur le même fil vers l'unique broche DD, ce qui marche
parce que le firmware bascule DD_O en entrée (haute impédance) quand la puce répond.

```
Pico 3V3 (pin 36) → DVDD
Pico GND          → GND
Pico GP3          → RESET_N
Pico GP4          → DC
Pico GP6 ┐
Pico GP7 ┴─(câble dédoublé)→ DD
```

Côté puce : **5 fils** (DD, DC, RESET, DVDD, GND). Fils courts (l'entrée en debug est
sensible au timing). Piles de l'étiquette **retirées** pendant le flash.

---

## 5. Setup du Pico en CC-Debugger

### Core arduino-pico dans l'IDE Arduino
Préférences → URLs de cartes supplémentaires :
```
https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
```
Gestionnaire de cartes → installer « Raspberry Pi Pico/RP2040 ».

### Bibliothèque CCLib
```bash
git clone https://github.com/wavesoft/CCLib.git
# copier la lib Arduino là où l'IDE la cherche :
mkdir -p ~/Documents/Arduino/libraries
cp -R CCLib/Arduino/CCLib ~/Documents/Arduino/libraries/CCLib
```
> Piège : `#include <CCDebugger.h>` (chevrons) → l'IDE cherche dans le dossier
> `libraries`, pas à côté du sketch. **Quitter et relancer l'IDE** après la copie
> (le scan des libs ne se fait qu'au démarrage). Ouvrir ensuite le sketch via
> **Fichier → Exemples → CCLib → CCLib_proxy**.

### Broches dans le sketch `CCLib_proxy.ino`
Le « 4 pins » est **côté Pico** : DD_I et DD_O sont deux GPIO qui attaquent la même
broche DD (bidirectionnelle). Côté puce, toujours 3 fils logiques.
```c
int LED      = LED_BUILTIN;   // (l'origine visait une Teensy : LED=17)
int CC_RST   = 3;
int CC_DC    = 4;
int CC_DD_I  = 6;
int CC_DD_O  = 7;
```

### Premier flash du Pico (mode bootloader)
Pico neuf = pas de port série. BOOTSEL maintenu + branchement USB → disque
`RPI-RP2` monte → Téléverser (arduino-pico détecte le disque tout seul). Le
« disque non éjecté correctement » de macOS est normal (le Pico reboote).
Ensuite, le Pico expose un port série `/dev/cu.usbmodemXXXX` et les uploads
suivants se font sans BOOTSEL.

---

## 6. Setup Python côté Mac + patches CCLib

La lib CCLib se dit compatible Python 3 mais ne l'est qu'en partie. Tous les patches
ci-dessous sont dans la copie déplacée en `~/vusion/host/cclib/` (voir §11).

### Patch 1 — écritures série py2 → py3 (`cclib/ccproxy.py`)
`chr()` renvoie une *str*, refusée par pyserial en py3. Deux endroits :

**Ligne 203** (bloquait l'auto-détection *en silence*, l'exception étant avalée) :
```python
# avant : self.ser.write( chr(cmd)+chr(c1)+chr(c2)+chr(c3) )
self.ser.write( bytes([cmd, c1, c2, c3]) )
```
**Ligne 399** (ne pète qu'à l'écriture flash) :
```python
# avant : self.ser.write(chr(b & 0xFF))
self.ser.write( bytes([b & 0xFF]) )
```

### Patch 2 — taille de flash (`cclib/chip/cc2510.py`)
Le driver code `16` en dur (écrit pour un F16). Ma puce est un **F32** :
```python
self.chipInfo = { 'flash' : 32, 'usb' : 0, 'sram' : 2 }   # 16 → 32
```
Indicateur de succès : `cc_info.py` affiche « Flash size : 32 Kb ».

### Patch 3 — divisions flottantes (`cclib/chip/cc2510.py`, `writeFlashPage`)
En py3, `/` renvoie un float → illégal dans un flux d'octets/opérations binaires.
Passer en `//` (division entière) partout où le résultat alimente un `&`, `>>`, ou
la liste d'opcodes :
```python
words_per_flash_page = self.flashPageSize // self.flashWordSize
# et dans routine8_1 :
0x75, 0xAD, ((address >> 8) // self.flashWordSize) & 0x7E,
```

### Patch 4 — méthode `setPC` manquante (`cclib/chip/cc2510.py`)
`writeFlashPage` a besoin de positionner le PC, mais le proxy n'expose que `getPC`,
et le firmware Arduino n'a pas de commande dédiée. On fixe le PC en faisant exécuter
un `LJMP address` (opcode `0x02`) via `CMD_EXEC` :
```python
def setPC(self, address):
    aHigh = (address >> 8) & 0xFF
    aLow  = address & 0xFF
    return self.instr(0x02, aHigh, aLow)   # LJMP #address
```

### Pourquoi ces bugs
Deux familles : (1) **portage py2→py3 incomplet** (les `chr()` et les `/`) ;
(2) **fusion bâclée** du travail de fishpepper dans la lib officielle
(`writeFlashPage` copiée mais références à `debug_active`, `show_debug_info`, `setPC`
non fournies).

---

## 7. Le script de flash `flash_page.py`

`cc_write_flash.py` d'origine passe par le **DMA** (`pauseDMA` → `NotImplementedError`),
voie jamais portée pour le CC2510. On contourne avec `writeFlashPage()` (routine
assembleur page par page, sans DMA). Script créé dans `~/vusion/host/cclib/Python/` :

```python
#!/usr/bin/env python3
import sys
from cclib import CCHEXFile, getOptions, openCCDebugger

opts = getOptions("CC2510 page-based flash writer", hexIn=True)
dbg = openCCDebugger(opts['port'], enterDebug=opts['enter'])

PAGE  = dbg.flashPageSize   # 0x400 = 1024
FLASH = dbg.flashSize       # 32768

hexFile = CCHEXFile(opts['in'])
hexFile.load()

image = bytearray([0xFF] * FLASH)      # flash vierge = 0xFF
for mb in hexFile.memBlocks:
    for i in range(mb.size):
        image[mb.addr + i] = mb.bytes[i]

dbg.enter()
dbg.debug_active   = True   # attribut fantôme attendu par writeFlashPage
dbg.show_debug_info = False  # idem (flag de verbosité)
for page in range(FLASH // PAGE):
    start = page * PAGE
    chunk = image[start:start + PAGE]
    if all(b == 0xFF for b in chunk):
        continue                        # saute les pages vides
    print(f" - Page {page} @ 0x{start:04x} ...", end=" ", flush=True)
    dbg.writeFlashPage(start, chunk, erase_page=True)
    print("ok")
print("Terminé.")
```

Ce qu'il fait : (1) aplatit le `.hex` (sections éparses) en une image continue de
32 Ko remplie de `0xFF` ; (2) n'écrit que les pages non vides ; (3) efface chaque
page juste avant de l'écrire.

---

## 8. Premier contact et diagnostic du lock

```bash
cd ~/vusion/host/cclib/Python
pip3 install pyserial
python3 cc_info.py -E -p /dev/cu.usbmodem101
```
`-E` = force l'entrée en mode debug.

Sortie obtenue : Chip ID `0x8104`, et dans le **Debug status** :
- `DEBUG_LOCKED` **actif** → firmware SES illisible, dump impossible.
- Décision imposée : **mass erase + reflash** (le mass erase lève le lock).

> Note : le prompt de confirmation `<y/N>` attend **`y`** seul. Taper la phrase
> « ERASE and REPROGRAM » (qui est juste le libellé de l'action) fait échouer la
> lecture → `Aborted`. Si un `Aborted` sort *avant* de pouvoir répondre, c'est un
> résidu dans le tampon d'entrée du terminal → ouvrir un terminal neuf.

---

## 9. Le blink (validation de la chaîne SDCC → flash → puce)

### SDCC
```bash
brew install sdcc
```
SDCC ne fournit **pas** de `cc2510.h` → on déclare les registres (SFR) à la main.
Sur le 8051, un périphérique = une case mémoire à adresse fixe ; `__sfr __at(adr)`
lie une variable C à cette adresse.

```c
__sfr __at (0x80) P0;   __sfr __at (0x90) P1;   __sfr __at (0xA0) P2;
__sfr __at (0xFD) P0DIR; __sfr __at (0xFE) P1DIR; __sfr __at (0xFF) P2DIR;
__sfr __at (0xF3) P0SEL; __sfr __at (0xF4) P1SEL; __sfr __at (0xF5) P2SEL;

void delay(void){ volatile unsigned long i; for(i=0;i<60000UL;i++); }

void main(void){
    P0SEL=0; P1SEL=0; P2SEL=0;   // tout en GPIO
    P0DIR=0xFF; P1DIR=0xFF; P2DIR=0xFF;   // tout en sortie
    while(1){
        P0=0xFF; P1=0xFF; P2=0xFF; delay();
        P0=0x00; P1=0x00; P2=0x00; delay();
    }
}
```
> `P0/P1/P2` (0x80/0x90/0xA0) sont standard 8051. `PxDIR`/`PxSEL` (0xFD–0xFF /
> 0xF3–0xF5) sont **spécifiques au CC2510** → aucun header générique ne marche.
> On balaye les 3 ports pour trouver la LED sans en connaître le pin exact.

### Compilation
```bash
sdcc -mmcs51 --model-small --code-size 0x8000 --xram-size 0x1000 blink.c
```
→ produit `blink.ihx`.

### `.ihx` → `.hex` sans packihx
`packihex` absent de SDCC Homebrew, mais **inutile** : le `.ihx` de SDCC est déjà de
l'Intel HEX valide que le parser mange. L'extension compte (détection du format) :
```bash
cp blink.ihx blink.hex
```
Vérif rapide : `head -3 blink.hex` (lignes en `:`, adresses < `8000`),
`tail -2` doit finir par `:00000001FF`.

### Flash et mass erase
```bash
python3 cc_write_flash.py --erase -i blink.hex -p /dev/cu.usbmodem101   # taper y
```
`--erase` = chip erase (lève le lock) puis écrit. **Résultat : le blink a tourné**
(preuve que du code perso s'exécute sur la puce). Débrancher le Pico avant
d'observer (P2 est balayé et contient DD/DC).

---

## 10. Firmware d'affichage d'image (angrymew)

Projet fait pour cette puce précise : `angrymew/firmware-cc2510` (« Imagotag 2.6 BWR
GL120/GU140, CC2510 »). Contient driver EPD (IL0373), pinout de la carte, résolution
152×296, et une image de test.

```bash
git clone https://github.com/angrymew/firmware-cc2510.git
```

### `make.sh` réécrit pour macOS
L'original appelle `sdcc.exe` et `packihx` (Windows) :
```bash
#!/bin/bash
set -e
mkdir -p build
find ./src -name "*.c" -type f | xargs -L 1 sdcc -mmcs51 -o ./build/ -c
find ./build -name "*.rel" -type f ! -name main.rel | xargs sdcc -o ./build/ ./build/main.rel
cp build/main.ihx build/main.hex
```
Étapes : compile chaque `.c` en `.rel`, linke tous les `.rel` (main.rel en premier),
renomme `.ihx` → `.hex`. Les `warning 283 (no prototype)` sont inoffensifs.

Flash → **l'image de test angry mew s'est affichée** (~15 s de refresh tricolore,
normal).

---

## 11. Organisation des dossiers `~/vusion/`

Séparer ce qui tourne sur le Mac (outil) de ce qui tourne sur la puce (firmwares) :

```
~/vusion/
├── flash.sh              # raccourci de flash
├── host/
│   └── cclib/            # CCLib PATCHÉ (déplacé, jamais re-cloné)
│       └── Python/
│           ├── flash_page.py
│           └── cclib/chip/cc2510.py
└── firmware/
    ├── image/            # firmware angrymew
    └── blink/            # blink.c
```

Mise en place (CCLib **déplacé**, pas re-cloné, pour garder les patches) :
```bash
mkdir -p ~/vusion/host ~/vusion/firmware
mv ~/Downloads/CCLib ~/vusion/host/cclib
cd ~/vusion/firmware && git clone https://github.com/angrymew/firmware-cc2510.git image
```

> `~/Documents/Arduino/libraries/CCLib` **reste en place** (lib gérée par l'IDE, sert
> à recompiler le firmware du Pico). Ne pas y mettre ses fichiers perso.

Raccourci `~/vusion/flash.sh` :
```bash
#!/bin/bash
# usage: ./flash.sh <fichier.hex>
PYTHONPATH=~/vusion/host/cclib/Python \
  python3 ~/vusion/host/cclib/Python/flash_page.py -i "$1" -p /dev/cu.usbmodem101
```
```bash
chmod +x ~/vusion/flash.sh
```
`PYTHONPATH` permet de trouver le module `cclib` quel que soit le dossier courant.

**Workflow quotidien :**
```bash
cd ~/vusion/firmware/image && ./make.sh        # compile
cd ~/vusion && ./flash.sh firmware/image/build/main.hex   # flashe
```

---

## 12. Conversion d'une image perso

### Conventions du buffer (lues dans `epd.c`)
`epd_clearDisplay` envoie `0xFF` partout pour du blanc → donc :
- **Plan BW (cmd 0x10)** : bit `1` = blanc, bit `0` = noir. MSB = pixel de gauche.
- **Plan R (cmd 0x13)** : **inversé** — bit `0` = rouge, bit `1` = rien.
- Un pixel rouge l'emporte sur le noir.
- **19 octets/ligne** (152/8), **296 lignes**, **5624 octets/plan**.

### Traitement (script `convert.py`)
Objectif demandé : silhouette noire, mouchetures **intérieures** en rouge (au lieu de
blanc), gris en rouge, fond blanc conservé, image déformée en 152×296.

Le point clé : distinguer **le blanc du fond** du **blanc enclavé** dans le corps
(même couleur, traitement différent). Solution = **flood-fill** :
- blanc connecté au bord de l'image = fond → reste blanc ;
- blanc enclavé dans le noir = moucheture → rouge.
Le gris part en rouge par seuil de luminance. Chaque masque est ensuite étiré en
152×296 au plus proche voisin (NEAREST) pour ne pas créer de gris intermédiaires.

Packing : pour chaque octet, MSB = pixel de gauche ; BW `1=blanc/0=noir` ;
R `0=rouge/1=rien` ; rouge prioritaire sur noir.

### Bug « Multiple definition of _imageBW / _imageR »
Cause structurelle : les tableaux étaient **définis dans `epd.h`**, un header inclus
par **deux** `.c` (`main.c` et `epd.c`) → chaque `.c` crée sa copie → conflit au link.
**Règle : jamais de définition de variable dans un header.**

Fix : le header ne *déclare* (`extern`), un seul `.c` *définit*.
- `epd.h` :
```c
extern __code const uint8_t imageBW[];
extern __code const uint8_t imageR[];
```
- nouveau `src/display/images.c` : les deux gros tableaux, définis **une seule fois**.
`make.sh` le compile automatiquement (`find ./src -name "*.c"`).

---

## 13. État actuel et pistes

**Fait :** prise de contrôle complète de la puce, blink validé, image de test puis
image perso affichées. Aucun composant dessoudé.

**Points à surveiller au premier affichage d'une image perso :**
- **Orientation** : si l'image sort tournée/miroir → inverser l'ordre des lignes ou
  des octets dans le packing (pas l'encodage).
- **Rendu moucheté** : les points rouges d'un seul pixel peuvent baver sur la dalle
  → épaissir les zones rouges si trop bruité.

**Hygiène de la dalle :** ne pas laisser l'e-paper sous tension DC en continu avec une
image affichée (dégradation). Remplacer le `while(1){}` de `main()` par un
`epd_sleep()` en fin de programme. Compter ~15 s par refresh tricolore, ne pas
boucler dessus.

**Suites possibles :** réveil périodique de la puce (afficher l'heure / une donnée
qui change), passage à d'autres images via `convert.py`.

---

## 14. Aide-mémoire commandes

```bash
# lire l'état de la puce
cd ~/vusion/host/cclib/Python && python3 cc_info.py -E -p /dev/cu.usbmodem101

# compiler un firmware
cd ~/vusion/firmware/image && ./make.sh

# flasher
cd ~/vusion && ./flash.sh firmware/image/build/main.hex

# compiler un .c isolé (blink)
sdcc -mmcs51 --model-small --code-size 0x8000 --xram-size 0x1000 blink.c
cp blink.ihx blink.hex
```

**Fichiers patchés à ne pas perdre** (dans `~/vusion/host/cclib/Python/`) :
- `cclib/ccproxy.py` — lignes 203 et 399 (`bytes([...])`)
- `cclib/chip/cc2510.py` — `flash:32`, les `//`, la méthode `setPC`
- `flash_page.py` — script maison (`debug_active`, `show_debug_info`)
