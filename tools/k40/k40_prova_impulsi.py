# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.23.3: file di prova degli impulsi per la K40 (scheda M2 Nano), da eseguire con «File → Esegui un file G-code».

Sulla K40 la scheda accende e spegne soltanto: la scala di grigi si potrebbe fare solo a impulsi, e serve sapere quanto
è corto l'impulso più breve che il tubo riesce a seguire. Il file incide tre gruppi di 8 strisce (25, 50 e 100 mm/s;
impulsi accesi e spenti da 1, 2, 3, 4, 6, 8, 12 e 16 passi, 1 passo = 0,0254 mm). Con una lente si guarda da quale
striscia i puntini restano separati.

Uso: python tools/k40/k40_prova_impulsi.py K40-prova-impulsi.gcode
"""
import sys
MIL = 0.0254
VEL = (25, 50, 100)  # mm/s
IMPULSI = (1, 2, 3, 4, 6, 8, 12, 16)  # passi (1 passo = 0,0254 mm)
X0, LUNGA, RINCORSA = 50.0, 15.0, 5.0
Y0, FRA_STRISCE, FRA_GRUPPI, RIGHE, FRA_RIGHE = 30.0, 2.0, 6.0, 3, 0.2


def genera():
    L = ["; FreeLaserCut 0.23.3 — prova degli impulsi per la K40 (laser acceso/spento a tratti uguali)",
         "; gruppi dall'alto: 25, 50, 100 mm/s; in ogni gruppo 8 strisce, impulsi da 1, 2, 3, 4, 6, 8, 12, 16 passi",
         "; (1 passo = 0,025 mm). Guardare con una lente da quale striscia i puntini sono separati.",
         "G90 G21", "M4 S0"]
    y = Y0
    for v in VEL:
        L.append(f"; --- {v} mm/s")
        for n in IMPULSI:
            L.append(f"; impulsi da {n} passi ({n * MIL:.3f} mm, {n * MIL / v * 1000:.2f} ms)")
            for r in range(RIGHE):
                yy = y + r * FRA_RIGHE
                L.append(f"G0 X{X0 - RINCORSA:.3f} Y{yy:.3f}")
                L.append(f"G1 X{X0:.3f} S0 F{v * 60}")
                x, acceso, passo = X0, True, n * MIL
                while x + passo <= X0 + LUNGA + 1e-9:
                    x += passo
                    L.append(f"G1 X{x:.4f} S{1000 if acceso else 0}")
                    acceso = not acceso
                L.append(f"G1 X{x + RINCORSA:.3f} S0")
            y += FRA_STRISCE
        y += FRA_GRUPPI - FRA_STRISCE
    L += ["M5 S0", "G0 X10 Y10", "; fine"]
    return L


if __name__ == "__main__":
    open(sys.argv[1], "w", newline="\r\n").write("\n".join(genera()) + "\n")
