# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.5: Studia la macchina, K40 con il driver libusb-win32 (rapporto FLC-20261123-1817-5BAB).

Sul PC del tester la scheda (1a86:5512) c'era, ma con il driver «libusb-win32» (quello che si installa con Zadig per
usarla con altri programmi liberi) e non con quello del programma originale; pyusb non c'era. Così K0 la trovava e K1,
K2, K3 finivano «non collegata» senza dire perché. Ora:
- K0 dice se la scheda ha il driver libusb (`driver_libusb`);
- quando non c'è nessun modo di parlarle, il diario e la finestra dicono il motivo;
- pyusb entra nell'installatore, quindi con il driver libusb-win32 la scheda si usa (collegamento «libusb»).

Qui pyusb è finto (modulo «usb» costruito nella prova, davanti alla scheda finta di tests/studio_finte.py): si prova
che i pacchetti escono sul cavo nel formato del chip (0xA6 ogni 31 byte) e che le prove K1–K3 vanno fino in fondo.

Uso: python tests/test_v225_k40_libusb.py [classica|banco]
"""
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


for k in [k for k in sys.modules if k == "usb" or k.startswith("usb.")]:
    del sys.modules[k]  # pyusb vero, se c'è, fuori dai piedi: qui si usa quello finto

from freelasercut import studio  # noqa: E402
from freelasercut.studio import lihuiyu as L  # noqa: E402
from studio_finte import LihuiyuFinta, Orologio  # noqa: E402

clk = Orologio()
L.OROLOGIO, L.ATTESA = clk, clk.attesa


def last(d, code):
    return next(r for r in reversed(d.righe) if r.get("prova") == code)


# ====================================================================== A. quello che ha visto il tester
EVO = ("USB\\VID_1A86&PID_5512\\5&1A2B3C4D&0&2|libusb-win32 devices|Unknown Device #1|OK\n")
pnp = L._pnp_windows(lambda cmd, **k: EVO)
check("A dispositivo del rapporto: 1a86:5512, classe «libusb-win32 devices»", pnp == [
    {"vid": "1a86", "pid": "5512", "classe": "libusb-win32 devices", "nome": "Unknown Device #1", "stato": "OK"}], pnp)

real_sys, real_elenco, real_pnp = L.sys, L.WinDriver.elenco, L._pnp_windows
real_pyusb_ok = L._pyusb_ok
L._pyusb_ok = lambda: False  # 0.22.5: come sul PC del tester, anche dove pyusb c'è davvero (ora è nell'installatore)
L.sys = types.SimpleNamespace(platform="win32")
L.WinDriver.elenco = staticmethod(lambda: [])
L._pnp_windows = lambda run=None: L.__dict__["_pnp_real"](lambda cmd, **k: EVO)
L._pnp_real = real_pnp
v = L.trova()
check("A K0 come sul PC del tester: trovata, driver libusb, niente driver originale, niente pyusb",
      v["trovata"] and v["driver_libusb"] and v["driver_originale"] == [] and v["pyusb"] is False, v)
check("A motivo: «libusb_senza_pyusb»", L.perche_nessun_collegamento(v) == "libusb_senza_pyusb")
d = studio.Diario("k40", "prova001", path=os.path.join(TMP, "a.jsonl"))
L.prova_k1(d, [])
r = last(d, "K1")
check("A K1 senza collegamenti: «non collegata» con il motivo scritto nel diario",
      r["esito"] == "non collegata" and r["motivo"] == "libusb_senza_pyusb" and "pyusb" in r["motivo_testo"], r)
v2 = dict(v, driver_libusb=False)
check("A scheda vista con un driver sconosciuto: «nessun_driver»", L.perche_nessun_collegamento(v2) == "nessun_driver")
check("A scheda non vista: «non_vista»", L.perche_nessun_collegamento(dict(v, trovata=False, driver_libusb=False)) == "non_vista")
L.sys = types.SimpleNamespace(platform="linux")
check("A Linux o Mac senza pyusb: «senza_pyusb»", L.perche_nessun_collegamento(dict(v, pyusb=False)) == "senza_pyusb")
L.sys, L.WinDriver.elenco, L._pnp_windows = real_sys, real_elenco, real_pnp
L._pyusb_ok = real_pyusb_ok
check("A un driver che si chiama in un altro modo non si scambia per libusb", not any(
    "libusb" in d0["classe"].lower() for d0 in L._pnp_windows(lambda c, **k: "USB\\VID_1A86&PID_5512\\x|USB|CH341A|OK"))
      and True)


# ====================================================================== B. pyusb finto davanti alla scheda finta
class NoBackendError(Exception):
    pass


class FakeDev:
    """Un dispositivo come lo vede pyusb, con dietro la scheda finta: riceve i byte sul cavo e li scompone come il chip."""

    def __init__(self, finta):
        self.finta = finta
        self.configured = 0
        self.ctrl = []
        self.storti = []
        self.letture = 0

    def set_configuration(self):
        self.configured += 1
        self.finta.apri()

    def is_kernel_driver_active(self, i):
        return False

    def ctrl_transfer(self, rt, req, val, idx, data_or_len, timeout=None):
        self.ctrl.append((rt, req, val, idx))
        return bytes([0x30, 0x00]) if rt == 0xC0 and req == 0x5F else b""

    def write(self, ep, data, timeout=None):
        data = bytes(data)
        assert ep == 0x02
        if data == b"\xA0":
            return 1
        if len(data) == 34 and data[0] == 0xA6 and data[32] == 0xA6:
            self.finta.scrivi(data[1:32] + data[33:34])
            return 34
        self.storti.append(data)
        return len(data)

    def read(self, ep, n, timeout=None):
        assert ep == 0x82
        self.letture += 1
        return self.finta.stato()[0][:n]


STATE = {"dev": None, "backend": True}
usb = types.ModuleType("usb")
core = types.ModuleType("usb.core")
util = types.ModuleType("usb.util")
core.NoBackendError = NoBackendError


def find(idVendor=None, idProduct=None):
    if not STATE["backend"]:
        raise NoBackendError("No backend available")
    return STATE["dev"] if (idVendor, idProduct) == (0x1A86, 0x5512) else None


core.find = find
util.dispose_resources = lambda dev: None
usb.core, usb.util = core, util
sys.modules.update({"usb": usb, "usb.core": core, "usb.util": util})

check("B con pyusb presente il collegamento «libusb» è fra quelli da provare", L._pyusb_ok()
      and any(x.nome == "libusb" for x in L.collegamenti()))
finta = LihuiyuFinta(clk)
STATE["dev"] = FakeDev(finta)
d = studio.Diario("k40", "prova001", path=os.path.join(TMP, "b.jsonl"))
st = L.prova_k1(d, [L.LibUsb()])
r = last(d, "K1")
check("B K1 con libusb: collegata, stato «pronta», versione del chip letta", r["esito"] == "ok" and st == [206]
      and r["collegamento"] == "libusb" and r["versione_chip"] == "30 00", r)
dev = STATE["dev"]
check("B apertura come vuole il chip: configurazione e modo parallelo EPP (0x40, 0xB1, 0x0102)",
      dev.configured == 1 and (0x40, 0xB1, 0x0102, 0) in dev.ctrl, dev.ctrl)
L.prova_k2(d, [L.LibUsb()])
check("B K2 con libusb: casa, la scheda finta ha ricevuto «IPP» con il CRC giusto", last(d, "K2")["esito"] == "ok"
      and ("casa",) in finta.comandi and finta.crc_ko == 0, finta.comandi)
L.prova_k3(d, [L.LibUsb()], "M2")
k3 = last(d, "K3")
check("B K3 con libusb: velocità vera misurata (92 % di quella chiesta)", k3["esito"] == "ok"
      and abs(k3["velocita_vera"]["10.0"] - 9.2) < 0.1, k3.get("velocita_vera"))
check("B sul cavo solo pacchetti nel formato del chip, nessun comando pericoloso", not dev.storti and not finta.pericoli)
check("B K3: per ogni spostamento anche il tempo da quando l'ultimo pacchetto è arrivato, e il rapporto vera/chiesta",
      all(m["dopo_invio_s"] is not None and m["dopo_invio_s"] <= m["secondi"] for m in k3["misure"])
      and abs(k3["rapporto"]["10.0"] - 0.92) < 0.01 and abs(k3["rapporto"]["30.0"] - 0.92) < 0.01, k3.get("rapporto"))
STATE["backend"] = False
L.prova_k1(d, [L.LibUsb()])
r = last(d, "K1")
check("B pyusb senza la libreria libusb del sistema: «non collegata» con il motivo (libusb0.dll)",
      r["esito"] == "non collegata" and "libusb0.dll" in r["errori"][0], r)
STATE["backend"] = True
STATE["dev"] = None
L.prova_k1(d, [L.LibUsb()])
check("B scheda non attaccata: «non collegata», «scheda non trovata con libusb»",
      "scheda non trovata" in last(d, "K1")["errori"][0])

# ====================================================================== C. finestra: il motivo si legge
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from freelasercut.ui.dialogs_studio import StudioDialog  # noqa: E402

dlg = StudioDialog(None, None)
dlg.k40_links = lambda: []
L.trova = lambda run=None: {"sistema": "win32", "pyusb": False, "driver_originale": [], "trovata": True,
                            "driver_libusb": True, "dispositivi": pnp}
real_sys = L.sys
L.sys = types.SimpleNamespace(platform="win32")
dlg.run("K1", sync=True)
log = dlg.log.toPlainText()
check("C K1 senza collegamenti: nella finestra il motivo, in parole («driver libusb-win32», «pyusb», nessun comando)",
      "✗" in dlg.rows["K1"][0].text() and "libusb-win32" in log and "pyusb" in log and "Nessun comando" in log, log)
L.sys = real_sys
finta2 = LihuiyuFinta(clk)
STATE["dev"] = FakeDev(finta2)
dlg.k40_links = lambda: [L.LibUsb()]
dlg.run("K2", sync=True)
check("C con pyusb e il driver libusb la prova va: K2 fatta", "✓" in dlg.rows["K2"][0].text(), dlg.log.toPlainText()[-200:])

# ====================================================================== D. installatore e testi
sys.path.insert(0, os.path.join(ROOT, "build"))
import prepara_installer as pi  # noqa: E402

check("D pyusb nell'installatore per Windows (e da lì in quelli per Mac e Linux), versione fissata",
      "pyusb==1.3.1" in pi.PACKAGES)
req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
check("D pyusb fra le librerie di chi lo avvia dal sorgente", "pyusb>=" in req)
lic = open(os.path.join(ROOT, "LICENZE-TERZE-PARTI.md"), encoding="utf-8").read()
lic_file = os.path.join(ROOT, "licenze-terze-parti", "pyusb-BSD-3-Clause.txt")
check("D licenza di pyusb fra quelle delle librerie incluse (elenco e file)", "pyusb-BSD-3-Clause.txt" in lic
      and os.path.exists(lic_file) and "Redistribution" in open(lic_file, encoding="utf-8").read())
MOT = ("La scheda c'è e ha il driver libusb-win32 (quello che si installa con Zadig), ma per parlarle FreeLaserCut ha "
       "bisogno della libreria pyusb, che su questo computer manca. Nessun comando è partito.",
       "La scheda c'è, ma non ha un driver con cui FreeLaserCut sappia parlarle. Nessun comando è partito.",
       "Su questo sistema per parlare con la scheda serve la libreria pyusb, che manca. Nessun comando è partito.",
       "La scheda non si vede: è accesa e collegata con il cavo USB?")
missing = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    m = [t for t in MOT if not cat.get(t)]
    if m:
        missing[lang] = m
check("D testi nuovi tradotti in inglese, spagnolo, francese e portoghese", not missing, missing)

# ====================================================================== E. difetti rimessi apposta
caught = []
orig = L.sul_cavo
L.sul_cavo = lambda p32: b"\xA6" + p32  # 1. pacchetto senza il secondo 0xA6
fe = LihuiyuFinta(clk)
STATE["dev"] = FakeDev(fe)
L.prova_k2(studio.Diario("k40", "g", path=os.path.join(TMP, "g1.jsonl")), [L.LibUsb()])
caught.append(bool(STATE["dev"].storti) and ("casa",) not in fe.comandi)
L.sul_cavo = orig
orig_ok = L._pyusb_ok
L._pyusb_ok = lambda: False  # 2. pyusb non visto anche se c'è
caught.append(not any(x.nome == "libusb" for x in L.collegamenti()))
L._pyusb_ok = orig_ok
orig_p = L.perche_nessun_collegamento
L.perche_nessun_collegamento = lambda visto=None: ""  # 3. motivo perso
dg = studio.Diario("k40", "g", path=os.path.join(TMP, "g2.jsonl"))
L.prova_k1(dg, [])
caught.append(not last(dg, "K1").get("motivo"))
L.perche_nessun_collegamento = orig_p
check("E tre difetti rimessi apposta (formato del cavo, pyusb ignorato, motivo perso): tutti visti", all(caught), caught)

for k in ("usb", "usb.core", "usb.util"):
    sys.modules.pop(k, None)
print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
