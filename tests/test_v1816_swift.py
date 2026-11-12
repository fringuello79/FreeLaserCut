# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.16: Atomstack Swift 7W e 12W nel catalogo.

Dati dalle fonti ufficiali Atomstack (lette l'11/11/2026):
- pagina prodotto atomstack.com: versioni da 7 e 12 W, area 300 × 300 mm, spot 0,08 × 0,04 mm;
- profilo ufficiale per i programmi laser (pagina «Product Support», Device_SWIFT_V1.02.lbdev): GRBL su seriale a
  460800 baud, 300 × 300, scala S 1000, niente homing all'avvio.
La velocità massima Atomstack non la dichiara: nel catalogo c'è il valore generico (10.000 mm/min), e la nota lo dice.

Casi: le due voci (area, spot, potenza, velocità seriale, fonte, nota); gli altri modelli che restano a 115200;
460800 fra le velocità provate dal riconoscimento (al quarto posto, senza togliere le altre) e fra quelle proposte a
mano; il riconoscimento che a 460800 trova la scheda e a 115200 no; una scheda Atomstack 300 × 300 che propone i due
Swift; il profilo ufficiale importato che dà gli stessi valori; traduzioni della nota.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from freelasercut import machines, profile_share
from freelasercut.grbl import optical_watts

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


S7, S12 = "Atomstack Swift 7W", "Atomstack Swift 12W"
names = machines.catalog_names()
check("Atomstack Swift 7W e 12W nel catalogo, sceglibili, senza doppioni (almeno 60 modelli più il generico)",
      S7 in names and S12 in names and len(names) == len(set(names)) and len(machines.CATALOG) >= 60
      and len(names) == len(machines.CATALOG) + 1,
      len(machines.CATALOG))
atom = [n for n in names if n.startswith("Atomstack")]
check("nell'elenco stanno con gli altri Atomstack", abs(names.index(S12) - names.index(S7)) == 1
      and names.index("Atomstack A70 Max") < names.index(S12) < names.index("Atomstack X20 Pro / S20 Pro / A20 Pro"), atom)
for n, watts in ((S7, 7.0), (S12, 12.0)):
    p = machines.preset_profile(n)
    check(f"{n}: area di lavoro 300 × 300 mm e spot 0,08 × 0,04 mm (pagina ufficiale)",
          (p.bed_x, p.bed_y, p.spot_x_mm, p.spot_y_mm) == (300.0, 300.0, 0.08, 0.04), (p.bed_x, p.bed_y, p.spot_x_mm, p.spot_y_mm))
    check(f"{n}: potenza «{watts:g} W»", p.optical_power == f"{watts:g} W" and optical_watts(p.optical_power) == watts, p.optical_power)
    check(f"{n}: porta seriale a 460800 baud (profilo ufficiale), già nel profilo pronto", p.baud == 460800, p.baud)
    check(f"{n}: velocità massima generica 10.000 mm/min, e la nota dice che Atomstack non la dichiara",
          (p.max_rate_x, p.max_rate_y) == (10000.0, 10000.0) and "non dichiara la velocità massima" in machines.NOTES.get(n, "")
          and "460800" in machines.NOTES[n] and "Leggi dalla macchina" in machines.NOTES[n], machines.NOTES.get(n))
    check(f"{n}: fonte ufficiale Atomstack dichiarata; nome, modello e valori «di targa»",
          machines.SOURCES.get(n, "").startswith("https://atomstack.com/products/") and "swift" in machines.SOURCES[n]
          and p.name == n and p.model == n and bool(p.source))
    check(f"{n}: area non ridotta, niente correzione della scansione né G55 tolto",
          n not in machines.AREA_NOTE and not p.scan_offsets and not p.no_g55)
others = [n for n in names[:-1] if n not in (S7, S12)]
check("tutti gli altri modelli restano a 115200 baud", all(machines.preset_profile(n).baud == 115200 for n in others)
      and sorted(machines.BAUD) == sorted((S7, S12)), [n for n in others if machines.preset_profile(n).baud != 115200])
a = machines.preset_profile("Atomstack A5 Pro"), machines.preset_profile("Atomstack A70 Max")
check("gli altri Atomstack restano com'erano", (a[0].bed_x, a[0].bed_y, a[0].max_rate_x) == (410.0, 400.0, 10000.0)
      and (a[1].bed_x, a[1].bed_y, a[1].max_rate_x) == (800.0, 800.0, 24000.0))

# ------------------------------------------------------------------ velocità provate
check("460800 è fra le velocità che il riconoscimento prova da solo, senza averne tolta nessuna; 115200 resta la prima",
      machines._BAUDS[0] == 115200 and 460800 in machines._BAUDS
      and set(machines._BAUDS) == {115200, 250000, 230400, 460800, 57600, 38400, 9600} and len(machines._BAUDS) == 7,
      machines._BAUDS)
from freelasercut.ui import dialogs_serial  # noqa: E402

check("…e fra quelle proposte in «Velocità della porta seriale»", 460800 in dialogs_serial.COMMON
      and dialogs_serial.COMMON[0] == 115200 and dialogs_serial.parse_baud("460800") == 460800, dialogs_serial.COMMON)


class Board:
    """Una scheda GRBL finta che capisce solo a una velocità: alle altre restituisce rumore, come una vera."""

    def __init__(self, baud, speaks=460800):
        self.ok = baud == speaks
        self.out = b""
        self.dtr = self.rts = False

    def write(self, data):
        if not self.ok:
            self.out += b"\xf8\x00\xfe"
            return len(data)
        for line in data.replace(b"\x18", b"\n\x18\n").split(b"\n"):
            line = line.strip()
            if line == b"\x18":
                self.out += b"\r\nGrbl 1.1h ['$' for help]\r\n"
            elif line == b"$I":
                self.out += b"[VER:1.1h.20250101:ATOMSTACK]\r\n[OPT:VL,35,254]\r\nok\r\n"
            elif line == b"$$":
                self.out += b"$30=1000\r\n$32=1\r\n$110=10000.000\r\n$111=10000.000\r\n$130=300.000\r\n$131=300.000\r\nok\r\n"
            elif line:
                self.out += b"ok\r\n"
        return len(data)

    def read(self, n=1):
        chunk, self.out = self.out[:max(n, 1)], self.out[max(n, 1):]
        return chunk

    def readline(self):
        i = self.out.find(b"\n")
        if i < 0:
            chunk, self.out = self.out, b""
            return chunk
        chunk, self.out = self.out[:i + 1], self.out[i + 1:]
        return chunk

    @property
    def in_waiting(self):
        return len(self.out)

    def reset_input_buffer(self):
        self.out = b""

    def flush(self):
        pass

    def close(self):
        pass


tried = []


def opener(port, baud):
    tried.append(baud)
    return Board(baud)


r = machines.probe("COM_PROVA", opener=opener, settle=0.05)
check("una scheda che parla a 460800 viene trovata dal riconoscimento (prima: «la scheda non ha risposto»)",
      r is not None and r["baud"] == 460800 and tried[0] == 115200 and tried[-1] == 460800,
      (r and r["baud"], tried))
if r:
    i = machines.identify(r["banner"], r["info"], r["settings"], None, r["baud"])
    check("…ed è riconosciuta come Atomstack 300 × 300: propone i due Swift, e la velocità resta 460800",
          i.vendor == "Atomstack" and sorted(i.candidates) == sorted((S7, S12)) and i.baud == 460800, (i.vendor, i.model, i.candidates))
    i.model = S12  # la persona sceglie il suo fra i due proposti
    p = machines.build_profile(i, r["settings"], r["info"])
    check("…scelto il modello, il profilo costruito dalla scheda tiene 460800 baud, l'area letta e lo spot del modello",
          p.baud == 460800 and (p.bed_x, p.bed_y) == (300.0, 300.0) and (p.spot_x_mm, p.spot_y_mm) == (0.08, 0.04),
          (p.baud, p.bed_x, p.spot_x_mm))
tried.clear()
r2 = machines.probe("COM_PROVA", bauds=tuple(b for b in machines._BAUDS if b != 460800), opener=opener, settle=0.05)
check("senza 460800 nell'elenco la stessa scheda non risponde (è il difetto di prima)", r2 is None and 460800 not in tried, tried)

# ------------------------------------------------------------------ il profilo ufficiale, importato
official = {"DeviceList": [{"DisplayName": "SWIFT_V1.02", "Name": "GRBL", "ProfilePath": "GRBL", "Type": "Serial", "Width": 300,
                            "Height": 300, "HomeOnStartup": False, "MirrorX": False, "MirrorY": False,
                            "ReverseIntervalCompensation": False,
                            "Settings": {"AirAssistM7": False, "AlignH": 0, "AlignV": 2, "BaudRate": 460800, "EnableZ": False,
                                         "S_Scale": 1000, "Sim_MaxAccelX": 3000, "Sim_MaxAccelY": 3000,
                                         "Sim_MaxSpeedX": 500, "Sim_MaxSpeedY": 400}}]}  # i valori del file di Atomstack
path = os.path.join(tempfile.mkdtemp(), "Device_SWIFT_V1.02.lbdev")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(official, fh)
q = profile_share.read_any(path)
ref = machines.preset_profile(S12)
check("il profilo ufficiale di Atomstack (.lbdev), importato, dà gli stessi valori del catalogo: 300 × 300, 460800 baud, "
      "scala S 1000, aria con M8 (e l'origine davanti a sinistra)",
      (q.bed_x, q.bed_y, q.baud, q.s_max, q.air_on) == (ref.bed_x, ref.bed_y, ref.baud, ref.s_max, ref.air_on)
      == (300.0, 300.0, 460800, 1000.0, "M8") and q.origin_corner == "fl", (q.bed_x, q.bed_y, q.baud, q.s_max, q.origin_corner, q.air_on))

# ------------------------------------------------------------------ traduzioni
note = machines.NOTES[S12]
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    t = loc.get(note, "")
    check(f"nota tradotta in {lang}, con 460800, 10.000 mm/min e il nome del pulsante di quella lingua",
          "460800" in t and "Atomstack Swift" in t and ("10,000" in t or "10.000" in t or "10 000" in t)
          and loc["Leggi dalla macchina"] in t, t[:120])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
