"""Messages shown by the CLI and the web app, in English and French."""
import locale
import os

LANGS = ("en", "fr")

MSG = {
    # ----------------------------------------------------------- generic
    "op.cancelled": ("Cancelled.", "Annulé."),
    "op.failed": ("Failed: {err}", "Échec : {err}"),
    "op.busy": ("Another operation is already running.", "Une autre opération est déjà en cours."),
    "op.done": ("Done.", "Terminé."),
    "deps.missing": ("Missing Python package '{pkg}'. Run: ./monopink.sh setup",
                     "Paquet Python « {pkg} » manquant. Lance : ./monopink.sh setup"),
    "sim.banner": ("SIMULATION MODE - no hardware is used.",
                   "MODE SIMULATION - aucun matériel n'est utilisé."),

    # ----------------------------------------------------------- pins
    "pins.invalid": ("Invalid pin numbers.", "Numéros de broches invalides."),
    "pins.not_on_header": ("Use GPIOs available on the Pico header (GP0-GP22, GP26-GP28).",
                           "Utilise des GPIO présents sur le connecteur du Pico (GP0-GP22, GP26-GP28)."),
    "pins.duplicate": ("RST, DC and DD must be on different GPIOs (only DD_IN and DD_OUT may share one).",
                       "RST, DC et DD doivent être sur des GPIO différents (seuls DD_IN et DD_OUT peuvent être partagés)."),

    # ----------------------------------------------------------- probe
    "probe.searching": ("Looking for the Pico probe…", "Recherche de la sonde Pico…"),
    "probe.found": ("Probe on {port}: {kind}", "Sonde sur {port} : {kind}"),
    "probe.not_found": (
        "No probe found. Is the Pico plugged in with a USB *data* cable, and running the MonopInk "
        "(or CCLib_proxy) firmware?",
        "Aucune sonde trouvée. Le Pico est-il branché avec un câble USB *de données*, et flashé avec "
        "le firmware MonopInk (ou CCLib_proxy) ?"),
    "probe.kind.monopink": ("MonopInk probe v{version} ({board})", "sonde MonopInk v{version} ({board})"),
    "probe.kind.cclib": ("CCLib_proxy (original firmware)", "CCLib_proxy (firmware d'origine)"),
    "probe.cclib_hint": (
        "This Pico runs the original CCLib_proxy sketch. It works, but installing the MonopInk probe "
        "firmware makes transfers much faster and lets you change pins without recompiling.",
        "Ce Pico tourne avec le sketch CCLib_proxy d'origine. Ça marche, mais le firmware MonopInk "
        "rend les transferts bien plus rapides et permet de changer les broches sans recompiler."),
    "probe.pins": ("Probe pins: RST=GP{rst}  DC=GP{dc}  DD_IN=GP{dd_i}  DD_OUT=GP{dd_o}",
                   "Broches de la sonde : RST=GP{rst}  DC=GP{dc}  DD_IN=GP{dd_i}  DD_OUT=GP{dd_o}"),
    "probe.pins_differ": (
        "The pins stored in the Pico differ from your settings. Apply them (step 'Pico') or the label will not answer.",
        "Les broches enregistrées dans le Pico diffèrent de tes réglages. Applique-les (étape « Pico ») sinon "
        "l'étiquette ne répondra pas."),

    # ----------------------------------------------------------- pico flashing
    "pico.flash.start": ("Installing the MonopInk probe firmware on the Pico",
                         "Installation du firmware sonde MonopInk sur le Pico"),
    "pico.touch": ("Asking the Pico on {port} to reboot into BOOTSEL mode…",
                   "Demande au Pico sur {port} de redémarrer en mode BOOTSEL…"),
    "pico.hold_bootsel": (
        "Unplug the Pico, hold its BOOTSEL button, plug it back in, then release the button.",
        "Débranche le Pico, maintiens son bouton BOOTSEL, rebranche-le, puis relâche le bouton."),
    "pico.waiting_bootsel": ("Waiting for the RPI-RP2 / RP2350 drive (up to {s} s)…",
                             "En attente du disque RPI-RP2 / RP2350 (jusqu'à {s} s)…"),
    "pico.no_bootsel": ("No BOOTSEL drive appeared.", "Aucun disque BOOTSEL n'est apparu."),
    "pico.bootsel_found": ("BOOTSEL drive found: {path} ({board})", "Disque BOOTSEL trouvé : {path} ({board})"),
    "pico.no_uf2": ("No probe firmware for board '{board}'.", "Pas de firmware sonde pour la carte « {board} »."),
    "pico.copying": ("Copying {file}…", "Copie de {file}…"),
    "pico.rebooting": ("The Pico is rebooting…", "Le Pico redémarre…"),
    "pico.not_back": ("The Pico did not come back as a MonopInk probe within {s} s.",
                      "Le Pico n'est pas revenu en sonde MonopInk en {s} s."),
    "pico.back": ("MonopInk probe v{version} ({board}) ready on {port}",
                  "Sonde MonopInk v{version} ({board}) prête sur {port}"),
    "pico.pins_set": ("Pins saved in the Pico: RST=GP{rst}, DC=GP{dc}, DD_IN=GP{dd_i}, DD_OUT=GP{dd_o}",
                      "Broches enregistrées dans le Pico : RST=GP{rst}, DC=GP{dc}, DD_IN=GP{dd_i}, DD_OUT=GP{dd_o}"),
    "pico.pins_mismatch": ("Pin read-back mismatch.", "La relecture des broches ne correspond pas."),
    "pico.needs_monopink": (
        "This needs the MonopInk probe firmware on the Pico (install it first).",
        "Il faut d'abord installer le firmware sonde MonopInk sur le Pico."),
    "pico.macos_note": (
        "macOS may say the disk was not ejected properly: that is normal (the Pico reboots).",
        "macOS peut dire que le disque n'a pas été éjecté correctement : c'est normal (le Pico redémarre)."),

    # ----------------------------------------------------------- label
    "tag.connecting": ("Entering debug mode on the CC2510…", "Passage du CC2510 en mode debug…"),
    "tag.not_responding": (
        "The CC2510 does not answer. Check: 3.3 V and GND on the battery contacts, batteries removed, "
        "RESET wired, DD and DC not swapped, and the Pico pins match your wiring.",
        "Le CC2510 ne répond pas. Vérifie : 3,3 V et GND sur les contacts de piles, piles retirées, "
        "RESET câblé, DD et DC non inversés, et que les broches du Pico correspondent à ton câblage."),
    "tag.unsupported_chip": ("Unexpected chip ID {chip}: this is not a CC2510.",
                             "Chip ID inattendu {chip} : ce n'est pas un CC2510."),
    "tag.found": ("{chip} found (chip ID {chip_id}, revision {revision})",
                  "{chip} détecté (chip ID {chip_id}, révision {revision})"),
    "tag.locked": (
        "Debug lock is ON: the original SES firmware is read-protected. A full erase is needed (it also clears the lock).",
        "Le debug lock est ACTIF : le firmware SES d'origine est protégé. Un effacement complet est nécessaire (il lève aussi le verrou)."),
    "tag.unlocked": ("Debug lock is off.", "Le debug lock est désactivé."),
    "tag.fw_installed": ("MonopInk firmware v{version} is installed.", "Le firmware MonopInk v{version} est installé."),
    "tag.fw_blank": ("The flash is blank.", "La flash est vierge."),
    "tag.fw_other": ("Another firmware is installed (not MonopInk).", "Un autre firmware est installé (pas MonopInk)."),
    "tag.locked_need_erase": (
        "The chip is locked: the full erase must be confirmed (--erase / checkbox).",
        "La puce est verrouillée : l'effacement complet doit être confirmé (--erase / case à cocher)."),
    "tag.erasing": ("Mass erase (original firmware + debug lock)…", "Effacement complet (firmware d'origine + debug lock)…"),
    "tag.erased": ("Chip erased, debug lock cleared.", "Puce effacée, debug lock levé."),
    "tag.erase_failed": ("Erase failed: the chip is still locked or not blank.",
                         "Échec de l'effacement : la puce est encore verrouillée ou pas vierge."),
    "tag.programming": ("Writing {n} flash pages, then reading them back…",
                        "Écriture de {n} pages de flash, puis relecture…"),
    "tag.programmed": ("{n} pages written and verified in {s} s.", "{n} pages écrites et vérifiées en {s} s."),
    "tag.flash_timeout": ("Flash write timed out at {addr}.", "Délai dépassé pendant l'écriture flash à {addr}."),
    "tag.verify_failed": ("Verification failed at {addr}: the flash does not contain what was written.",
                          "Vérification échouée à {addr} : la flash ne contient pas ce qui a été écrit."),
    "tag.no_firmware": (
        "The MonopInk firmware is not installed on the label yet (do the 'Label' step first).",
        "Le firmware MonopInk n'est pas encore installé sur l'étiquette (fais d'abord l'étape « Étiquette »)."),
    "tag.fw_outdated": ("Label firmware v{have} is older than v{want}: reinstall it from the 'Label' step.",
                        "Le firmware de l'étiquette v{have} est plus ancien que v{want} : réinstalle-le depuis l'étape « Étiquette »."),
    "tag.running": ("Starting the label and watching the display refresh…",
                    "Démarrage de l'étiquette et suivi du rafraîchissement…"),
    "tag.state": ("{state}  (+{t} s)", "{state}  (+{t} s)"),
    "tag.refresh_ok": (
        "Display refreshed in {s} s. The picture stays without power: you can unplug the Pico.",
        "Écran rafraîchi en {s} s. L'image reste sans alimentation : tu peux débrancher le Pico."),
    "tag.refresh_too_fast": (
        "The refresh ended after only {s} s: the display is probably not connected (BUSY never went low).",
        "Le rafraîchissement s'est terminé en {s} s seulement : l'écran n'est sans doute pas connecté (BUSY jamais à 0)."),
    "tag.err_busy_on": (
        "The display did not power up (BUSY stuck). Power the label through its battery contacts "
        "(see Wiring) and check the panel flex cable.",
        "L'écran ne s'est pas allumé (BUSY bloqué). Alimente l'étiquette par ses contacts de piles "
        "(voir Câblage) et vérifie la nappe de la dalle."),
    "tag.err_busy_refresh": ("The display refresh never finished (timeout).",
                             "Le rafraîchissement ne s'est jamais terminé (délai dépassé)."),
    "tag.err_busy_off": ("Display power-off timed out (the picture is probably fine).",
                         "Délai dépassé à l'extinction de l'écran (l'image est probablement bonne)."),
    "tag.run_timeout": ("No news from the firmware after {s} s.", "Pas de nouvelles du firmware après {s} s."),
    "tag.dumped": ("Flash saved to {path}", "Flash sauvegardée dans {path}"),
    "tag.reset_done": ("Label reset: it boots normally (not in debug mode).",
                       "Étiquette réinitialisée : elle démarre normalement (hors mode debug)."),
    "tag.install.start": ("Installing the MonopInk firmware on the label", "Installation du firmware MonopInk sur l'étiquette"),
    "tag.image.start": ("Sending the picture to the label", "Envoi de l'image sur l'étiquette"),
    "tag.default_image": ("No picture yet: the orientation test card will be displayed.",
                          "Pas encore d'image : la mire d'orientation sera affichée."),

    "hex.invalid": ("Not a valid Intel HEX file: {err}", "Fichier Intel HEX invalide : {err}"),
    "hex.start": ("Flashing a custom firmware ({n} bytes)", "Flash d'un firmware personnalisé ({n} octets)"),
    "hex.running": ("Label reset: the new firmware is running (the Pico lines are released).",
                    "Étiquette réinitialisée : le nouveau firmware tourne (lignes du Pico libérées)."),

    "boot.start": ("Autonomous start test (plain reset, as on batteries)",
                   "Test de démarrage autonome (reset simple, comme sur piles)"),
    "boot.waiting": ("The label starts on its own; reading the result in {s} s…",
                     "L'étiquette démarre seule ; lecture du résultat dans {s} s…"),
    "boot.ok": ("Autonomous start OK: the label refreshed its display by itself in {s} s. It will work on batteries.",
                "Démarrage autonome OK : l'étiquette a rafraîchi son écran toute seule en {s} s. Elle fonctionnera sur piles."),
    "boot.incomplete": ("The firmware did not finish its sequence (state {state}).",
                        "Le firmware n'a pas terminé sa séquence (état {state})."),

    "nfc.info.start": ("NFC chip diagnostic", "Diagnostic de la puce NFC"),
    "nfc.need_fw13": ("This needs the MonopInk label firmware 1.3 or newer: reinstall it (step 'Label').",
                      "Il faut le firmware étiquette MonopInk 1.3 ou plus récent : réinstalle-le (étape « Étiquette »)."),
    "nfc.diag_failed": ("The NFC diagnostic did not complete.", "Le diagnostic NFC ne s'est pas terminé."),
    "nfc.no_chip": ("The NFC chip does not answer on I2C.", "La puce NFC ne répond pas en I2C."),
    "nfc.chip": ("NTAG I2C plus {variant} found (UID {uid})", "NTAG I2C plus {variant} détectée (UID {uid})"),
    "nfc.details": ("CC {cc} · config {config} · AUTH0 {auth0} · ACCESS {access} · locks {lock}",
                    "CC {cc} · config {config} · AUTH0 {auth0} · ACCESS {access} · verrous {lock}"),
    "nfc.fd": ("Field-detect line pulled high: {off} with the chip off, {on} with the chip on (1 = pull-up present)",
               "Ligne de détection de champ tirée à 1 : {off} puce éteinte, {on} puce allumée (1 = pull-up présent)"),
    "nfc.password": ("A password protects part of the NFC memory (AUTH0 < EBh).",
                     "Un mot de passe protège une partie de la mémoire NFC (AUTH0 < EBh)."),
    "nfc.fd_wake": ("Wake-up on NFC: instant (the field-detect line has a pull-up on the board) - sleep ~1 µA.",
                    "Réveil NFC : instantané (la ligne de détection de champ a un pull-up sur la carte) - veille ~1 µA."),
    "nfc.fd_polling": ("The field-detect line has no pull-up with the chip off: on batteries the label checks the NFC chip every 2 s instead (sleep ~15 µA, wait 2-3 s between taps).",
                       "La ligne de détection de champ n'a pas de pull-up puce éteinte : sur piles l'étiquette interroge la puce NFC toutes les 2 s à la place (veille ~15 µA, attendre 2-3 s entre les tapes)."),
    "nfc.locked": ("NFC memory locked for phones (locks {lock}, factory setting of store labels): a phone could only write 48 bytes. Firmware 1.4+ clears these locks by itself as soon as the label starts normally (Phone mode) or receives a picture.",
                   "Mémoire NFC verrouillée pour les téléphones (verrous {lock}, réglage d'usine des étiquettes de magasin) : un téléphone ne pourrait écrire que 48 octets. Le firmware 1.4+ enlève ces verrous tout seul dès que l'étiquette démarre normalement (Mode téléphone) ou reçoit une image."),
    "nfc.url_invalid": ("The phone page address must start with https:// (Web NFC only works on secure pages).",
                        "L'adresse de la page téléphone doit commencer par https:// (Web NFC ne marche que sur des pages sécurisées)."),
    "nfc.send.start": ("NFC upload test: {size} bytes compressed, {n} part(s) (the Pico plays the phone)",
                       "Test d'envoi NFC : {size} octets compressés, {n} morceau(x) (le Pico joue le téléphone)"),
    "nfc.part_ok": ("Part {i}/{n} accepted by the label (next expected: {next})",
                    "Morceau {i}/{n} accepté par l'étiquette (suivant attendu : {next})"),
    "nfc.part_refused": ("Part {i} refused by the label ({err}).", "Morceau {i} refusé par l'étiquette ({err})."),
    "nfc.not_complete": ("All parts were sent but the label did not complete the picture.",
                         "Tous les morceaux sont envoyés mais l'étiquette n'a pas terminé l'image."),
    "nfc.test_timeout": ("The label did not finish processing the NFC data.",
                         "L'étiquette n'a pas fini de traiter les données NFC."),
    "nfc.send.done": ("Picture received over the NFC protocol, decoded and displayed (refresh {s} s).",
                      "Image reçue par le protocole NFC, décodée et affichée (rafraîchissement {s} s)."),

    # ----------------------------------------------------------- firmware states
    "state.16": ("Firmware started", "Firmware démarré"),
    "state.32": ("Panel powered", "Dalle alimentée"),
    "state.48": ("Panel initialised", "Dalle initialisée"),
    "state.64": ("Picture sent to the panel", "Image envoyée à la dalle"),
    "state.80": ("Refreshing (about 20 s)…", "Rafraîchissement (environ 20 s)…"),
    "state.96": ("Refresh finished", "Rafraîchissement terminé"),
    "state.112": ("Panel switched off", "Dalle éteinte"),
    "state.128": ("Done", "Terminé"),
    "state.unknown": ("Unknown state 0x{v:02x}", "État inconnu 0x{v:02x}"),

    # ----------------------------------------------------------- image
    "image.none": ("No picture loaded.", "Aucune image chargée."),
    "image.saved": ("Written: {path}", "Écrit : {path}"),
    "image.converted": ("Converted: {white}% white, {black}% black, {red}% red",
                        "Converti : {white} % blanc, {black} % noir, {red} % rouge"),
}


def detect_lang():
    for var in ("MONOPINK_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return "fr" if v.lower().startswith("fr") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""
    return "fr" if loc.lower().startswith("fr") else "en"


def norm_lang(lang):
    return lang if lang in LANGS else detect_lang()


def t(key, lang="en", **kw):
    entry = MSG.get(key)
    if entry is None:
        text = key
    else:
        text = entry[LANGS.index(lang) if lang in LANGS else 0]
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


def state_text(v, lang):
    key = f"state.{v}"
    if key in MSG:
        return t(key, lang)
    return t("state.unknown", lang, v=v if isinstance(v, int) else 0)
