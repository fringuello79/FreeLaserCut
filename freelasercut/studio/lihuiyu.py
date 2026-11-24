# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Studia la macchina: K40 con la scheda M2 Nano (e sorelle), il linguaggio a lettere della scheda e il collegamento
USB, riscritti da capo.

Collegamento: un chip USB CH341 in modo «parallelo EPP», identificativo 1a86:5512. Sul cavo il chip riceve comandi
suoi: 0xA6 + fino a 31 byte = «scrivi questi dati», 0xA0 = «dimmi lo stato» (6 byte; il secondo è lo stato della
scheda). La scheda riceve pacchetti di 32 byte: 0x00, 30 byte di comandi (riempiti con «F»), un byte di controllo
(CRC a 8 bit del tipo 1-Wire). Stati: 206 pronta, 238 occupata, 207 errore di controllo, 236 lavoro finito,
239 alimentazione, 204 finito (M3) o numero di serie confermato.

Linguaggio: lettere maiuscole per le direzioni (B destra, T sinistra, L su, R giù, M diagonale), distanze in millesimi
di pollice scritte con lettere minuscole e cifre, codici di velocità che cominciano con «CV» o «V».
Lo studio manda solo: IPP (vai a casa), I (interrompi), lo spostamento veloce «I … S1P» e lo spostamento a velocità
nota «I CV… NBRS1E … FNSE» (anche con più corse dentro, 0.22.5). Il comando che accende il laser («D») non esiste in questo file, e controlla() rifiuta
qualsiasi lettera che non sia nell'elenco.

Su Windows la scheda si usa dal driver che installa il programma originale della macchina (niente da installare);
altrove serve pyusb con libusb, se c'è.
"""
import math
import os
import re
import sys
import time

from . import SicurezzaError, esadecimale

VID, PID = 0x1A86, 0x5512
OK, OCCUPATA, ERRORE_CRC, FINITO, ALIMENTAZIONE, FINITO_M3 = 206, 238, 207, 236, 239, 204
NOMI_STATO = {OK: "pronta", OCCUPATA: "occupata", ERRORE_CRC: "errore di controllo", FINITO: "lavoro finito",
              ALIMENTAZIONE: "alimentazione", FINITO_M3: "finito (M3) o seriale confermato"}
SCHEDE = ("A", "B", "B1", "B2", "M", "M1", "M2", "M3")
MIL_PER_MM = 1000.0 / 25.4
OROLOGIO, ATTESA = time.monotonic, time.sleep  # sostituibili nelle prove automatiche (tempo finto)

# ---------------------------------------------------------------- lettere permesse (tutto il resto è rifiutato)
_PERMESSE = set(b"IPSNBTLRFECVG-0123456789") | set(b"abcdefghijklmnopqrstuvwxyz|")


def controlla(comandi):
    """Solo le lettere dello studio, e mai l'accensione del laser. Se no SicurezzaError, e non parte niente."""
    data = bytes(comandi)
    for i, b in enumerate(data):
        if b not in _PERMESSE:
            raise SicurezzaError(f"carattere non permesso {bytes([b])!r} al posto {i}")
    return data


# ---------------------------------------------------------------- pacchetti
def crc8(dati):
    c = 0
    for byte in dati:
        for _ in range(8):
            misto = (c ^ byte) & 1
            c >>= 1
            if misto:
                c ^= 0x8C
            byte >>= 1
    return c


def pacchetto32(comandi):
    """Fino a 30 byte di comandi -> i 32 byte che riceve la scheda (0x00, comandi riempiti con F, CRC)."""
    corpo = controlla(comandi)
    if len(corpo) > 30:
        raise ValueError("al massimo 30 byte per pacchetto")
    corpo = corpo + b"F" * (30 - len(corpo))
    return b"\x00" + corpo + bytes([crc8(corpo)])


def sul_cavo(p32):
    """I 32 byte per la scheda -> i 34 byte da scrivere sull'USB (il chip vuole 0xA6 ogni 31 byte di dati)."""
    return b"\xA6" + p32[:31] + b"\xA6" + p32[31:]


def pacchetti(flusso):
    """Un flusso di comandi -> pacchetti da 30 byte: i comandi continuano da un pacchetto all'altro, solo l'ultimo
    si riempie di F."""
    data = controlla(flusso)
    return [pacchetto32(data[i:i + 30]) for i in range(0, max(len(data), 1), 30)]


