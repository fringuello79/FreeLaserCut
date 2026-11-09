# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Riconoscimento della macchina collegata (senza interfaccia: si prova anche col simulatore).

Tre livelli di indizi, dal più debole al più forte:
1. la porta USB: VID/PID dicono il chip ponte (CH340, CP210x, FTDI, ESP32 nativo) e quindi il driver;
2. il messaggio di avvio e $I: famiglia del firmware (GRBL 1.1, grblHAL, FluidNC, Grbl_ESP32),
   firmware del produttore (es. "LGT V1.2.3" = Longer), scheda, buffer di ricezione;
3. $$: area di lavoro ($130/$131), scala di potenza ($30), modalità laser ($32), homing ($22).

identify() mette insieme gli indizi e propone nome, profilo di partenza e avvisi.
probe() apre la porta, trova la velocità giusta e legge banner, $I e $$ (la porta deve essere libera).
"""
import math
import re
import time
from dataclasses import dataclass, field

from .profile import MachineProfile
from freelasercut.i18n import tr  # noqa: E402

# chip ponte USB-seriale: (VID, PID) -> (nome, famiglia driver).  PID None = qualsiasi.
USB_CHIPS = {
    (0x1A86, 0x7523): ("CH340", "wch"),
    (0x1A86, 0x7522): ("CH340K", "wch"),
    (0x1A86, 0x5523): ("CH341", "wch"),
    (0x1A86, 0x55D3): ("CH343", "wch"),
    (0x1A86, 0x55D4): ("CH9102", "wch"),
    (0x10C4, 0xEA60): ("CP2102/CP2104", "silabs"),
    (0x10C4, 0xEA70): ("CP2105", "silabs"),
    (0x0403, 0x6001): ("FT232R", "ftdi"),
    (0x0403, 0x6015): ("FT231X", "ftdi"),
    (0x303A, None): (tr("ESP32 (USB nativo)"), "native"),
    (0x2341, None): ("Arduino", "arduino"),
    (0x2A03, None): ("Arduino", "arduino"),
}

DRIVERS = {
    "wch": (tr("Driver WCH CH34x (CH340/CH341/CH9102)"), "https://www.wch-ic.com/downloads/CH341SER_EXE.html"),
    "silabs": (tr("Driver Silicon Labs CP210x"), "https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers"),
    "ftdi": (tr("Driver FTDI VCP"), "https://ftdichip.com/drivers/vcp-drivers/"),
    "native": (tr("Driver USB seriale di Windows (già incluso)"), ""),
    "arduino": (tr("Driver Arduino (incluso nell'IDE Arduino)"), "https://www.arduino.cc/en/software"),
}

# parole chiave nel banner/$I -> produttore
VENDORS = (
    ("Longer", ("LGT", "LONGER")),
    ("Ortur", ("ORTUR",)),
    ("Sculpfun", ("SCULPFUN",)),
    ("Atomstack", ("ATOMSTACK",)),
    ("Two Trees", ("TWOTREES", "TWO TREES")),
    ("Creality", ("CREALITY",)),
    ("NEJE", ("NEJE",)),
    ("Comgrow", ("COMGROW",)),
    ("Acmer", ("ACMER",)),
    ("AlgoLaser", ("ALGO_LASER", "ALGOLASER", "ALGO LASER")),
    ("SainSmart", ("GENMITSU", "SAINSMART", "JINSOKU")),
    ("Makerbase", ("MKS DLC", "MKS_DLC", "MKSDLC", "DLC32")),  # scheda montata su tanti laser e telai fai-da-te
    ("Mecpow", ("MECPOW",)),
)

_BAUDS = (115200, 250000, 230400, 57600, 38400, 9600)

# Incisori a diodo GRBL più diffusi: valori di targa per partire subito, anche senza la macchina collegata.
# Quando la colleghi, area di lavoro, scala di potenza, velocità e buffer si rileggono dalla scheda ($$, $I).
# (nome, produttore, area X, area Y mm, potenza ottica indicativa, velocità massima mm/min)
CATALOG = (
    ("Longer B1 40W", "Longer", 450, 440, "44–48 W", 36000),
    ("Longer B1 20W / 30W", "Longer", 450, 440, "20–30 W", 36000),
    # 0.13.5: la pagina ufficiale Longer distingue le aree (10W 400 × 400, 20W 400 × 365) e dà 10.000 mm/min
    ("Longer Ray5 10W", "Longer", 400, 400, "10 W", 10000),
    ("Longer Ray5 20W", "Longer", 365, 365, "20 W", 10000),
    ("Ortur Laser Master 3 (10W)", "Ortur", 400, 400, "10 W", 20000),
    ("Ortur Laser Master 3 (20W / 40W)", "Ortur", 400, 380, "20–40 W", 20000),
    ("Ortur Laser Master 2 Pro S2", "Ortur", 400, 430, "5–10 W", 10000),
    ("xTool D1 Pro", "xTool", 430, 390, "10–40 W", 24000),
    ("Atomstack A10 Pro V2", "Atomstack", 410, 380, "10 W", 24000),
    ("Atomstack X20 Pro / S20 Pro / A20 Pro", "Atomstack", 400, 400, "20 W", 20000),
    ("Atomstack X40 Pro / S40 Pro / A40 Pro", "Atomstack", 400, 400, "40 W", 20000),
    ("Sculpfun S9", "Sculpfun", 410, 420, "5,5 W", 10000),
    ("Sculpfun S10", "Sculpfun", 410, 400, "10 W", 10000),
    ("Sculpfun S30 / S30 Pro / S30 Pro Max", "Sculpfun", 410, 400, "5–20 W", 25000),
    ("Creality Falcon 10W", "Creality", 400, 415, "10 W", 10000),
    ("Creality Falcon2 22W / 40W", "Creality", 400, 415, "22–40 W", 25000),
    ("Two Trees TS2", "Two Trees", 450, 450, "10–20 W", 10000),
    ("Two Trees TTS-55 Pro", "Two Trees", 300, 300, "5,5 W", 6000),
    ("Comgrow Z1", "Comgrow", 400, 410, "5–10 W", 10000),
    ("Acmer S1 (2,5W / 3,5W / 6W)", "Acmer", 130, 130, "2,5–6 W", 10000),
    # 0.12.0: valori presi dalle pagine ufficiali dei produttori (fonti in SOURCES, lette il 03/11/2026).
    # Dove il produttore non dice la velocità massima metto 20000 mm/min: alla connessione vale quella della scheda.
    ("Ortur Aufero Laser 1 (AL1)", "Ortur", 180, 180, "1,6–5,5 W", 5000),
    ("Ortur Aufero Laser 2 (AL2)", "Ortur", 390, 390, "1,6–5,5 W", 10000),
    ("Sculpfun SF-A9 40W", "Sculpfun", 400, 400, "20–40 W", 36000),
    ("Sculpfun iCube Pro Max 10W", "Sculpfun", 120, 120, "10 W", 10000),
    ("Sculpfun iCube Ultra 12W", "Sculpfun", 150, 150, "12 W", 10000),
    ("Atomstack A5 Pro", "Atomstack", 410, 400, "5–5,5 W", 10000),
    ("Creality Falcon A1 10W", "Creality", 305, 381, "10 W", 36000),
    ("Creality Falcon2 Pro 22W / 40W", "Creality", 400, 415, "22–40 W", 20000),
    ("Creality Falcon2 Pro 60W", "Creality", 400, 400, "60 W", 20000),
    ("Two Trees TTS-10 Pro", "Two Trees", 300, 300, "10 W", 30000),
    ("Two Trees TTS-20 Pro", "Two Trees", 418, 418, "20 W", 30000),
    ("AlgoLaser Alpha 22W", "AlgoLaser", 400, 400, "22 W", 20000),
    ("AlgoLaser Alpha MK2 20W", "AlgoLaser", 400, 410, "20 W", 20000),
    ("AlgoLaser Alpha MK2 40W", "AlgoLaser", 400, 386, "40 W", 20000),
    ("AlgoLaser Delta 22W", "AlgoLaser", 440, 415, "22 W", 30000),
    ("Genmitsu Jinsoku LC-40", "SainSmart", 395, 365, "5–10 W", 10200),
    ("Genmitsu L8 20W", "SainSmart", 400, 400, "20 W", 40000),
    ("Genmitsu L8 40W", "SainSmart", 390, 390, "40 W", 40000),
    ("Genmitsu LE5040", "SainSmart", 500, 400, "5,5 W", 10000),
    ("Longer Ray5 5W", "Longer", 400, 400, "5,5 W", 10000),
    # scheda di controllo, non una macchina: l'area vera si legge dalla scheda ($130/$131) collegandola
    ("Scheda Makerbase MKS DLC32", "Makerbase", 400, 400, "", 10000),
    # 0.13.4: dati controllati due volte, in modo indipendente, sulle pagine ufficiali (SOURCES). Se i due lati
    # dichiarati sono diversi e il produttore non dice quale è X, si usa il più piccolo per tutti e due (AREA_NOTE):
    # la testa non va mai contro il telaio, e collegando la macchina l'area vera si legge dalla scheda.
    ("Mecpow X3 5W", "Mecpow", 400, 400, "5 W", 10000),
    ("Mecpow X3 Pro 10W", "Mecpow", 400, 400, "10 W", 10000),
    ("Mecpow X4 22W / X4 Pro 22W", "Mecpow", 400, 400, "22 W", 22000),
    ("Mecpow X4 Pro 40W", "Mecpow", 398, 398, "20–40 W", 30000),
    ("Mecpow X5 Pro 33W", "Mecpow", 600, 600, "33 W", 28000),
    # 0.17.2: richiesta da un utente; dati dalle pagine ufficiali Mecpow (SOURCES), lette il 07/11/2026
    ("Mecpow X3S 7W", "Mecpow", 360, 360, "7 W", 10000),
    ("Mecpow X3S 12W", "Mecpow", 360, 360, "12 W", 10000),
    ("Longer Ray5 Mini", "Longer", 130, 130, "2,5–3,5 W", 12000),
    ("Creality CR-Laser Falcon 5W", "Creality", 400, 400, "5 W", 10000),
    ("Atomstack A70 Max", "Atomstack", 800, 800, "35–70 W", 24000),
    # 0.17.14: richiesto da un utente. Area, velocità della porta, scala di potenza e correzione della scansione dai
    # profili ufficiali Acmer della microSD (cartella «TF Card Data» del sito acmerlaser.com, file ACMER P3 *.lbdev,
    # letti l'08/11/2026); velocità massima e spot dalla pagina ufficiale del P3 (800 mm/s = 48.000 mm/min)
    ("Acmer P3 24W", "Acmer", 400, 400, "24 W", 48000),
    ("Acmer P3 48W", "Acmer", 400, 390, "48 W", 48000),
    ("Acmer P3 2W IR", "Acmer", 400, 400, "2 W (infrarosso)", 48000),
    ("Acmer P3 2-in-1 (diodo + IR)", "Acmer", 400, 390, "diodo + 2 W IR", 48000),
    # 0.17.18: richiesto da un utente (rapporto FLC-20261109-1514-7E5C). Area 150 × 130 mm, potenza e spot dalle
    # pagine ufficiali Sculpfun (SOURCES, lette il 09/11/2026), che non dicono quale lato è X: qui 130 × 130 per
    # prudenza (AREA_NOTE). La velocità massima non è sulla pagina ufficiale: 10.000 mm/min come nelle schede dei
    # rivenditori; alla connessione vale quella della scheda.
    ("Sculpfun C1 3W", "Sculpfun", 130, 130, "3 W", 10000),
    ("Sculpfun C1 6W", "Sculpfun", 130, 130, "6 W", 10000),
)
# area dichiarata dal produttore, quando è stata ridotta per prudenza (vedi sopra)
AREA_NOTE = {
    "Mecpow X3 5W": (410, 400), "Mecpow X3 Pro 10W": (410, 400), "Mecpow X4 22W / X4 Pro 22W": (410, 400),
    "Mecpow X4 Pro 40W": (400, 398), "Longer Ray5 Mini": (130, 140), "Creality CR-Laser Falcon 5W": (400, 415),
    "Atomstack A70 Max": (850, 800), "Longer Ray5 20W": (400, 365),
    "Sculpfun C1 3W": (150, 130), "Sculpfun C1 6W": (150, 130),
}
# pagine ufficiali da cui vengono i valori dei modelli aggiunti nella 0.12.0
SOURCES = {
    "Acmer P3 24W": "https://acmerlaser.com/pages/download",
    "Acmer P3 48W": "https://acmerlaser.com/products/acmer-p3-48w-diode-enclosed-laser-engraver",
    "Acmer P3 2W IR": "https://acmerlaser.com/pages/download",
    "Acmer P3 2-in-1 (diodo + IR)": "https://acmerlaser.com/products/acmer-p3-ir-diode-laser-engraver",
    "Mecpow X3 5W": "https://mecpow.com/products/mecpow-x3-5w-laser-engraver",
    "Mecpow X3 Pro 10W": "https://mecpow.com/products/mecpow-x3-pro-10w-laser-engraver",
    "Mecpow X4 22W / X4 Pro 22W": "https://mecpow.com/products/x4-22w-powerful-laser-engraver",
    "Mecpow X4 Pro 40W": "https://mecpow.com/products/mecpow-x4-pro-40w-laser-engraving-machine",
    "Mecpow X5 Pro 33W": "https://mecpow.com/products/x5-pro-33w-laser-engraving-machine-with-air-pump",
    "Mecpow X3S 7W": "https://mecpow.com/products/mecpow-x3s-7w-laser-engraver",
    "Mecpow X3S 12W": "https://mecpow.com/products/mecpow-x3s-12w-laser-engraver",
    "Longer Ray5 Mini": "https://www.longer.net/products/longer-ray5-mini-laser-engraver",
    "Creality CR-Laser Falcon 5W": "https://www.crealityfalcon.com/products/cr-laser-falcon-5w-laser-engraver",
    "Atomstack A70 Max": "https://atomstack.com/products/atomstack-a70-max",
    "Ortur Aufero Laser 1 (AL1)": "https://ortur.net/pages/support-al1",
    "Ortur Aufero Laser 2 (AL2)": "https://ortur.net/pages/support-al2",
    "Sculpfun SF-A9 40W": "https://www.sculpfun.com/products/sculpfun-sf-a9-40w-laser-engraver-cutting-machine",
    "Sculpfun iCube Pro Max 10W": "https://sculpfun.com/products/sculpfun-icube-portable-laser-engraving-machine",
    "Sculpfun iCube Ultra 12W": "https://eu.sculpfun.com/products/icube-ultra-portable-laser-engraving-machine",
    "Sculpfun C1 3W": "https://www.sculpfun.com/products/sculpfun-c1-mini-laser-engraver-3w",
    "Sculpfun C1 6W": "https://eu.sculpfun.com/products/sculpfun-c1-6w-mini-portable-laser-engraver",
    "Atomstack A5 Pro": "https://atomstack.com/products/refurbished-atomstack-a5-m50-pro-laser-engraver",
    "Creality Falcon A1 10W": "https://www.crealityfalcon.com/products/falcon-a1-10w-enclosed-laser-engraver-and-cutter",
    "Creality Falcon2 Pro 22W / 40W": "https://crealityfalcon.com/products/falcon2-pro-60w-enclosed-laser-cutter-and-engraver",
    "Creality Falcon2 Pro 60W": "https://crealityfalcon.com/products/falcon2-pro-60w-enclosed-laser-cutter-and-engraver",
    "Two Trees TTS-10 Pro": "https://uk.twotrees3d.com/collections/tts-series/products/tts-10-pro-diode-laser-engraver-twotrees",
    "Two Trees TTS-20 Pro": "https://uk.twotrees3d.com/collections/tts-series/products/tts-20-20w-laser-engraver-machine",
    "AlgoLaser Alpha 22W": "https://algolaser.com/pages/comparison-of-alpha-and-delta-parameters",
    "AlgoLaser Alpha MK2 20W": "https://algolaser.com/products/alpha-mk2-20w-smart-enclosed-diode-laser-engraver",
    "AlgoLaser Alpha MK2 40W": "https://algolaser.com/products/alpha-mk2-20w-smart-enclosed-diode-laser-engraver",
    "AlgoLaser Delta 22W": "https://algolaser.com/products/algolaser-delta-22w-diode-laser-engraver",
    "Genmitsu Jinsoku LC-40": "https://www.sainsmart.com/products/jinsoku-lc40-laser-engraver-wireless-control-candle-support",
    "Genmitsu L8 20W": "https://www.sainsmart.com/products/l8-laser-engraver",
    "Genmitsu L8 40W": "https://www.sainsmart.com/products/l8-laser-engraver",
    "Genmitsu LE5040": "https://www.sainsmart.com/products/genmitsu-le5040-cnc-laser-engraver-machine",
    "Longer Ray5 5W": "https://longer3d.com/products/longer-ray5-laser-engraver",
    "Longer Ray5 10W": "https://www.longer3d.com/products/longer-ray5-10w-laser-engraver",
    "Longer Ray5 20W": "https://www.longer.net/products/longer-ray5-laser-engraver-5w-10w-20w",
}
# firmware che rispondono error:20 a G55 (visto nel registro di un Acmer S1, firmware 1.0.4 del 2025)
NO_G55 = {"Acmer S1 (2,5W / 3,5W / 6W)"}
# note da mostrare quando si sceglie il modello
NOTES = {
    "Genmitsu Jinsoku LC-40": tr("Il LC-40 esce dalla fabbrica con il firmware per l'app: per usarlo con FreeLaserCut "
                                 "va caricato il firmware GRBL che SainSmart mette a disposizione."),
    "AlgoLaser Delta 22W": tr("Il Delta si può collegare anche via Wi-Fi (pulsante Wi-Fi accanto alla porta): "
                              "l'indirizzo si legge nell'app AlgoLaser."),
    "Sculpfun iCube Pro Max 10W": tr("Gli iCube si collegano con il cavo USB (il Bluetooth serve solo per l'app)."),
    "Scheda Makerbase MKS DLC32": tr(
        "MKS DLC32: collega la macchina e premi «Leggi dalla macchina» per l'area di lavoro vera. Se premendo una "
        "freccia la testa va dalla parte opposta, spunta «Inverti l'asse X/Y» nel pannello Laser. Via Wi-Fi la porta "
        "è di solito 8080. Se il firmware non accetta G55, FreeLaserCut se ne accorge alla prima verifica."),
    "Sculpfun iCube Ultra 12W": tr("Gli iCube si collegano con il cavo USB (il Bluetooth serve solo per l'app)."),
}
for _n in ("Acmer P3 24W", "Acmer P3 48W", "Acmer P3 2W IR", "Acmer P3 2-in-1 (diodo + IR)"):
    NOTES[_n] = tr("Acmer P3: struttura CoreXY, si collega con il cavo USB (il Wi-Fi serve all'app). Correzione della "
                   "scansione avanti e indietro già impostata con i valori di Acmer. Il P3 da 48W e il 2-in-1 hanno "
                   "un'area di 400 × 390 mm, il 24W e il 2W IR di 400 × 400. Collegando la macchina, l'area vera si "
                   "legge dalla scheda.")
for _n in ("Mecpow X3S 7W", "Mecpow X3S 12W"):
    NOTES[_n] = tr("Con il kit di estensione dell'asse Y (venduto a parte) l'area diventa 360 × 730 mm: collegando la "
                   "macchina e premendo «Leggi dalla macchina», l'area vera si legge dalla scheda.")
# spot del laser (mm) dichiarato dal produttore, dove è diverso dal valore comune (0,08 × 0,10)
for _n, (_ax, _ay) in AREA_NOTE.items():
    _bx, _by = next((c[2], c[3]) for c in CATALOG if c[0] == _n)
    NOTES.setdefault(_n, tr("Area dichiarata dal produttore {0} × {1} mm: qui {2} × {3} per prudenza, perché non è "
                            "indicato quale lato è l'asse X. Collegando la macchina, l'area vera si legge dalla scheda.",
                            _ax, _ay, _bx, _by))
NOTES["Atomstack A70 Max"] = NOTES["Atomstack A70 Max"] + " " + tr(
    "Velocità massima dichiarata 400 mm/s (24.000 mm/min), senza dire se di incisione o di spostamento.")
SPOTS = {"Mecpow X3 5W": (0.05, 0.07), "Mecpow X3 Pro 10W": (0.06, 0.08), "Mecpow X4 22W / X4 Pro 22W": (0.08, 0.10),
         "Mecpow X4 Pro 40W": (0.10, 0.15), "Mecpow X5 Pro 33W": (0.08, 0.10), "Longer Ray5 Mini": (0.04, 0.04),
         "Mecpow X3S 7W": (0.05, 0.07), "Mecpow X3S 12W": (0.06, 0.08),
         "Creality CR-Laser Falcon 5W": (0.06, 0.06),
         "Acmer S1 (2,5W / 3,5W / 6W)": (0.06, 0.06), "Sculpfun SF-A9 40W": (0.10, 0.15),
         "Sculpfun iCube Pro Max 10W": (0.08, 0.08), "Sculpfun iCube Ultra 12W": (0.08, 0.08),
         "Atomstack A5 Pro": (0.08, 0.08), "Creality Falcon A1 10W": (0.06, 0.08),
         "Creality Falcon2 Pro 22W / 40W": (0.08, 0.12), "Creality Falcon2 Pro 60W": (0.08, 0.15),
         "Two Trees TTS-10 Pro": (0.08, 0.08), "Two Trees TTS-20 Pro": (0.13, 0.145),
         "AlgoLaser Alpha 22W": (0.16, 0.14), "AlgoLaser Alpha MK2 20W": (0.16, 0.14),
         "AlgoLaser Alpha MK2 40W": (0.175, 0.15), "AlgoLaser Delta 22W": (0.16, 0.14),
         "Genmitsu Jinsoku LC-40": (0.08, 0.05), "Genmitsu L8 20W": (0.07, 0.13), "Genmitsu L8 40W": (0.07, 0.13),
         "Longer Ray5 5W": (0.08, 0.08), "Longer Ray5 10W": (0.06, 0.06), "Longer Ray5 20W": (0.08, 0.10),
         "Acmer P3 24W": (0.06, 0.08), "Acmer P3 48W": (0.08, 0.10), "Acmer P3 2W IR": (0.02, 0.02),
         "Acmer P3 2-in-1 (diodo + IR)": (0.06, 0.04), "Sculpfun C1 3W": (0.04, 0.04), "Sculpfun C1 6W": (0.06, 0.06)}
# correzione della scansione avanti e indietro dichiarata dal produttore: [velocità mm/min, sfasamento mm]
# (Acmer P3: dai profili ufficiali; nel file è metà dello sfasamento, qui l'intero)
_P3_SCAN = [[6000.0, 0.14], [12000.0, 0.16], [18000.0, 0.12], [24000.0, 0.12], [30000.0, 0.16], [36000.0, 0.16],
            [42000.0, 0.16], [48000.0, 0.16]]
SCAN = {n: _P3_SCAN for n in ("Acmer P3 24W", "Acmer P3 48W", "Acmer P3 2W IR", "Acmer P3 2-in-1 (diodo + IR)")}
ACCEL = {n: 3000.0 for n in SCAN}  # mm/s² dai profili ufficiali Acmer
GENERIC = tr("Altro laser GRBL (si legge dalla macchina)")


def catalog_names():
    """Modelli pronti: il B1 40W per primo, poi in ordine alfabetico, il generico per ultimo."""
    rest = sorted((c[0] for c in CATALOG[1:]), key=str.lower)
    return [CATALOG[0][0]] + rest + [GENERIC]


def preset_profile(name):
    """Profilo pronto per un modello del catalogo (o generico): area, velocità e potenza indicativa."""
    if name == "Longer B1 40W":
        return MachineProfile()
    for n, vendor, bx, by, power, rate in CATALOG:
        if n == name:
            sx, sy = SPOTS.get(n, (0.08, 0.10))
            return MachineProfile(name=n, model=n, source=tr("valori di targa"), bed_x=float(bx), bed_y=float(by),
                                  optical_power=power, max_rate_x=float(rate), max_rate_y=float(rate),
                                  accel_x=ACCEL.get(n, 1500.0), accel_y=ACCEL.get(n, 1500.0), spot_x_mm=sx,
                                  spot_y_mm=sy, rx_buffer=128, no_g55=n in NO_G55,
                                  scan_offsets=[list(x) for x in SCAN.get(n, [])])
    return MachineProfile(name=tr("Laser GRBL"), model=tr("Laser GRBL"), source=tr("valori di targa"), bed_x=400.0,
                          bed_y=400.0, optical_power="", max_rate_x=10000.0, max_rate_y=10000.0, accel_x=1000.0,
                          accel_y=1000.0, spot_x_mm=0.10, spot_y_mm=0.10)


@dataclass
class PortInfo:
    device: str
    description: str = ""
    vid: int = None
    pid: int = None
    manufacturer: str = ""
    chip: str = ""
    driver: str = ""  # famiglia: wch / silabs / ftdi / native / arduino
    likely: bool = False

    def vid_pid(self):
        return f"{self.vid:04X}:{self.pid:04X}" if self.vid is not None and self.pid is not None else ""

    def label(self):
        bits = [self.device]
        if self.chip:
            bits.append(self.chip)
        elif self.description:
            bits.append(self.description)
        return " — ".join(bits)


def chip_for(vid, pid):
    if vid is None:
        return "", ""
    return USB_CHIPS.get((vid, pid)) or USB_CHIPS.get((vid, None)) or ("", "")


def describe_ports(comports=None):
    """Porte seriali con chip e driver riconosciuti; le probabili schede laser per prime."""
    if comports is None:
        try:
            from serial.tools import list_ports

            comports = list_ports.comports()
        except ImportError:
            comports = []
    out = []
    for p in comports:
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        chip, drv = chip_for(vid, pid)
        desc = getattr(p, "description", "") or ""
        blob = f"{desc} {getattr(p, 'hwid', '') or ''}".upper()
        likely = bool(chip) or any(h in blob for h in ("CH340", "CH341", "CP210", "USB-SERIAL", "USB SERIAL", "ESP32"))
        if not chip:  # Windows a volte non dà VID/PID ma li scrive nella descrizione
            m = re.search(r"VID[:_=]([0-9A-F]{4}).*PID[:_=]([0-9A-F]{4})", blob)
            if m:
                vid, pid = int(m.group(1), 16), int(m.group(2), 16)
                chip, drv = chip_for(vid, pid)
        out.append(PortInfo(p.device, desc, vid, pid, getattr(p, "manufacturer", "") or "", chip, drv, likely))
    out.sort(key=lambda t: (not t.likely, t.device))
    return out


@dataclass
class Identification:
    vendor: str = ""
    model: str = ""
    family: str = ""  # GRBL 1.1 / grblHAL / FluidNC / Grbl_ESP32 / sconosciuto
    version: str = ""
    vendor_fw: str = ""
    board: str = ""
    baud: int = 115200
    rx_buffer: int = 0
    planner_blocks: int = 0
    bed: tuple = (0.0, 0.0)
    s_max: float = 0.0
    laser_mode: bool = None
    homing: bool = None
    confidence: str = "bassa"  # alta / media / bassa
    notes: list = field(default_factory=list)  # (livello, testo)
    candidates: list = field(default_factory=list)  # modelli del catalogo con la stessa area

    def name(self):
        if self.model:
            return self.model
        bx, by = self.bed
        size = f" {bx:g}×{by:g}" if bx and by else ""
        return f"{self.vendor or 'Laser GRBL'}{size}"

    def summary(self):
        bits = []
        if self.vendor_fw:
            bits.append(self.vendor_fw)
        if self.family:
            bits.append(f"{self.family} {self.version}".strip())
        if self.board:
            bits.append(tr("scheda {0}", self.board))
        if self.bed[0] and self.bed[1]:
            bits.append(tr("area {0:g}×{1:g} mm", self.bed[0], self.bed[1]))
        if self.rx_buffer:
            bits.append(tr("buffer {0} byte", self.rx_buffer))
        return " · ".join(bits)


def _num(settings, n):
    try:
        return float(settings.get(n, settings.get(str(n))))
    except (TypeError, ValueError):
        return None


def identify(banner=(), info=(), settings=None, port=None, baud=115200):
    """Mette insieme gli indizi di porta, avvio, $I e $$."""
    settings = settings or {}
    ident = Identification(baud=baud)
    text = "\n".join(list(banner) + list(info))
    up = text.upper()
    # famiglia e versione del firmware
    if "FLUIDNC" in up:
        ident.family = "FluidNC"
    elif "GRBLHAL" in up:
        ident.family = "grblHAL"
    elif "GRBL_ESP32" in up or "GRBL ESP32" in up:
        ident.family = "Grbl_ESP32"
    m = re.search(r"Grbl\s+(\d+\.\d+\w*)", text, re.I)
    if m and not ident.family:
        ident.family = "GRBL"
    if m:
        ident.version = m.group(1)
    m = re.search(r"\[VER:([^\]:]*)", text)
    if m and not ident.version:
        ident.version = m.group(1)
    m = re.search(r"\[OPT:[^,\]]*,(\d+),(\d+)", text)
    if m:
        ident.planner_blocks, ident.rx_buffer = int(m.group(1)), int(m.group(2))
    m = re.search(r"\[MSG:FW:([^|\]]*)(?:\|MB:([^\]]*))?", text)
    if m:
        ident.vendor_fw = m.group(1).strip()
        ident.board = (m.group(2) or "").strip()
    m = re.search(r"^\[(LGT[^\]]*)\]", text, re.M)
    if m and not ident.vendor_fw:
        ident.vendor_fw = m.group(1).strip()
    for vendor, keys in VENDORS:
        if any(k in up for k in keys):
            ident.vendor = vendor
            break
    # impostazioni
    bx, by = _num(settings, 130), _num(settings, 131)
    from .grbl_codes import bad_travel

    bad = bad_travel(settings)
    if bad:  # 0.17.2: area non credibile (es. $131=234500): non la uso per il piano né per riconoscere il modello
        if any(n == 130 for n, _ in bad):
            bx = None
        if any(n == 131 for n, _ in bad):
            by = None
        ident.notes.append(("warn", tr("La scheda dice {0}: non è un'area di lavoro credibile e FreeLaserCut non la usa. "
                                    "Controlla il valore nella scheda Macchina (tabella delle impostazioni) e "
                                    "correggilo con la misura vera del piano, in mm.",
                                    ", ".join(f"${n}={v}" for n, v in bad))))
    ident.bed = (bx or 0.0, by or 0.0)
    ident.s_max = _num(settings, 30) or 0.0
    lm, hm = _num(settings, 32), _num(settings, 22)
    ident.laser_mode = None if lm is None else lm >= 1
    ident.homing = None if hm is None else hm >= 1
    # modello
    if ident.vendor == "Longer" and bx and by and abs(bx - 450) <= 15 and abs(by - 440) <= 15:
        ident.model = "Longer B1 40W"
        ident.notes.append(("info", tr("Longer B1 riconosciuto da firmware e area di lavoro. La potenza del modulo non si "
                                    "legge dalla scheda: confermala nel nome (20, 30 o 40 W).")))
    if ident.vendor and not ident.model and bx and by:
        def gap(n, cx, cy):  # distanza dall'area del catalogo o da quella dichiarata (anche con X e Y scambiati)
            ax, ay = AREA_NOTE.get(n, (cx, cy))
            return min(abs(bx - c1) + abs(by - c2) if abs(bx - c1) <= 15 and abs(by - c2) <= 15 else math.inf
                       for c1, c2 in ((cx, cy), (ax, ay), (ay, ax)))

        same = [n for n, v, cx, cy, *_ in CATALOG if v == ident.vendor and gap(n, cx, cy) < math.inf]
        if len(same) > 1:  # più modelli simili: tengo quelli con l'area più vicina
            best = min(gap(n, cx, cy) for n, v, cx, cy, *_ in CATALOG if n in same)
            same = [n for n, v, cx, cy, *_ in CATALOG if n in same and gap(n, cx, cy) <= best + 0.5]
        if len(same) == 1:
            ident.model = same[0]
        elif same:
            ident.candidates = same
            ident.notes.append(("info", tr("Area di lavoro come: {0}. Scegli il modello giusto nell'elenco.",
                                           ", ".join(same))))
    if not ident.vendor and not ident.model and bx and by:
        same = [n for n, v, cx, cy, *_ in CATALOG if abs(bx - cx) <= 2 and abs(by - cy) <= 2]
        if len(same) == 1:
            ident.model = same[0]
            ident.notes.append(("info", tr("Modello riconosciuto solo dall'area di lavoro ({0:g} × {1:g} mm): "
                                           "controlla che sia quello giusto.", bx, by)))
        elif same:
            ident.candidates = same
    # affidabilità
    score = (2 if ident.vendor else 0) + (1 if ident.family else 0) + (1 if bx and by else 0) + (1 if ident.board else 0)
    ident.confidence = "alta" if score >= 4 else "media" if score >= 2 else "bassa"
    # avvisi utili
    if not text.strip() and not settings:
        ident.notes.append(("warn", tr("La scheda non ha risposto: controlla che sia accesa, il cavo e il driver USB.")))
    if ident.family == "FluidNC":
        ident.notes.append(("info", tr("FluidNC: lo streaming GRBL funziona; alcune impostazioni stanno nel file "
                                    "config.yaml e non compaiono in $$.")))
    if ident.family == "grblHAL":
        ident.notes.append(("info", tr("grblHAL: FreeLaserCut usa il buffer dichiarato dalla scheda per uno streaming più fluido.")))
    if ident.version.startswith("0."):
        ident.notes.append(("warn", tr("GRBL 0.9 o precedente: niente potenza dinamica M4; usa la potenza costante (M3).")))
    if ident.laser_mode is False:
        ident.notes.append(("warn", tr("Modalità laser spenta ($32=0): la testa si ferma a ogni cambio di potenza. "
                                    "Conviene $32=1.")))
    if ident.s_max and ident.s_max != 1000:
        ident.notes.append(("info", tr("Scala potenza S0–S{0:g}: FreeLaserCut la usa da sola.", ident.s_max)))
    if ident.homing is False:
        ident.notes.append(("info", tr("Homing disattivato: l'origine sarà dove si trova la testa all'accensione.")))
    if port is not None and port.driver in ("wch", "silabs", "ftdi"):
        ident.notes.append(("ok", tr("Chip USB {0}: driver «{1}» funzionante.", port.chip, DRIVERS[port.driver][0])))
    return ident


def base_profile(ident):
    """Profilo di partenza per la macchina riconosciuta (poi from_machine ci scrive i valori letti)."""
    if ident.model == "Longer B1 40W":
        p = MachineProfile()
    elif ident.model in catalog_names():
        p = preset_profile(ident.model)
        p.vendor_fw = ident.vendor_fw
    else:
        p = MachineProfile(name=ident.name(), model=ident.name(), optical_power="", spot_x_mm=0.10, spot_y_mm=0.10)
        p.vendor_fw = ident.vendor_fw
    p.baud = ident.baud
    return p


def build_profile(ident, settings, info, name=None):
    p = MachineProfile.from_machine(settings, list(info), base=base_profile(ident))
    if name:
        p.name = name
        p.model = name
    p.baud = ident.baud
    return p


# ---------------------------------------------------------------------- sonda
def _read_until(ser, deadline, done=None):
    lines = []
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode(errors="replace").strip()
        line = re.sub(r"<[^<>]*>", "", line).strip()  # report di stato infilati (ESP32)
        if not line:
            continue
        lines.append(line)
        if done and done(line):
            break
    return lines


def hard_reset(ser, pulse=0.12):
    """Riavvio di una scheda ESP32 dalle linee della porta USB, come il suo pulsante di reset (0.17.3).
    È la sequenza «hard reset» dello strumento ufficiale di programmazione delle ESP32: DTR spento (pin di avvio
    libero, la scheda riparte normale e non in programmazione), RTS acceso per un attimo (reset), poi spento.
    Con alcuni chip USB (visto con il CH9102) all'apertura della porta l'ESP32 resta in programmazione e GRBL non
    parte finché non si preme il pulsante. True se le linee si sono potute muovere."""
    if not hasattr(ser, "dtr") or not hasattr(ser, "rts"):
        return False
    try:
        ser.dtr = False
        ser.rts = True
        time.sleep(pulse)
        ser.rts = False
    except Exception:  # noqa: BLE001  porta che non gestisce le linee
        return False
    return True


def probe(port, bauds=_BAUDS, opener=None, settle=1.6, log=None):
    """Apre la porta e legge avvio, $I e $$.  Ritorna dict(baud, banner, info, settings) o None.

    opener(port, baud) -> oggetto tipo serial.Serial (per il simulatore e i test)."""
    from . import netport

    if netport.is_net(port):
        bauds = bauds[:1]  # in rete la velocità non conta
    if opener is None:
        import serial

        def opener(p, b):
            if netport.is_net(p):
                return netport.NetSerial.from_port(p)
            return serial.Serial(p, b, timeout=0.1, write_timeout=1)
    end_ok = lambda l: l == "ok" or l.startswith("error")  # noqa: E731
    sensible = lambda lines: any(end_ok(l) or l.startswith("[") or "grbl" in l.lower() for l in lines)  # noqa: E731
    reset_done = netport.is_net(port)  # in rete le linee della porta non ci sono
    for baud in bauds:
        if log:
            log(f"Provo {port} a {baud} baud…")
        try:
            ser = opener(port, baud)
        except Exception as exc:  # noqa: BLE001
            if log:
                log(f"Impossibile aprire {port}: {exc}")
            return None
        try:
            banner = _read_until(ser, time.time() + settle)  # le schede si riavviano all'apertura
            ser.write(b"\r\n\r\n")
            banner += _read_until(ser, time.time() + 0.4)
            ser.write(b"$I\n")
            info = _read_until(ser, time.time() + 2.5, end_ok)
            if not sensible(banner + info) and not reset_done:
                # 0.17.3: nessuna risposta sensata: forse un ESP32 rimasto in programmazione all'apertura della
                # porta. Un riavvio dalle linee DTR/RTS (una volta sola), poi riprovo; se la velocità è sbagliata
                # la scheda almeno ora sta girando GRBL e le velocità successive la trovano
                reset_done = True
                if hard_reset(ser):
                    if log:
                        log("Nessuna risposta: riavvio la scheda dalla porta USB (come il pulsante di reset)…")
                    banner += _read_until(ser, time.time() + 3.0)
                    ser.write(b"\r\n\r\n")
                    banner += _read_until(ser, time.time() + 0.4)
                    ser.write(b"$I\n")
                    info = _read_until(ser, time.time() + 2.5, end_ok)
            if not sensible(banner + info):
                continue  # niente di sensato: velocità sbagliata
            ser.write(b"$$\n")
            raw = _read_until(ser, time.time() + 4.0, end_ok)
            settings = {}
            for l in raw:
                m = re.match(r"^\$(\d+)=(.*)$", l)
                if m:
                    settings[int(m.group(1))] = m.group(2).strip()
            return dict(baud=baud, banner=[l for l in banner if l not in ("ok",)],
                        info=[l for l in info if l.startswith("[")], settings=settings)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
    return None
