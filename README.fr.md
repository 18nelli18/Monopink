# MonopInk

**Affiche tes propres images sur une étiquette e-ink SES-imagotag VUSION 2.6 BWR (GL420).**

*[English version → README.md](README.md)*

MonopInk prend le contrôle de l'étiquette par le port de debug d'usine de son
microcontrôleur (TI CC2510), avec un Raspberry Pi Pico comme programmateur.
Aucun composant n'est dessoudé. Tout se fait depuis une **interface web**
(français / anglais) ou en **ligne de commande** :

1. tu indiques à l'appli quels GPIO du Pico tu as câblés,
2. un clic flashe le firmware sonde sur le Pico,
3. un clic efface le firmware verrouillé du magasin et installe le firmware MonopInk,
4. tu déposes n'importe quelle image, tu ajustes la conversion, tu prévisualises, tu envoies,
5. ou tu envoies des images **depuis un téléphone Android en NFC**, sans le Pico —
   la puce NFC de l'étiquette les reçoit, même sur piles ([docs/NFC.md](docs/NFC.md)).

![câblage](docs/img/wiring.svg)

---

## ⚠️ À lire avant tout

- Le firmware SES d'origine est **protégé en lecture** et sera **définitivement
  effacé** (impossible de le sauvegarder). L'étiquette ne fonctionnera plus jamais
  avec le système du magasin. Ne le fais que sur une étiquette qui t'appartient.
- Alimente l'étiquette par ses **contacts de piles** (+ et −) avec le 3V3 du Pico,
  piles retirées. **Jamais** de 3,3 V sur la broche **DCOUPL** du CC2510 : c'est la
  sortie du régulateur interne 1,8 V, l'alimenter détruit la puce.

## Ce qu'il te faut

| | |
|---|---|
| Étiquette | SES-imagotag **VUSION 2.6 BWR GL420** — TI CC2510F32, e-paper 152 × 296 noir/blanc/rouge (contrôleur IL0373) |
| Programmateur | **Raspberry Pi Pico** (RP2040) ou **Pico 2** (RP2350) — les versions W marchent aussi |
| Câble | un câble USB qui transporte les **données** (beaucoup de câbles bon marché ne font que charger) |
| Outils | 5 fils fins (< 15 cm), fer à souder à panne fine, idéalement un multimètre |
| Ordinateur | macOS, Linux ou Windows avec **Python 3.8+** (internet nécessaire une fois, pour installer 2 paquets Python) |

Rien d'autre : pas d'IDE Arduino, pas de SDCC, aucun fichier à patcher. Les
firmwares prêts à l'emploi sont fournis.

## Démarrage rapide

**macOS / Linux**

```bash
cd MonopInk
./monopink.sh
```

Le premier lancement crée un environnement Python privé dans `.venv/` (installe
`pyserial` et `Pillow`, rien au niveau du système) et ouvre
<http://127.0.0.1:8420/> dans ton navigateur. Sur macOS tu peux aussi
double-cliquer sur **`Start MonopInk.command`** (la première fois : clic droit → Ouvrir).

**Windows** : double-clique sur **`monopink.bat`** (installe d'abord Python depuis
python.org en cochant *« Add python.exe to PATH »*).

**Essayer sans matériel** : `./monopink.sh --sim` déroule tout le parcours sur un
Pico et une étiquette simulés.

Ensuite, suis les étapes de la barre latérale de la page web.

## Câblage

GPIO par défaut (tu peux en choisir d'autres à l'étape *Câblage* — les broches
sont enregistrées dans le Pico, rien à recompiler) :

| Pico | Broche Pico | Étiquette (CC2510) | Où souder |
|---|---|---|---|
| 3V3 OUT | 36 | **Contact + des piles** | piles retirées |
| GND | 38 | **Contact − des piles** | |
| GP3 | 5 | **RESET_N** | reset du CC2510 |
| GP4 | 6 | **DC** = P2_2 | partagée avec l'enable du survolteur de la LED (TPS61071) : facile à atteindre là |
| GP6 + GP7 (reliés) | 9 + 10 | **DD** = P2_1 | partagée avec la LED blanche : facile à atteindre côté LED |