def distanza(mil):
    """Distanza in millesimi di pollice -> lettere della scheda."""
    mil = int(mil)
    if mil < 0:
        raise ValueError("distanza negativa")
    out = "z" * (mil // 255)
    r = mil % 255
    if r == 0:
        return out
    if r < 26:
        return out + chr(96 + r)
    if r < 52:
        return out + "|" + chr(96 + r - 25)
    return out + "%03d" % r


# ---------------------------------------------------------------- codici di velocità
DIAG = 0.261199033289
_FAM_AB = ((64752.0, 64752.0, 64640.0, 64512.0), -2000.0)
_FAM_M = ((60416.0, 60416.0, 59904.0, 59392.0), -12120.0)
CON_DIAGONALE = ("B1", "B2", "M1", "M2", "M3")


def _famiglia(scheda):
    basi, pend = _FAM_M if scheda.startswith("M") else _FAM_AB
    if scheda == "B2":
        pend = -24240.0
    return basi, pend


def marcia(v, raster=False):
    if v <= 25.4:
        return 1
    if v <= 60:
        return 2
    if not raster:
        return 3 if v < 127 else 4
    if v < 127:
        return 2
    return 3 if v <= 320 else 4


def retta(scheda, v, raster=False):
    """-> (base, pendenza, marcia scritta, lenta?)."""
    basi, pend = _famiglia(scheda)
    g = marcia(v, raster)
    if scheda == "B2" and v < 7:
        return basi[0], pend / 12, 1, not raster
    if scheda in ("M", "M1") and v < 7 and not raster:
        return basi[0], pend, 1, False
    if scheda in ("M2", "M3") and v < 7:
        return 65528.0, pend / 12, 1, True
    return basi[g - 1], pend, g, False


def _sedici(valore):
    valore = int(valore)
    return "%03d%03d" % ((valore >> 8) & 0xFFFFFF, valore & 0xFF)


def codice_velocita(scheda, v, passo_raster=0):
    """Codice di velocità per la scheda (v in mm/s; passo del raster in millesimi di pollice, 0 = taglio)."""
    if scheda not in SCHEDE:
        raise ValueError(f"scheda sconosciuta: {scheda}")
    if not 0.5 <= v <= 240:
        raise ValueError("velocità fuori misura")
    raster = passo_raster != 0
    base, pend, g, lenta = retta(scheda, v, raster)
    t = 25.4 / v
    val = base + pend * t
    val = math.ceil(val) if val - round(val) > 0.005 else round(val)
    s = _sedici(val)
    if raster:
        return "V%s%dG%03d" % (s, g, abs(passo_raster))
    if scheda not in CON_DIAGONALE:
        return "CV%s1C" % s if lenta else "CV%s%d" % (s, g)
    passo = min(int(math.floor(v) + 1), 128)
    d = _sedici(DIAG * -pend * t / passo)
    return "CV%s1%03d%sC" % (s, passo, d) if lenta else "CV%s%d%03d%s" % (s, g, passo, d)


# ---------------------------------------------------------------- i soli comandi dello studio
def cmd_casa():
    return b"IPP"


def cmd_ferma():
    return b"I"


def cmd_passo_veloce(dx_mm, dy_mm=0.0):
    """Spostamento con la velocità della scheda (laser spento). dx > 0 verso destra, dy > 0 verso il basso."""
    out = b"I"
    dx, dy = round(dx_mm * MIL_PER_MM), round(dy_mm * MIL_PER_MM)
    if dy:
        out += (b"R" if dy > 0 else b"L") + distanza(abs(dy)).encode()
    if dx:
        out += (b"B" if dx > 0 else b"T") + distanza(abs(dx)).encode()
    return controlla(out + b"S1P")


def cmd_a_velocita(scheda, v, dx_mm):
    """Spostamento orizzontale a velocità nota, a laser spento (il laser si accenderebbe solo con un comando che qui
    non c'è)."""
    dx = round(dx_mm * MIL_PER_MM)
    if not dx:
        raise ValueError("spostamento nullo")
    out = (b"I" + codice_velocita(scheda, v).encode() + b"NBRS1E" + (b"B" if dx > 0 else b"T")
           + distanza(abs(dx)).encode() + b"FNSE")
    return controlla(out)


def cmd_lavoro_unico(scheda, v, corse_mm):
    """0.22.5: più spostamenti orizzontali dentro un solo lavoro (una sola entrata nel modo compatto e una sola uscita),
    a laser spento. corse_mm: per esempio (50, -50, 100, -100); > 0 verso destra."""
    corse = [round(c * MIL_PER_MM) for c in corse_mm]
    if not corse or any(c == 0 for c in corse):
        raise ValueError("spostamento nullo")
    out = b"I" + codice_velocita(scheda, v).encode() + b"NBRS1E"
    for c in corse:
        out += (b"B" if c > 0 else b"T") + distanza(abs(c)).encode()
    return controlla(out + b"FNSE")  # 0.22.6: senza «-» (non è per la scheda)


def nome_stato(s):
    return NOMI_STATO.get(s, f"sconosciuto ({s})")


# ---------------------------------------------------------------- dove la scheda è collegata (sola lettura)
def trova(run=None):
    """Cerca la scheda senza aprirla. -> dict con quello che si vede (niente numeri di serie, niente percorsi)."""
    out = {"sistema": sys.platform, "pyusb": _pyusb_ok()}
    try:
        if sys.platform.startswith("win"):
            out["driver_originale"] = [{"descrizione": d} for _p, d in WinDriver.elenco()]
            out["dispositivi"] = _pnp_windows(run)
        elif sys.platform.startswith("linux"):
            out["dispositivi"] = _usb_linux()
        elif sys.platform == "darwin":
            out["dispositivi"] = _usb_mac(run)
    except Exception as ex:  # noqa: BLE001
        out["errore"] = f"{type(ex).__name__}: {ex}"
    devs = out.get("dispositivi") or []
    out["trovata"] = bool(out.get("driver_originale")) or any(d.get("pid") == "5512" for d in devs)
    # 0.22.5: su Windows la scheda può avere il driver «libusb-win32» (quello che si installa con Zadig per usarla con
    # altri programmi liberi) invece di quello del programma originale: si parla con lei con pyusb (rapporto del 23/11)
    out["driver_libusb"] = any(d.get("pid") == "5512" and "libusb" in str(d.get("classe", "")).lower() for d in devs)
    return out


def vista_veloce():
    """0.22.6: la scheda c'è? Risposta in pochi millesimi, per l'elenco delle porte (trova() su Windows chiede a
    PowerShell e ci mette secondi). Vede la scheda solo se c'è anche un modo di parlarle: il driver del programma
    originale, oppure pyusb con libusb."""
    try:
        if sys.platform.startswith("win") and WinDriver.elenco():
            return True
        if sys.platform.startswith("linux") and not any(d.get("pid") == "5512" for d in _usb_linux()):
            return False
        if _pyusb_ok():
            import usb.core

            return usb.core.find(idVendor=VID, idProduct=PID) is not None
    except Exception:  # noqa: BLE001 — manca libusb, permessi…: per l'elenco vuol dire «non c'è»
        pass
    return False


MOTIVI = {
    "libusb_senza_pyusb": "scheda vista con il driver libusb-win32, ma su questo computer manca la libreria pyusb",
    "nessun_driver": "scheda vista ma senza un driver con cui parlarle (né quello del programma originale né libusb)",
    "senza_pyusb": "su questo sistema per parlare con la scheda serve la libreria pyusb, che manca",
    "non_vista": "scheda non vista: è accesa e collegata con il cavo USB?",
}


def perche_nessun_collegamento(visto=None):
    """Quando non c'è nessun modo di parlare con la scheda: il motivo (codice di MOTIVI). `visto` è il risultato di
    trova(), se c'è già."""
    v = visto if visto is not None else trova()
    pid_ok = v.get("trovata")
    if sys.platform.startswith("win"):
        if v.get("driver_libusb") and not v.get("pyusb"):
            return "libusb_senza_pyusb"
        return "nessun_driver" if pid_ok else "non_vista"
    if not v.get("pyusb"):
        return "senza_pyusb"
    return "non_vista" if not pid_ok else "nessun_driver"


def _pyusb_ok():
    try:
        import usb.core  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _run(cmd, timeout=20):
    import subprocess

    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}  # nessuna finestra nera
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    return r.stdout


