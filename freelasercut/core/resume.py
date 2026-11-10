# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Ripresa di un lavoro interrotto (cavo staccato, corrente, arresto) da una riga precisa.

Ricostruisce lo stato modale fino alla riga N (coordinate, sistema G54/G55, unità,
laser M3/M4, potenza S, velocità F, aria) e prepara un programma che:
  1. ripristina lo stato senza muovere nulla;
  2. porta la testa, a laser spento, al punto in cui si era fermata;
  3. continua dalla riga N.
"""
import re
from freelasercut.i18n import tr  # noqa: E402

_W = re.compile(r"([A-Z])\s*(-?\d*\.?\d+)")


def analyse(lines, upto):
    st = {"x": None, "y": None, "abs": True, "cs": "G54", "laser": "M5", "s": 0.0, "f": None, "air": False,
          "header": [], "g92": False, "g55_zero": False}
    for i, raw in enumerate(lines[:upto]):
        line = raw.split(";")[0].strip().upper()
        if not line:
            continue
        if "G10" in line and "L2" in line and "P2" in line:
            st["g55_zero"] = True
        if re.search(r"G5[4-9](?![.\d])", line):
            st["cs"] = re.search(r"G5[4-9]", line).group(0)
        if "G92.1" in line:
            st["g92"] = False
        elif re.search(r"G92(?![.\d])", line):
            st["g92"] = True
        for letter, v in _W.findall(line):
            val = float(v)
            if letter == "G":
                if val == 90:
                    st["abs"] = True
                elif val == 91:
                    st["abs"] = False
            elif letter == "M":
                if val in (3, 4):
                    st["laser"] = f"M{int(val)}"
                elif val == 5:
                    st["laser"] = "M5"
                elif val in (7, 8, 106):  # 0.18.5: l'aria può essere M7 o M106, non solo M8
                    st["air"] = True
                    st["air_cmd"] = f"M{int(val)}"
                elif val in (9, 107):
                    st["air"] = False
                    st["air_off"] = f"M{int(val)}"
            elif letter == "S":
                st["s"] = val
            elif letter == "F":
                st["f"] = val
            elif letter == "X":
                st["x"] = val if st["abs"] else (st["x"] or 0.0) + val
            elif letter == "Y":
                st["y"] = val if st["abs"] else (st["y"] or 0.0) + val
    return st


def can_resume(lines, upto):
    st = analyse(lines, upto)
    if st["g92"]:
        return False, (tr("Il lavoro usa la «posizione attuale» (G92): dopo un'interruzione il riferimento è perso. "
                       "Riavvialo dall'inizio oppure usa le coordinate assolute o l'origine utente."))
    if not st["abs"]:
        return False, tr("Il lavoro usa coordinate relative (G91): non si può riprendere in sicurezza.")
    return True, ""


def resume_program(lines, upto, back=0):
    """Programma per riprendere dalla riga `upto` (indice nelle righe originali).
    back: righe di sicurezza da rifare prima del punto (sovrapposizione)."""
    start = max(0, upto - back)
    st = analyse(lines, start)
    out = ["; FreeLaserCut — ripresa dalla riga %d" % (start + 1), "G90 G21", "M5 S0"]
    if st["g55_zero"]:
        out.append("G10 L2 P2 X0 Y0")
    out.append(st["cs"])
    if st["air"]:
        out.append(st.get("air_cmd", "M8"))  # lo stesso comando del lavoro
    elif st.get("air_cmd") or st.get("air_off"):
        out.append(st.get("air_off", "M9"))  # un lavoro senza comandi dell'aria resta senza
    if st["x"] is not None and st["y"] is not None:
        out.append(f"G0 X{st['x']:.3f} Y{st['y']:.3f}")
    laser = st["laser"] if st["laser"] != "M5" else "M4"
    out.append(f"{laser} S0")
    first = f"G1 S{st['s']:g}" + (f" F{st['f']:g}" if st["f"] else "")
    out.append(first)
    out += lines[start:]
    return out