- DD est bidirectionnelle : le montage CCLib éprouvé utilise deux GPIO reliés
  (l'un lit, l'autre pilote) et un seul fil vers l'étiquette. Un mode à un seul
  GPIO existe (case *« DD sur un seul GPIO »*) mais n'a pas encore été validé sur
  le matériel.
- Le Pico et le CC2510 sont tous deux en 3,3 V : **pas de résistance, pas
  d'adaptateur de niveau**.
- Garde des fils courts : l'entrée en mode debug est sensible au timing.
- **Pourquoi les contacts de piles et pas DVDD ?** Mesuré sur une vraie GL420 :
  l'écran est alimenté par le rail des piles. Avec le 3,3 V seulement sur la
  broche DVDD du CC2510 (comme dans le journal d'origine), la puce se flashe et
  l'écran se rafraîchit en général tant que l'appli dialogue avec la puce, mais il
  ne se rafraîchit **pas** tout seul (reset, piles). Sur les contacts de piles tout
  fonctionne. Vérifie ton câblage avec *Outils → Tester le démarrage autonome*
  (`./monopink.sh boot-test`).

## L'interface web, étape par étape

1. **Avant de commencer** — liste de contrôle et vérification de l'installation.
2. **Câblage** — clique un rôle (RESET, DC, DD) puis une broche sur le dessin du
   Pico, ou utilise les menus. Le tableau des connexions se met à jour en direct.
3. **Sonde Pico** — branche le Pico et clique *Installer le firmware MonopInk sur le Pico*.
   S'il exécute déjà un firmware Arduino (ex. CCLib_proxy), l'appli le fait
   redémarrer toute seule en mode BOOTSEL ; sinon elle te demande de maintenir
   BOOTSEL en le branchant. Le `.uf2` est copié, le Pico redémarre et tes broches
   sont enregistrées dans sa flash. RP2040 et RP2350 sont détectés automatiquement.
4. **Étiquette** — *Tester la connexion* lit le chip ID (0x81xx = CC2510), le
   debug lock et le firmware installé. Une étiquette de magasin est verrouillée :
   coche la confirmation puis *Effacer & installer*. L'appli efface entièrement la
   puce (ce qui lève le verrou), écrit le firmware + une mire d'orientation,
   **relit tout pour vérifier**, démarre l'étiquette et **suit le rafraîchissement
   de l'écran en direct** (≈ 20 s pour un rafraîchissement 3 couleurs).
5. **Image** — dépose / colle / choisis une image (JPG, PNG, GIF, WebP, BMP…),
   choisis portrait ou paysage, le cadrage (remplir / ajuster / étirer), le rendu :
   - *Tramage* — photos (tramage noir/blanc, rouge seulement là où l'image est rouge),
   - *Seuil* — logos, texte, dessins en aplats,
   - *Niveaux* — sombre → noir, tons moyens → rouge, clair → blanc,
   plus luminosité, contraste, sensibilité au rouge, inversion, redimensionnement
   net et *« zones blanches enclavées → rouge »*. L'aperçu montre ce que la dalle
   affichera. *Envoyer sur l'étiquette* ne réécrit que la zone image de 11 Ko
   (quelques secondes) et montre le rafraîchissement. Tu peux aussi télécharger
   l'aperçu, un `.hex` complet (firmware + image, pour n'importe quel programmateur
   CC), les plans bruts, ou un `images.c` pour le firmware angrymew.
6. **NFC (téléphone)** — vérifie la puce NFC de l'étiquette, teste un envoi NFC
   avec le Pico dans le rôle du téléphone, et donne le lien vers la page
   téléphone (voir [Images depuis un téléphone](#images-depuis-un-téléphone-nfc)).
7. **Outils & réglages** — rafraîchir à nouveau, **test de démarrage autonome**
   (reset simple comme sur piles, puis vérification que l'étiquette a redessiné
   son image toute seule), reset simple, sauvegarde de la flash, firmware `.hex`
   personnalisé, port série, langue, **calibration de l'affichage** (rotation
   180° / miroir si la mire apparaît dans le mauvais sens — inutile sur la GL420
   testée).

La barre **Activité** en bas affiche le journal de chaque opération, avec une
barre de progression et un bouton *Annuler*.

Une fois le rafraîchissement terminé, l'image reste sur l'e-paper **sans aucune
alimentation** : débranche le Pico. Avec des piles, l'étiquette redessine l'image
à chaque mise sous tension puis dort jusqu'à ce qu'un téléphone approche (NFC).

## Images depuis un téléphone (NFC)

Avec le firmware étiquette **1.4+**, un téléphone Android (Chrome) peut remplacer
l'image par la puce NFC de l'étiquette — sans Pico, sans ordinateur, étiquette
sur piles.

1. **Publier la page téléphone (une fois)** — elle doit être servie en
   `https://`. Avec GitHub : pousse ce dossier dans un dépôt, puis *Settings →
   Pages → Deploy from a branch → `main`, dossier `/docs`*. La page est alors à
   `https://<utilisateur>.github.io/<dépôt>/nfc/`. Colle cette adresse dans
   l'appli web (étape *NFC (téléphone)*) pour obtenir un lien prêt pour le
   téléphone (il transmet aussi la langue et la calibration).
2. **Vérifier l'étiquette** — étape *NFC (téléphone)* : *Vérifier la puce NFC*,
   éventuellement *Tester un envoi NFC* (le Pico joue le téléphone), puis *Mode
   téléphone* (ou mets les piles).
3. **Sur le téléphone** — ouvre la page, choisis une image, règle-la (mêmes
   réglages que sur l'ordinateur), appuie sur *Envoyer* et pose le téléphone sur
   l'étiquette une fois par morceau (1 tape pour du texte/un logo, 4 à 8 pour une
   photo tramée). La page guide chaque tape ; l'étiquette affiche la nouvelle image
   ~30 s après la dernière (~10 s de décodage + ~20 s de rafraîchissement).

Fonctionnement, protocole, consommation et limites : [docs/NFC.md](docs/NFC.md)
(en anglais). En bref :

- une tape = le téléphone lit l'état de l'étiquette puis écrit le morceau
  qu'elle attend (≤ 832 octets) ; l'étiquette le lit quand le téléphone
  s'éloigne, le vérifie (CRC) et le range en flash ; au dernier morceau elle
  décode l'image (compression dédiée, 0,3 à 6 Ko) et rafraîchit l'écran ;
- une tape ratée, un doublon ou une coupure de piles sont rattrapés : l'état dit
  toujours quel morceau envoyer ;
- réveil : instantané (~1 µA en veille) si la ligne de détection de champ de la
  puce NFC a un pull-up sur la carte, sinon l'étiquette interroge la puce toutes
  les 2 s (~15 µA) — `nfc-info` indique le mode.

**État :** le chemin d'envoi marche sur la vraie étiquette (testé avec le Pico
dans le rôle du téléphone) ; le réveil sur piles et les tapes d'un vrai
téléphone ne sont pas encore testés.

## Testé sur le vrai matériel

Étiquette VUSION 2.6 BWR GL420 (CC2510F32, chip ID `0x8104`), Raspberry Pi Pico
(RP2040), macOS, broches par défaut. Câblage final : 3V3 sur les contacts de piles.

| Étape | Résultat |
|---|---|
| Pico sous CCLib_proxy d'origine → détection, infos étiquette (mode compatibilité) | ✔ |
| Firmware sonde installé depuis la page web (redémarrage BOOTSEL auto, copie, broches enregistrées) | ✔ 7 s |
| Mise à jour d'une sonde MonopInk existante (CLI) | ✔ |
| Lecture complète des 32 Ko, deux fois, identique, conforme au firmware flashé auparavant | ✔ 4,5 s |
| Firmware + mire : 14 pages écrites **et vérifiées** | ✔ 4,6 s |
| Image depuis la page web / la CLI : 11 pages écrites et vérifiées | ✔ 3,6 s |
| Rafraîchissement suivi en direct (3 couleurs) | ✔ 19,6–19,7 s |
| Orientation et couleurs de la mire, image perso en paysage — vérifiées à l'œil | ✔ aucune calibration nécessaire |
| Démarrage autonome (reset simple, comme sur piles), veille PM3, reconnexion | ✔ 8/8 avec le firmware 1.2 |
| Envoi NFC, le Pico jouant le téléphone : morceaux écrits dans la puce NFC et relus en I2C, rangés en flash par le firmware, décodés par le 8051 (identique au décodeur de référence), affichés — 1 morceau et 3 morceaux (logo de 1,9 Ko) | ✔ décodage ≈ 10 s + rafraîchissement 19,6 s |
| Puce NFC : verrous d'usine (`FF 3F 7F`, pages à partir de 10h en lecture seule pour les téléphones) enlevés par le firmware 1.4 ; pull-up présent sur la détection de champ → réveil instantané | ✔ |

Pas encore testé sur le matériel : le réveil NFC sur piles et les tapes d'un vrai téléphone, Pico 2 (RP2350), Windows, Linux, le mode DD sur un
seul GPIO, et l'effacement complet d'une puce réellement verrouillée (la nôtre
s'est avérée déjà déverrouillée ; ce chemin est couvert par le simulateur et suit
CCLib).

## Ligne de commande

Tout ce que fait la page web est disponible dans un terminal
(`./monopink.sh --help`, `./monopink.sh <commande> --help`). Ajoute `--lang fr`
pour les messages en français, `--sim` pour le simulateur, `--port
/dev/cu.usbmodemXXXX` pour forcer un port.

```bash
./monopink.sh doctor                     # vérifie Python, paquets, fichiers firmware
./monopink.sh ports                      # ports série, disques BOOTSEL, sondes et leurs broches
./monopink.sh pico-flash                 # installe le firmware sonde (broches par défaut)
./monopink.sh pico-flash --rst 2 --dc 3 --dd-in 4 --dd-out 5
./monopink.sh pico-pins --dd 6           # change les broches sans reflasher (DD sur un fil)
./monopink.sh info                       # chip ID, debug lock, firmware installé
./monopink.sh install                    # demande avant d'effacer une puce verrouillée
./monopink.sh install --erase --yes      # sans question
./monopink.sh image photo.jpg            # convertit + envoie + suit le rafraîchissement
./monopink.sh image logo.png --mode threshold --fit contain --preview apercu.png
./monopink.sh image chat.png --mode levels --fill-enclosed --orientation landscape
./monopink.sh test-pattern               # mire d'orientation
./monopink.sh config --rotate180 on      # calibration de l'affichage
./monopink.sh run                        # redessine et suit le rafraîchissement
./monopink.sh boot-test                  # test de démarrage autonome (comme sur piles)
./monopink.sh reset                      # reset simple (démarrage normal)
./monopink.sh flash-hex blink.hex        # n'importe quel firmware Intel HEX (--erase si verrouillée)
./monopink.sh dump flash.bin             # lit les 32 Ko de flash (puce déverrouillée)
./monopink.sh export photo.jpg --png p.png --hex etiquette.hex --bin plans.bin --c images.c
./monopink.sh nfc-info                   # diagnostic de la puce NFC, mode de réveil sur piles
./monopink.sh nfc-send photo.jpg         # test d'envoi NFC, le Pico joue le téléphone
./monopink.sh web --http-port 8420 --no-browser
```

Les réglages (broches, port, calibration, dernières options de conversion) sont
enregistrés dans `data/config.json` (`--sim` utilise `data/sim/` : les essais ne
touchent jamais aux données de la vraie étiquette).

À la question *« L'effacer maintenant ? [y/N] »*, réponds `y` (ou `o`) seul. Les
touches tapées avant l'apparition de la question sont ignorées.

## Dépannage

| Symptôme | Cause / solution |
|---|---|
| *Aucune sonde trouvée* | Câble USB de charge seule ; Pico pas encore flashé (fais l'étape Pico, elle gère BOOTSEL) ; sous Linux ton utilisateur doit avoir accès aux ports série : `sudo usermod -aG dialout $USER` (Arch : `uucp`) puis déconnexion/reconnexion. |
| Le disque BOOTSEL n'apparaît jamais | Maintiens BOOTSEL *avant* de brancher le câble USB, relâche après. Essaie un autre câble/port. Sous Linux le disque doit être monté automatiquement (la plupart des bureaux le font ; sinon monte-le sous `/media/$USER/RPI-RP2`). |
| macOS : *« Disque non éjecté correctement »* | Normal : le Pico redémarre juste après avoir reçu le firmware. |
| *Le CC2510 ne répond pas* | Pas de 3,3 V / masse sur les contacts de piles ; RESET non câblé ; DD et DC inversés ; fils trop longs ; broches du Pico différentes du câblage réel (l'appli le signale) ; piles encore en place. |
| *Chip ID inattendu* | Ce n'est pas une étiquette à CC2510 (d'autres modèles VUSION utilisent d'autres puces). |
| *Vérification échouée* | Mauvais contact / fils longs pendant le transfert : raccourcis les fils, recommence l'installation. |
| *Rafraîchissement trop court* | Le firmware a tourné mais l'écran n'a jamais été occupé : la nappe de la dalle est sans doute déconnectée. |
| *L'écran ne s'est pas allumé* / le test de démarrage autonome échoue | L'écran n'est pas alimenté : amène le 3,3 V sur les **contacts de piles** plutôt que sur DVDD ; vérifie la nappe de la dalle. |
| Puce annoncée *verrouillée* par d'autres outils | Juste après l'entrée en mode debug, le CC2510 signale `DEBUG_LOCKED` jusqu'à la première instruction de debug, même s'il n'est pas verrouillé (mesuré). MonopInk teste le verrou en exécutant une instruction ; `cc_info.py` de CCLib non, d'où de fausses alertes — c'est probablement ce qui s'est passé dans le journal d'origine. |
| Image à l'envers / en miroir | Outils → Calibration de l'affichage (rotation 180° / miroir), puis renvoie l'image. |
| Rouge moucheté | Utilise le mode *Seuil* ou baisse la sensibilité au rouge ; les traits rouges fins bavent sur cette dalle. |
| Page téléphone : *Web NFC n'est pas disponible* | Utilise Chrome sur Android, en `https://`, NFC activé. Impossible sur iPhone ou ordinateur. |
| Page téléphone : *pas une étiquette MonopInk* | L'étiquette a un ancien firmware : réinstalle-le (étape *Étiquette*, firmware 1.4+). |
| Page téléphone : *n'a pas encore pris le dernier morceau* | L'étiquette n'est pas alimentée (piles ?) ou interroge toutes les 2 s (`nfc-info` indique le mode de réveil) : éloigne, attends, retape. |
| Page téléphone : *trop complexe* | Plus de 6 Ko compressés : utilise *Seuil* / *Niveaux* ou une image plus simple. |

## Comment ça marche (version courte)

- **Pico = sonde.** `pico/monopink_probe` est un firmware compatible CCLib_proxy
  qui génère le protocole de debug 2 fils de TI. Extensions MonopInk : broches
  réglées par USB et stockées en flash, lecture/écriture par blocs (beaucoup plus
  rapide), reset et libération des lignes, mode debug activé à la demande. Le
  protocole CCLib_proxy est conservé.
- **Outil hôte** (`monopink/`, Python) : dialogue avec la sonde, efface la puce,
  programme la flash page par page avec une petite routine 8051 exécutée depuis la
  RAM (méthode TI SWRA124 / fishpepper — sans DMA), vérifie par relecture,
  convertit les images. Il fonctionne aussi avec un Pico qui exécute le sketch
  CCLib_proxy *d'origine* (plus lentement).
- **Firmware de l'étiquette** (`firmware/`, SDCC) : à chaque démarrage, alimente la
  dalle, envoie l'image stockée à une **adresse fixe de la flash (0x5000)**,
  rafraîchit une seule fois, éteint la dalle (deep sleep + coupure d'alim) et met
  le CC2510 en PM3. Comme l'image est à une adresse fixe, la changer ne réécrit
  que 11 pages de flash — aucun compilateur nécessaire. Le firmware publie sa
  progression en RAM ; l'appli la lit par le port de debug pour afficher le
  rafraîchissement en direct et diagnostiquer l'écran. Entre deux
  rafraîchissements il dort jusqu'à ce que le champ NFC d'un téléphone le
  réveille, puis reçoit une image compressée par la puce NTAG ([docs/NFC.md](docs/NFC.md)).

Détails : [docs/TECHNICAL.md](docs/TECHNICAL.md). Le journal de bidouille
d'origine dont ce projet est l'aboutissement : [docs/JOURNAL.fr.md](docs/JOURNAL.fr.md).
Toutes les corrections de CCLib décrites dans le journal (py2→py3, taille de
flash, divisions entières, `setPC`, attributs manquants) sont intégrées : il n'y
a plus rien à modifier à la main.

## Recompiler les firmwares (facultatif)

Seulement si tu les modifies — les fichiers prêts à l'emploi sont dans
`firmware/prebuilt/` et `pico/prebuilt/`.

```bash
brew install sdcc            # ou : sudo apt install sdcc
firmware/build.sh --install  # -> firmware/prebuilt/monopink-tag.hex

pico/build.sh                # nécessite arduino-cli + le core rp2040 d'earlephilhower
                             # (trouvé automatiquement dans l'IDE Arduino 2 sur macOS)
```

Tests (sans matériel) : `.venv/bin/python -m unittest discover -s tests -v`
(les tests NFC compilent aussi le firmware de l'étiquette en natif avec le
compilateur C du système et vérifient le JavaScript de la page téléphone avec
Node, s'ils sont disponibles).

## Organisation du projet

```
MonopInk/
├── monopink.sh / monopink.bat / Start MonopInk.command   lanceurs
├── monopink/            paquet Python (CLI, serveur web, sonde, CC2510, images, simulateur)
│   └── web/static/      interface web (HTML/CSS/JS, FR + EN, fonctionne hors ligne)
├── pico/                firmware sonde (sketch Arduino) + .uf2 prêts (RP2040, RP2350)
├── firmware/            firmware de l'étiquette (C / SDCC) + .hex prêt, exemple blink
├── docs/                notes techniques, NFC, journal d'origine, images
│   └── nfc/             page téléphone pour l'envoi NFC (statique, à publier en https)
├── tests/               tests automatiques (simulateur, protocole, API web, NFC + firmware natif)
└── data/                créé à l'exécution : réglages, dernière image
```

## Crédits & licence

- [CCLib](https://github.com/wavesoft/CCLib) d'Ioannis Charalampidis et Simon
  Schulz ([fishpepper](https://github.com/fishpepper)) — protocole de debug et
  routine d'écriture de page, dont dérive le firmware sonde.
- [angrymew/firmware-cc2510](https://github.com/angrymew/firmware-cc2510) et
  [andrei-tatar/imagotag-hack](https://github.com/andrei-tatar/imagotag-hack) —
  brochage de l'étiquette et initialisation de l'écran.
- [earlephilhower/arduino-pico](https://github.com/earlephilhower/arduino-pico) — core Arduino RP2040/RP2350.

MonopInk est distribué sous **GNU GPL v3** (voir `LICENSE`), comme CCLib.
VUSION et SES-imagotag sont des marques de leurs propriétaires ; ce projet n'y
est pas affilié.