def _pnp_windows(run=None):
    """Dispositivi del costruttore del chip (1a86) presenti: classe, nome, stato. Dell'identificativo si tiene solo
    VID e PID (il resto può contenere un numero di serie o la posizione della porta)."""
    ps = ("Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\\VID_1A86*' } | "
          "ForEach-Object { $_.InstanceId + '|' + $_.Class + '|' + $_.FriendlyName + '|' + $_.Status }")
    text = (run or _run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    out = []
    for line in (text or "").splitlines():
        parts = line.strip().split("|")
        m = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", parts[0].upper()) if parts else None
        if m:
            out.append({"vid": m.group(1).lower(), "pid": m.group(2).lower(), "classe": (parts + [""] * 4)[1],
                        "nome": (parts + [""] * 4)[2][:60], "stato": (parts + [""] * 4)[3]})
    return out


def _usb_linux(root="/sys/bus/usb/devices"):
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for n in names:
        p = os.path.join(root, n)
        try:
            vid = open(os.path.join(p, "idVendor")).read().strip()
            pid = open(os.path.join(p, "idProduct")).read().strip()
        except OSError:
            continue
        if vid != "1a86":
            continue
        drv = ""
        for sub in sorted(os.listdir(p)):
            dp = os.path.join(p, sub, "driver")
            if os.path.islink(dp):
                drv = os.path.basename(os.readlink(dp))
                break
        out.append({"vid": vid, "pid": pid, "driver": drv})
    return out


def _usb_mac(run=None):
    text = (run or _run)(["ioreg", "-p", "IOUSB", "-l", "-w0"])
    out, vid = [], None
    for line in (text or "").splitlines():
        m = re.search(r'"idVendor" = (\d+)', line)
        if m:
            vid = int(m.group(1))
        m = re.search(r'"idProduct" = (\d+)', line)
        if m and vid == VID:
            out.append({"vid": "1a86", "pid": "%04x" % int(m.group(1))})
            vid = None
    return out


# ---------------------------------------------------------------- collegamento: driver originale (Windows)
IOCTL = 0x223CD0
GUID_DRIVER = "{77989adf-06db-4025-92e8-40d902c03b0a}"
_PROP = "{a45c254e-df1c-4efd-8020-67d146a850e0}"  # proprietà dei dispositivi: 2 = descrizione, 16 = nome interno


class WinDriver:
    """Il driver che installa il programma originale della K40: si parla con DeviceIoControl, nessuna DLL in più.
    Ogni chiamata ha buffer della misura giusta; le risposte si tengono grezze nel diario."""

    nome = "driver originale (Windows)"

    def __init__(self, path, ioctl=None):
        self.path = path
        self._h = None
        self._ioctl = ioctl  # per le prove: funzione (ingresso bytes, misura uscita) -> bytes

    # -- elenco senza aprire
    @staticmethod
    def elenco():
        if not sys.platform.startswith("win"):
            return []
        import ctypes
        from ctypes import wintypes as W

        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

        class DEVINFO(ctypes.Structure):
            _fields_ = [("cbSize", W.DWORD), ("ClassGuid", GUID), ("DevInst", W.DWORD), ("Reserved", ctypes.c_void_p)]

        class PROPKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        def guid(s):
            g = GUID()
            ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
            return g

        sa = ctypes.windll.setupapi
        sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), ctypes.c_wchar_p, ctypes.c_void_p, W.DWORD]
        sa.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, W.DWORD, ctypes.POINTER(DEVINFO)]
        sa.SetupDiGetDevicePropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DEVINFO), ctypes.POINTER(PROPKEY),
                                                 ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, W.DWORD,
                                                 ctypes.POINTER(W.DWORD), W.DWORD]
        sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
        g = guid(GUID_DRIVER)
        h = sa.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 2)  # 2 = solo i presenti
        if not h or h == ctypes.c_void_p(-1).value:
            return []
        out = []
        try:
            i = 0
            while True:
                info = DEVINFO()
                info.cbSize = ctypes.sizeof(DEVINFO)
                if not sa.SetupDiEnumDeviceInfo(h, i, ctypes.byref(info)):
                    break
                i += 1

                def prop(pid):
                    key = PROPKEY(guid(_PROP), pid)
                    typ, need = ctypes.c_ulong(), W.DWORD(0)
                    sa.SetupDiGetDevicePropertyW(h, ctypes.byref(info), ctypes.byref(key), ctypes.byref(typ), None, 0,
                                                 ctypes.byref(need), 0)
                    if not need.value:
                        return None
                    buf = ctypes.create_string_buffer(need.value)
                    if not sa.SetupDiGetDevicePropertyW(h, ctypes.byref(info), ctypes.byref(key), ctypes.byref(typ),
                                                        buf, need, ctypes.byref(need), 0):
                        return None
                    return bytes(buf.raw).decode("utf-16-le", "replace").split("\0", 1)[0]

                pdo, desc = prop(16), prop(2)
                if pdo:
                    out.append((r"\\?\GLOBALROOT" + pdo, (desc or "")[:60]))
        finally:
            sa.SetupDiDestroyDeviceInfoList(h)
        return out

    # -- apertura e chiamate
    def apri(self):
        if self._ioctl is not None:
            return self
        import ctypes
        from ctypes import wintypes as W

        k = ctypes.windll.kernel32
        k.CreateFileW.restype = W.HANDLE
        k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
        k.DeviceIoControl.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD,
                                      ctypes.POINTER(W.DWORD), ctypes.c_void_p]
        k.CloseHandle.argtypes = [W.HANDLE]
        h = k.CreateFileW(self.path, 0xC0000000, 3, None, 3, 0x80, None)  # lettura e scrittura, condiviso, esistente
        if h in (None, W.HANDLE(-1).value, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.GetLastError(), "la scheda non si apre (il programma originale è ancora aperto?)")
        self._h = h
        self._k = k
        return self

    def chiudi(self):
        if self._h is not None:
            try:
                self._k.CloseHandle(self._h)
            finally:
                self._h = None

    def chiama(self, ingresso, misura_uscita):
        """DeviceIoControl con un buffer d'uscita da `misura_uscita` byte (40 al massimo). -> bytes restituiti."""
        if self._ioctl is not None:
            return bytes(self._ioctl(bytes(ingresso), misura_uscita))
        import ctypes
        from ctypes import wintypes as W

        buf_in = ctypes.create_string_buffer(bytes(ingresso), len(ingresso))
        buf_out = ctypes.create_string_buffer(40)
        n = W.DWORD(0)
        ok = self._k.DeviceIoControl(self._h, IOCTL, buf_in, len(ingresso), buf_out, min(misura_uscita, 40),
                                     ctypes.byref(n), None)
        if not ok:
            raise OSError(ctypes.GetLastError(), "chiamata al driver non riuscita")
        return bytes(buf_out.raw[:max(0, min(n.value, 40))])

    @staticmethod
    def _controllo(tipo, richiesta, valore, indice, lunghezza):
        """Trasferimento di controllo USB, nel formato del driver (40 byte)."""
        import struct

        return struct.pack("<iiBBHHB", 4, 0, tipo, richiesta, valore, indice, lunghezza).ljust(40, b"\0")

    @staticmethod
    def _scrittura(comando, dati):
        import struct

        return struct.pack("<ii", comando, len(dati)) + bytes(dati).ljust(260, b"\0")

    def inizia(self):
        """Modo parallelo EPP 1.9 (0x40, 0xB1, 0x0102)."""
        return self.chiama(self._controllo(0x40, 0xB1, 0x0102, 0, 0), 40)

    def versione(self):
        raw = self.chiama(self._controllo(0xC0, 0x5F, 0, 0, 2), 40)
        return raw

    def scrivi(self, p32):
        return self.chiama(self._scrittura(0x12, p32), 8)  # 0x12: scrittura dati EPP (il driver aggiunge gli 0xA6)

    def stato(self):
        """-> (6 byte di stato o b'', grezzo per il diario)."""
        import struct

        self.chiama(self._scrittura(0x07, b"\xA0"), 8)
        raw = self.chiama(struct.pack("<ii", 0x06, 8), 40)
        data = raw[8:] if len(raw) > 8 else raw
        if len(data) < 2:  # alcune versioni del driver rispondono solo al trasferimento di controllo
            raw2 = self.chiama(self._controllo(0xC0, 0x52, 0, 0, 8), 40)
            data = raw2[8:] if len(raw2) > 8 else raw2
            return data[:6], {"lettura": esadecimale(raw), "controllo": esadecimale(raw2)}
        return data[:6], {"lettura": esadecimale(raw)}


# ---------------------------------------------------------------- collegamento: libusb (se c'è pyusb)
class LibUsb:
    nome = "libusb"

    def __init__(self, dev=None):
        self.dev = dev

    def apri(self):
        import usb.core

        if self.dev is None:
            try:
                self.dev = usb.core.find(idVendor=VID, idProduct=PID)
            except usb.core.NoBackendError:
                raise OSError("pyusb c'è, ma manca la libreria libusb del sistema (su Windows libusb0.dll, che "
                              "installa il driver libusb-win32)") from None
        if self.dev is None:
            raise OSError("scheda non trovata con libusb")
        if sys.platform.startswith("linux"):
            try:
                if self.dev.is_kernel_driver_active(0):
                    self.dev.detach_kernel_driver(0)
            except Exception:  # noqa: BLE001
                pass
        self.dev.set_configuration()
        return self

    def chiudi(self):
        try:
            import usb.util

            usb.util.dispose_resources(self.dev)
        except Exception:  # noqa: BLE001
            pass

    def inizia(self):
        self.dev.ctrl_transfer(0x40, 0xB1, 0x0102, 0, 0, 2000)
        return b""

    def versione(self):
        return bytes(self.dev.ctrl_transfer(0xC0, 0x5F, 0, 0, 2, 2000))

    def scrivi(self, p32):
        self.dev.write(0x02, sul_cavo(p32), 2000)
        return b""

    def stato(self):
        self.dev.write(0x02, b"\xA0", 2000)
        raw = bytes(self.dev.read(0x82, 6, 2000))
        return raw[:6], {"lettura": esadecimale(raw)}


def collegamenti():
    """I modi di parlare con la scheda disponibili su questo computer, nell'ordine in cui si provano."""
    out = []
    if sys.platform.startswith("win"):
        out += [WinDriver(p) for p, _d in WinDriver.elenco()]
    if _pyusb_ok():
        out.append(LibUsb())
    return out


# ---------------------------------------------------------------- la scheda, vista dallo studio
class Scheda:
    """Tutto quello che parte verso la scheda passa da qui: controlla(), poi pacchetto con CRC, poi il collegamento.
    `traccia` riceve ogni pacchetto mandato (per il diario e per le prove automatiche)."""

    def __init__(self, link, traccia=None, attesa=None, orologio=None):
        self.link = link
        self.traccia = traccia
        self.attesa = attesa or ATTESA
        self.orologio = orologio or OROLOGIO
        self.mandati = []
        self.errori_crc = 0

    def apri(self):
        self.link.apri()
        self.inizio = self.link.inizia()
        return self

    def chiudi(self):
        self.link.chiudi()

    def stato(self):
        data, _raw = self.link.stato()
        return data[1] if len(data) > 1 else None, data

    def manda(self, flusso, tentativi=8):
        """Manda il flusso a pacchetti, aspettando che la scheda sia libera; rimanda un pacchetto con errore di CRC."""
        for p in pacchetti(flusso):
            for _ in range(tentativi):
                s, _d = self.stato()
                t0 = self.orologio()
                while s == OCCUPATA and self.orologio() - t0 < 10:
                    self.attesa(0.02)
                    s, _d = self.stato()
                self.link.scrivi(p)
                self.mandati.append(p)
                if self.traccia:
                    self.traccia(p)
                s, _d = self.stato()
                if s == ERRORE_CRC:
                    self.errori_crc += 1
                    continue
                break
            else:
                raise IOError("la scheda rifiuta i pacchetti (errore di controllo ripetuto)")

    def aspetta_fine(self, massimo, ferma=None):
        """Aspetta lo stato «lavoro finito». -> (secondi, sequenza degli stati visti con il tempo)."""
        t0 = self.orologio()
        visti, ultimo = [], None
        while self.orologio() - t0 < massimo:
            if ferma is not None and ferma():
                raise InterruptedError
            s, _d = self.stato()
            if s != ultimo:
                visti.append((round(self.orologio() - t0, 3), s))
                ultimo = s
            if s in (FINITO, FINITO_M3):
                return self.orologio() - t0, visti
            self.attesa(0.02)
        return None, visti

    def aspetta_casa(self, massimo, ferma=None, stabile=1.0):
        """0.22.5: fine del ritorno a casa. La M2 Nano vera dopo «IPP» non manda «lavoro finito»: torna solo «pronta»
        (rapporti FLC-20261123-1937-1187 e -2036-E7DF), e aspettare «finito» faceva perdere 25 s. Fine = «finito», oppure
        «pronta» ferma per `stabile` secondi dopo «occupata» (o dopo 2 s, se «occupata» non si è vista).
        -> (secondi al primo «pronta» rimasto fermo, sequenza degli stati, come è finita)"""
        t0 = self.orologio()
        visti, ultimo, t_pronta, occupata = [], None, None, False
        while self.orologio() - t0 < massimo:
            if ferma is not None and ferma():
                raise InterruptedError
            s, _d = self.stato()
            ora = self.orologio() - t0
            if s != ultimo:
                visti.append((round(ora, 3), s))
                ultimo = s
                t_pronta = ora if s == OK else None
            if s == OCCUPATA:
                occupata = True
            if s in (FINITO, FINITO_M3):
                return ora, visti, "finito"
            if s == OK and t_pronta is not None and ora - t_pronta >= stabile and (occupata or ora >= 2.0):
                return t_pronta, visti, "pronta" if occupata else "pronta senza occupata"
            self.attesa(0.02)
        return None, visti, "tempo scaduto"


# ---------------------------------------------------------------- le prove
PROVE = ("K0", "K1", "K2", "K3", "K4")
MUOVE = {"K2", "K3", "K4"}  # queste chiedono il consenso
VELOCITA_PROVA = (10.0, 30.0)
DISTANZE_PROVA = (50.0, 100.0)


def prova_k0(diario, run=None):
    dati = trova(run)
    diario.risultato("K0", "ok" if dati.get("trovata") else "non trovata", **dati)
    return dati


def _apri(links, diario, prova, visto=None):
    errori = []
    for link in links:
        sch = Scheda(link)
        try:
            sch.apri()
            ver = link.versione()
            return sch, {"collegamento": link.nome, "versione_chip": esadecimale(ver), "errori_prima": errori}
        except Exception as ex:  # noqa: BLE001
            errori.append(f"{link.nome}: {type(ex).__name__}: {ex}")
            try:
                link.chiudi()
            except Exception:  # noqa: BLE001
                pass
    extra = {}
    if not links:
        try:
            m = perche_nessun_collegamento(visto)
        except Exception as ex:  # noqa: BLE001
            m, extra["errore_ricerca"] = "", f"{type(ex).__name__}: {ex}"
        extra["motivo"] = m
        extra["motivo_testo"] = MOTIVI.get(m, "")
    diario.risultato(prova, "non collegata", errori=errori, collegamenti=[link.nome for link in links], **extra)
    return None, {"errori": errori}


def prova_k1(diario, links, secondi=2.0):
    """Stato della scheda per qualche secondo, a scheda ferma (sola lettura)."""
    sch, info = _apri(links, diario, "K1")
    if sch is None:
        return None
    try:
        letture = []
        t_end = sch.orologio() + secondi
        while sch.orologio() < t_end and len(letture) < 40:
            data, raw = sch.link.stato()
            letture.append({"byte": list(data), "stato": data[1] if len(data) > 1 else None, **raw})
            sch.attesa(0.1)
        stati = sorted({r["stato"] for r in letture if r["stato"] is not None})
        esito = "ok" if any(s in NOMI_STATO for s in stati) else "risposte strane"
        diario.risultato("K1", esito, **info, stati=stati, nomi=[nome_stato(s) for s in stati], letture=letture[:12])
        return stati
    except OSError as ex:
        diario.risultato("K1", "errore di collegamento", **info, errore=f"{type(ex).__name__}: {ex}")
        return None
    finally:
        sch.chiudi()


CASA_SICURA_S = 8.0  # K3, K4: attesa minima dopo «vai a casa» quando non si sa se «pronta» vuol dire «arrivata»


def _a_casa(sch, ferma=None, fidati=False):
    """Casa prima di una misura (K3, K4). La M2 vera a testa ferma a casa dice «pronta» dopo mezzo secondo; non
    sappiamo ancora se, partendo da lontano, lo dice solo all'arrivo (è quello che misura K2). Finché non si sa, se
    «pronta» arriva presto si aspettano comunque CASA_SICURA_S secondi dall'invio: una corsa partita mentre la testa
    sta ancora tornando falserebbe i tempi. fidati=True (K2 appena fatta ha detto «pronta dopo l'arrivo»): niente
    attesa in più."""
    t0 = sch.orologio()
    sch.manda(cmd_casa())
    sec, visti, come = sch.aspetta_casa(25, ferma)
    if not fidati and come != "finito":
        while sch.orologio() - t0 < CASA_SICURA_S:
            if ferma is not None and ferma():
                raise InterruptedError
            sch.attesa(0.05)
    sch.attesa(0.5)
    return sec, visti, come


LONTANO_MM = 100.0  # K2: da quanto lontano si torna a casa la seconda volta
SOGLIA_ARRIVO_S = 0.5  # K2: se da lontano «pronta» arriva almeno questo dopo che da vicino, aspetta l'arrivo


def prova_k2(diario, links, ferma=None, scheda="M2", lontano_mm=LONTANO_MM):
    """Ritorno a casa (0.22.5): tre volte. La prima porta la testa a casa da dove si trova; la seconda parte da casa
    (tempo «da vicino»); poi la testa va 100 mm a destra a 30 mm/s e torna a casa (tempo «da lontano»). Se da lontano
    «pronta» arriva più tardi, la scheda dice «pronta» quando la testa è arrivata; se arriva subito, lo dice prima e il
    programma dovrà aspettare. Laser spento."""
    sch, info = _apri(links, diario, "K2")
    if sch is None:
        return None
    tempi, visti_tutti = {}, {}
    try:
        try:
            for nome in ("prima", "vicino", "lontano"):
                if nome == "lontano":
                    sch.manda(cmd_a_velocita(scheda, 30.0, lontano_mm))
                    sch.aspetta_fine(3 * lontano_mm / 30.0 + 15, ferma)
                    sch.attesa(0.3)
                sch.manda(cmd_casa())
                sec, visti, come = sch.aspetta_casa(30, ferma)
                tempi[nome] = None if sec is None else round(sec, 3)
                visti_tutti[nome] = {"stati_nel_tempo": visti[:60], "fine": come}
                if sec is None:
                    break
                sch.attesa(0.3)
        except InterruptedError:
            _interrompi(sch)
            diario.risultato("K2", "fermata", **info, tempi=tempi, casa=visti_tutti)
            raise
        esito, verdetto, extra = "nessuna fine vista", "", {}
        if tempi.get("vicino") is not None and tempi.get("lontano") is not None:
            esito = "ok"
            diff = tempi["lontano"] - tempi["vicino"]
            extra["differenza_s"] = round(diff, 3)
            if diff >= SOGLIA_ARRIVO_S:
                verdetto = "pronta_dopo_arrivo"
                extra["velocita_ritorno_circa"] = round(lontano_mm / diff, 1)  # mm/s, con le rampe dentro
            else:
                verdetto = "pronta_subito"
        fine = (visti_tutti.get("lontano") or visti_tutti.get("prima") or {}).get("fine", "")
        diario.risultato("K2", esito, **info, tempi=tempi, casa=visti_tutti, verdetto=verdetto, fine=fine,
                         lontano_mm=lontano_mm, errori_crc=sch.errori_crc, **extra)
        ultimi = (visti_tutti.get("lontano") or visti_tutti.get("prima") or {}).get("stati_nel_tempo", [])
        return tempi.get("lontano"), ultimi
    except InterruptedError:  # è un OSError: già scritto «fermata», va solo passato su
        raise
    except OSError as ex:
        diario.risultato("K2", "errore di collegamento", **info, errore=f"{type(ex).__name__}: {ex}",
                         tempi=tempi, errori_crc=sch.errori_crc)
        return None
    finally:
        sch.chiudi()


def prova_k3(diario, links, scheda, ferma=None, velocita=VELOCITA_PROVA, distanze=DISTANZE_PROVA, casa=True,
             fidati_di_pronta=False):
    """Velocità vera: da casa, andata e ritorno a laser spento a velocità note, cronometrando fino a «finito».
    Con due distanze alla stessa velocità, la differenza dei tempi toglie le rincorse: velocità = Δd / Δt."""
    sch, info = _apri(links, diario, "K3")
    if sch is None:
        return None
    misure = []
    try:
        if casa:
            _a_casa(sch, ferma, fidati_di_pronta)  # 0.22.5: prima aspettava «finito», che dopo la casa non arriva
        for v in velocita:
            for d in distanze:
                for verso in (1, -1):
                    if ferma is not None and ferma():
                        raise InterruptedError
                    cmd = cmd_a_velocita(scheda, v, verso * d)
                    t0 = sch.orologio()
                    sch.manda(cmd)
                    sec, visti = sch.aspetta_fine(3 * d / v + 15, ferma)
                    tot = None if sec is None else sch.orologio() - t0
                    # 0.22.5: due tempi. «secondi» parte prima dell'invio dei pacchetti, «dopo_invio_s» quando l'ultimo
                    # è arrivato alla scheda. Per la velocità conta il secondo: sulla K40 vera l'invio è durato da
                    # 0,1 a 0,45 s, a caso (rapporto FLC-20261123-1937-1187), e sporcava la misura a 10 mm/s.
                    misure.append({"v": v, "mm": d, "verso": verso, "codice": codice_velocita(scheda, v),
                                   "secondi": None if tot is None else round(tot, 3),
                                   "dopo_invio_s": None if sec is None else round(sec, 3), "stati": visti[:20]})
        stime, rapporti = {}, {}
        for v in velocita:
            t = {d: [m["dopo_invio_s"] for m in misure if m["v"] == v and m["mm"] == d and m["dopo_invio_s"] is not None]
                 for d in distanze}
            if all(t.values()) and len(distanze) >= 2:
                d1, d2 = distanze[0], distanze[-1]
                dt = sum(t[d2]) / len(t[d2]) - sum(t[d1]) / len(t[d1])
                vero = (round(d2 * MIL_PER_MM) - round(d1 * MIL_PER_MM)) / MIL_PER_MM  # in millesimi interi
                stime[str(v)] = round(vero / dt, 3) if dt > 0 else None
                if stime[str(v)]:
                    rapporti[str(v)] = round(stime[str(v)] / v, 4)  # velocità vera / velocità chiesta
        diario.risultato("K3", "ok" if stime else "tempi non misurati", **info, scheda=scheda, misure=misure,
                         velocita_vera=stime, rapporto=rapporti, errori_crc=sch.errori_crc)
        return stime
    except InterruptedError:
        _interrompi(sch)
        diario.risultato("K3", "fermata", **info, scheda=scheda, misure=misure)
        raise
    except OSError as ex:
        diario.risultato("K3", "errore di collegamento", **info, scheda=scheda, misure=misure,
                         errore=f"{type(ex).__name__}: {ex}", errori_crc=sch.errori_crc)
        return None
    finally:
        sch.chiudi()


CORSE_K4 = (50.0, -50.0, 100.0, -100.0)
V_K4 = 30.0


def giri_nel_lavoro(tempi_separati, tempo_unico, corse=CORSE_K4):
    """K4: quante volte la testa fa il «giro» (supera il punto, torna, piccolo colpo in Y) nel lavoro unico.
    Dalle corse separate: velocità vera v = Δd/Δt fra la corsa lunga e la corta, e un giro g = tempo della corta - d/v.
    Nel lavoro unico: (tempo - somma delle distanze / v) / g. Circa 1: il giro c'è solo all'inizio e alla fine;
    circa quante le corse: c'è a ogni cambio di verso. -> (giri, v, g) oppure None se i tempi non bastano."""
    corti = [t for c, t in zip(corse, tempi_separati) if abs(c) == min(abs(x) for x in corse) and t is not None]
    lunghi = [t for c, t in zip(corse, tempi_separati) if abs(c) == max(abs(x) for x in corse) and t is not None]
    if not corti or not lunghi or tempo_unico is None:
        return None
    d1, d2 = min(abs(x) for x in corse), max(abs(x) for x in corse)
    t1, t2 = sum(corti) / len(corti), sum(lunghi) / len(lunghi)
    if t2 <= t1:
        return None
    v = (round(d2 * MIL_PER_MM) - round(d1 * MIL_PER_MM)) / MIL_PER_MM / (t2 - t1)
    g = t1 - d1 / v
    if g <= 0.05:
        return None
    totale = sum(round(abs(c) * MIL_PER_MM) for c in corse) / MIL_PER_MM
    return round((tempo_unico - totale / v) / g, 2), round(v, 3), round(g, 3)


def prova_k4(diario, links, scheda, ferma=None, v=V_K4, corse=CORSE_K4, fidati_di_pronta=False):
    """Un solo lavoro (0.22.5). Sulla K40 vera, alla fine di ogni corsa di K3 la testa supera il punto di circa 4 mm,
    torna e fa un piccolo colpo in Y (video di Evo, 23/11). K3 entra ed esce dal modo compatto a ogni corsa; un taglio
    vero entra una volta sola. Qui: le stesse corse prima una per lavoro, poi tutte in un solo lavoro, cronometrate.
    Dai tempi si conta quante volte la testa fa il giro nel lavoro unico. Laser spento."""
    sch, info = _apri(links, diario, "K4")
    if sch is None:
        return None
    separate, unico = [], {}
    try:
        try:
            _a_casa(sch, ferma, fidati_di_pronta)
            for c in corse:
                if ferma is not None and ferma():
                    raise InterruptedError
                sch.manda(cmd_a_velocita(scheda, v, c))
                sec, visti = sch.aspetta_fine(3 * abs(c) / v + 15, ferma)
                separate.append({"mm": c, "dopo_invio_s": None if sec is None else round(sec, 3), "stati": visti[:20]})
                sch.attesa(0.3)
            cmd = cmd_lavoro_unico(scheda, v, corse)
            t0 = sch.orologio()
            sch.manda(cmd)
            sec, visti = sch.aspetta_fine(3 * sum(abs(c) for c in corse) / v + 20, ferma)
            unico = {"dopo_invio_s": None if sec is None else round(sec, 3),
                     "secondi": None if sec is None else round(sch.orologio() - t0, 3), "stati": visti[:20]}
        except InterruptedError:
            _interrompi(sch)
            diario.risultato("K4", "fermata", **info, scheda=scheda, separate=separate, unico=unico)
            raise
        calc = giri_nel_lavoro([m["dopo_invio_s"] for m in separate], unico.get("dopo_invio_s"), corse)
        extra, verdetto = {}, ""
        if calc is not None:
            giri, vv, g = calc
            extra = {"giri": giri, "velocita_vera": vv, "giro_s": g}
            n = len(corse)
            verdetto = ("solo_inizio_fine" if 0.5 <= giri <= 1.6 else "a_ogni_corsa" if n - 0.6 <= giri <= n + 1
                        else "non_chiaro")
        diario.risultato("K4", "ok" if calc is not None else "tempi non misurati", **info, scheda=scheda, v=v,
                         corse=list(corse), separate=separate, unico=unico, verdetto=verdetto,
                         errori_crc=sch.errori_crc, **extra)
        return calc
    except InterruptedError:  # è un OSError: già scritto «fermata», va solo passato su
        raise
    except OSError as ex:
        diario.risultato("K4", "errore di collegamento", **info, scheda=scheda, separate=separate, unico=unico,
                         errore=f"{type(ex).__name__}: {ex}", errori_crc=sch.errori_crc)
        return None
    finally:
        sch.chiudi()


def _interrompi(sch):
    try:
        sch.manda(cmd_ferma())
    except Exception:  # noqa: BLE001
        pass


def ferma_subito(links):
    """Pulsante Ferma: manda «I» (interrompi) a ogni collegamento che si apre."""
    for link in links:
        try:
            sch = Scheda(link).apri()
            sch.manda(cmd_ferma())
            sch.chiudi()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False
