# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.2: le criticità dell'analisi del 13/11/2026 (freeburn/analisi-critica-2026-11-13.md), una prova per riga
della matrice dei casi (freeburn/aggiornamento-0.19.2.md).

Uso:  python tests/test_v192_analisi.py [classica | banco | chiaro]

A1  scorciatoie: nessun tasto che Qt non conosce (Stop era «Ctrl+Break»), nessun doppione, Stop con tre tasti
A2  Banco a 1920×1080, 1600×900, 1366×768 e 1280×720: niente sovrapposto, niente fuori dalla finestra
A3  ordine dei tagli: uguale a prima fino a 3000 tracciati, fori prima anche oltre, tempi
A4  preparazione del lavoro con segni di vita e Annulla; nelle prove storiche resta com'era
B1  Banco: il pulsante di avvio non si sposta quando si seleziona
B2  Banco: barra della selezione mai più larga dello spazio libero, riga dei comandi richiudibile
B3  materiali adattati alla potenza del laser (stima), voci dell'utente intatte, B1 40W invariato
B4  menu Laser riordinato, niente doppioni, Preferenze specchio di menu e pannelli
B5  ricerca dei comandi anche nella Classica, comandi recenti in cima
B6  pannello Laser: la riga di connessione non esce dal pannello; assi in una sezione loro
B7  riga selezionata leggibile nei due temi (contrasto misurato sui pixel)
C1  aggiornamenti: versioni in anteprima solo per chi le chiede
C2  la finestra della 0.1 non è più in app.py
C3  errori ignorati: una riga nel registro, senza toccare «l'ultimo errore del programma»
C4  indice delle prove per area
"""
import json
import math
import os
import random
import sys
import tempfile
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if MODE == "banco" else "classica"
os.environ["FLC_THEME"] = "chiaro" if MODE == "chiaro" else "scuro"
os.environ["FLC_ACCENT"] = "blu"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_BUSY", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QAction, QColor, QTransform  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QRadioButton,
)

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut import app as flc_app, diag, theme, updater  # noqa: E402
from freelasercut.core import gcode, geom, materials  # noqa: E402
from freelasercut.core.document import EllipseShape, RectShape, TextShape  # noqa: E402
from freelasercut.ui import busy, style  # noqa: E402
from freelasercut.ui.main_window import STOP_KEYS, MainWindow  # noqa: E402

# lo stesso aspetto dell'avvio vero (le prove storiche non caricano il foglio di stile: qui servono colori e misure)
app.setStyle("Fusion")
style.fast_ui(app)
style.load_fonts()
app.setFont(style.ui_font(9))
app.setStyleSheet(theme.QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)

results = []
BANCO = MODE == "banco"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(n=40):
    for _ in range(n):
        app.processEvents()


def at(shape, x, y):
    shape.tf = QTransform().translate(x, y)
    return shape


w = MainWindow()
w.resize(1400, 900)
w.show()
spin(80)
ed, cv = w.editor, w.canvas

# ============================================================================================ A1 · scorciatoie
acts = w.findChildren(QAction)
unknown = [(a.text(), n) for a in acts for n, ks in enumerate(a.shortcuts())
           if ks.isEmpty() or any(ks[i].key() == Qt.Key_unknown for i in range(ks.count()))]
check("A1 nessuna scorciatoia con un tasto che Qt non conosce", not unknown, str(unknown[:4]))
by_key = {}
for a in acts:
    for ks in a.shortcuts():
        by_key.setdefault(ks.toString(), set()).add(a)
dup = {k: [x.text() for x in v] for k, v in by_key.items() if len(v) > 1}
check("A1 nessuna scorciatoia assegnata a due comandi", not dup, str(dup))
stop = w.acts["stop"]
check("A1 Stop: Ctrl+Pausa (nei due nomi che manda la tastiera) e Maiusc+Esc",
      {k.toString() for k in stop.shortcuts()} == set(STOP_KEYS) == {"Ctrl+Pause", "Ctrl+Cancel", "Shift+Esc"},
      str([k.toString() for k in stop.shortcuts()]))
from freelasercut.ui import plates  # noqa: E402

check("A1 i tasti di Stop restano attivi nella vista d'insieme dei piani", set(STOP_KEYS) <= plates.OVERVIEW_KEYS)
fired = []
stop.triggered.connect(lambda *_: fired.append(1))
stop_was = stop.isEnabled()
stop.setEnabled(True)  # a laser scollegato il comando è spento; qui interessa il tasto
w.activateWindow()
cv.setFocus()
spin()
QTest.keyClick(cv, Qt.Key_Escape, Qt.ShiftModifier)
spin()
check("A1 Maiusc+Esc fa partire davvero il comando Stop", len(fired) == 1, f"{len(fired)} volte")
QTest.keyClick(cv, Qt.Key_Escape)
spin()
check("A1 Esc da solo non ferma niente (serve a chiudere strumenti e finestre)", len(fired) == 1)
cv.set_tool("line")  # con uno strumento di disegno attivo Esc è suo: Maiusc+Esc deve restare lo Stop
spin()
QTest.keyClick(cv, Qt.Key_Escape, Qt.ShiftModifier)
spin()
check("A1 Maiusc+Esc ferma anche con uno strumento di disegno attivo sul piano", len(fired) == 2, f"{len(fired)} volte")
cv.set_tool("line")
spin()
QTest.keyClick(cv, Qt.Key_Escape)
spin()
check("A1 … ed Esc da solo continua a chiudere lo strumento di disegno", len(fired) == 2
      and next(k for k, v in cv.tools.items() if v is cv.tool) == "select")
stop.setEnabled(False)
cv.set_tool("line")
spin()
QTest.keyClick(cv, Qt.Key_Escape, Qt.ShiftModifier)
spin()
check("A1 a comando spento (nessun lavoro) Maiusc+Esc non ferma niente e non dà errori", len(fired) == 2)
cv.set_tool("select")
stop.setEnabled(stop_was)
check("A1 la guida delle scorciatoie dice i tasti veri", "Ctrl+Pausa o Maiusc+Esc stop" in open(
    os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read())

# forme per le prove che seguono
r1 = at(RectShape(120, 80, layer=1), 100, 100)
e1 = at(EllipseShape(90, 90, layer=2), 200, 200)
t1 = at(TextShape("FreeLaserCut", size=14, layer=3), 60, 320)
for s in (r1, e1, t1):
    ed.add([s])
ed.clear_selection()
spin()

# ====================================================================== A2 · B1 · B2 · Banco su ogni schermo
if BANCO:
    bc = w.banco

    def box(widget):
        return QRect(widget.mapTo(w, QPoint(0, 0)), widget.size())

    def fully_visible(widget):
        """Tutto dentro la finestra e non tagliato dal contenitore."""
        return (widget.isVisibleTo(w) and w.rect().contains(box(widget))
                and widget.visibleRegion().boundingRect() == widget.rect())

    def overlays():
        out = {"strati": bc.rail, "percorso": bc.flow, "strumenti": bc.island}
        if bc.props_card.isVisibleTo(w):
            out["proprietà"] = bc.props_card
        if bc.view_box.isVisibleTo(w):
            out["vista"] = bc.view_box
        if bc.ctx.isVisibleTo(w):
            out["selezione"] = bc.ctx
        return out

    def clashes():
        o = overlays()
        names = list(o)
        return [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if box(o[a]).intersects(box(o[b]))]

    sizes = [(1920, 1080), (1600, 900), (1366, 768), (1280, 720)]
    for W, H in sizes:
        w.resize(W, H)
        ed.clear_selection()
        cv.set_tool("select")
        bc.ctx._fold_choice = "auto"
        spin(80)
        tag = f"{W}×{H}"
        real = f"{w.width()}×{w.height()}"
        starts = {}
        for state in ("vuoto", "selezione", "strumento"):
            ed.clear_selection()
            cv.set_tool("select")
            if state == "selezione":
                ed.select([r1])
            elif state == "strumento":
                cv.set_tool("rect")
            spin(80)
            time.sleep(0.02)
            spin(40)
            starts[state] = box(bc.flow.b_start)
            what = f"A2 {tag} ({state})"
            check(f"{what}: il pulsante di avvio è tutto in vista", fully_visible(bc.flow.b_start),
                  f"{box(bc.flow.b_start)} in {real}")
            check(f"{what}: le due spunte di sicurezza sono in vista",
                  fully_visible(bc.flow.c_glasses) and fully_visible(bc.flow.c_air))
            cl = clashes()
            check(f"{what}: nessun pannello ne copre un altro", not cl, str(cl))
            out = [n for n, x in overlays().items() if not w.rect().contains(box(x))]
            check(f"{what}: nessun pannello esce dalla finestra", not out, str(out))
            if state == "selezione":
                lo = box(bc.rail).right()
                hi = box(bc.flow).left()
                c = box(bc.ctx)
                check(f"B2 {tag}: la barra della selezione sta fra gli strati e la colonna destra",
                      bc.ctx.isVisibleTo(w) and c.left() > lo and c.right() < hi, f"{c} fra {lo} e {hi}")
                check(f"B2 {tag}: riga dei comandi {'richiusa' if cv.height() < bc.ctx.FOLD_BELOW else 'aperta'} di partenza",
                      bc.ctx.row2.isVisibleTo(w) == (cv.height() >= bc.ctx.FOLD_BELOW))
            if state != "vuoto":
                check(f"{what}: le proprietà sono in vista sopra il percorso",
                      bc.props_card.isVisibleTo(w) and box(bc.props_card).bottom() < box(bc.flow).top())
        check(f"B1 {tag}: il pulsante di avvio resta nello stesso punto con e senza selezione",
              starts["vuoto"] == starts["selezione"] == starts["strumento"], str(starts))
    # il vuoto sopra il percorso lascia passare i clic al piano
    w.resize(1920, 1080)
    ed.clear_selection()
    cv.set_tool("select")
    spin(80)
    gap = QPoint(bc.right.x() + bc.right.width() // 2, bc.right.y() + 30)
    under = cv.childAt(gap)
    check("B1 nel vuoto sopra il percorso il piano resta cliccabile",
          bc.flow.y() > 60 and under is not bc.right and (under is None or not bc.right.isAncestorOf(under)),
          f"sotto il clic: {under}")
    # riga dei comandi richiudibile, e la scelta si ricorda
    ed.select([r1])
    spin(80)
    h_open = bc.ctx.height()
    check("B2 schermo grande: riga dei comandi in vista", bc.ctx.row2.isVisibleTo(w))
    bc.ctx.b_fold.click()
    spin(60)
    check("B2 la freccetta richiude la riga dei comandi", not bc.ctx.row2.isVisibleTo(w) and bc.ctx.height() < h_open,
          f"{bc.ctx.height()} / {h_open}")
    check("B2 la scelta si ricorda", w.qs.value("banco_ctx_fold") == "closed")
    bc.ctx.b_fold.click()
    spin(60)
    check("B2 la freccetta la riapre", bc.ctx.row2.isVisibleTo(w) and w.qs.value("banco_ctx_fold") == "open")
    # finestra stretta: i tre comandi in più passano nel menu Altro, nessuno si perde
    w.resize(1280, 720)
    spin(80)
    more = [a for a in bc.ctx.b_more.menu().actions() if not a.isSeparator()]
    check("B2 finestra stretta: Ottimizza, Offset e Converti passano nel menu «Altro»",
          bc.ctx.narrow and all(w.acts[k] in more for k in ("nest", "offset", "to_path")))
    w.resize(1920, 1080)
    spin(80)
    more = [a for a in bc.ctx.b_more.menu().actions() if not a.isSeparator()]
    check("B2 finestra larga: tornano pulsanti (e nel menu non sono doppi)",
          not bc.ctx.narrow and all(b.isVisibleTo(w) for b in bc.ctx.wide_only)
          and not any(w.acts[k] in more for k in ("nest", "offset", "to_path")))
    ed.clear_selection()
    w.resize(1400, 900)
    spin(60)

# ============================================================================================ B5 · ricerca
pal = w.banco.palette if BANCO else getattr(w, "cmd_palette", None)
check("B5 la ricerca dei comandi c'è in questa interfaccia", pal is not None)
if not BANCO:
    pa = w.acts.get("palette")
    check("B5 Classica: Ctrl+F e F3 aprono la ricerca",
          pa is not None and {k.toString() for k in pa.shortcuts()} == {"Ctrl+F", "F3"})
    check("B5 Classica: «Cerca un comando…» è la prima voce del menu Aiuto", w.m_help.actions()[0] is pa)
if pal is not None:
    w.qs.remove("palette_recent")
    pal.open()
    spin()
    check("B5 la ricerca si apre e mostra i comandi", pal.isVisible() and pal.list.count() > 50, str(pal.list.count()))
    first_before = pal.list.item(0).data(Qt.UserRole)
    pal.edit.setText("griglia")
    spin()
    rows = [pal.list.item(i) for i in range(pal.list.count())]
    hit = next((it for it in rows if it.data(Qt.UserRole) is w.acts["grid"]), None)
    check("B5 scrivendo «griglia» si trova il comando Griglia", hit is not None)
    was = w.acts["grid"].isChecked()
    pal._run(hit)
    spin()
    check("B5 Invio esegue il comando e chiude la ricerca", w.acts["grid"].isChecked() != was and not pal.isVisible())
    pal.open()
    spin()
    check("B5 alla riapertura il comando appena usato è in cima", pal.list.item(0).data(Qt.UserRole) is w.acts["grid"]
          and first_before is not w.acts["grid"])
    check("B5 i recenti si ricordano per nome interno (valgono in ogni lingua)", w.qs.value("palette_recent") in (
        ["a:grid"], "a:grid"), str(w.qs.value("palette_recent")))
    pal.hide()
    w.acts["grid"].trigger()  # com'era
    spin()

# ============================================================================================ B4 · menu
def menu_actions(menu):
    out = []
    for a in menu.actions():
        if a.menu() is not None:
            out += menu_actions(a.menu())
        elif not a.isSeparator():
            out.append(a)
    return out


laser = w.m_laser.actions()
names = {a: k for k, a in w.acts.items()}
order = [names.get(a, "§" if a.property("menu_title") else "-") for a in laser]
daily = ("connect", "home", "frame", "verify", "preview", "start", "pause", "stop", "materials")
setup = ("identify", "serial_speed", "scan_offset", "autofocus", "board_backup", "profile_export", "profile_import")
check("B4 menu Laser: prima i comandi di tutti i giorni, poi (sotto un titolo) le regolazioni della macchina",
      "§" in order and all(order.index(k) < order.index("§") for k in daily)
      and all(order.index(k) > order.index("§") for k in setup), str(order))
head = next((a for a in laser if a.property("menu_title")), None)
check("B4 il titolo del gruppo è una scritta (non un comando) e non compare nella ricerca dei comandi",
      head is not None and not head.text() and head.defaultWidget().text() == "CONFIGURAZIONE DELLA MACCHINA"
      and (pal is None or (pal.collect(), all(a is not head for a, _p in pal.entries))[1]))
check("B4 «Salva G-code» ed «Esegui un file G-code» stanno in un menu solo (File)",
      all(w.acts[k] not in laser and w.acts[k] in w.m_file.actions() for k in ("save_gcode", "run_file")))
everything = []
for top in w.menuBar().actions():
    if top.menu() is not None:
        everything += menu_actions(top.menu())
lost = [k for k in daily + setup + ("save_gcode", "run_file", "material_test", "learned", "fire_guard", "phone", "rotary",
                                    "unlock_m", "light_bed", "snap_obj", "snap_grid", "dither_prev")
        if w.acts[k] not in everything]
check("B4 nessun comando è sparito dai menu", not lost, str(lost))
sett = w.m_settings.actions()
check("B4 «Preferenze…» è la prima voce di Impostazioni (e quindi della ⚙ nel Banco)", sett[0] is w.acts["prefs"])
view_in_settings = [k for k in ("light_bed", "snap_obj", "snap_grid", "dither_prev") if w.acts[k] in sett]
check("B4 le opzioni di vista: nel Banco sotto la ⚙, nella Classica solo in Visualizza",
      len(view_in_settings) == (4 if BANCO else 0), str(view_in_settings))

from freelasercut.ui.dialogs_prefs import PreferencesDialog  # noqa: E402

dlg = PreferencesDialog(w)
dlg.show()
spin()
keys = [k for k, _w in dlg.rows()]
check("B4 Preferenze: quattro sezioni (macchina, lavoro, interfaccia, aggiornamenti)",
      {"machine", "job", "ui", "updates"} <= set(keys) and len(keys) >= 20, f"{len(keys)} righe")
mirror = next(x for _k, x in dlg.rows("job") if isinstance(x, QCheckBox) and x.text() == w.laser.optimize.text())
before = w.laser.optimize.isChecked()
mirror.click()
spin()
check("B4 una spunta nelle Preferenze cambia quella del pannello Laser", w.laser.optimize.isChecked() != before)
w.laser.optimize.setChecked(before)
spin()
check("B4 … e viceversa", mirror.isChecked() == before)
gridrow = next(x for _k, x in dlg.rows("ui") if isinstance(x, QCheckBox) and x.text() == w.acts["grid"].text().replace("&", ""))
gb = w.acts["grid"].isChecked()
gridrow.click()
spin()
check("B4 una spunta nelle Preferenze esegue il comando del menu", w.acts["grid"].isChecked() != gb)
w.acts["grid"].trigger()
spin()
check("B4 … e il comando del menu aggiorna le Preferenze", gridrow.isChecked() == gb)
radios = [r for _k, x in dlg.rows("ui") for r in x.findChildren(QRadioButton)]
expert = next(r for r in radios if r.text() == w.acts["help_expert"].text().replace("&", ""))
expert.click()
spin()
check("B4 il livello di aiuto si sceglie anche dalle Preferenze", w.acts["help_expert"].isChecked())
w.acts["help_normal"].trigger()
spin()
buttons = [x.text() for _k, x in dlg.rows("machine") if isinstance(x, QPushButton)]
check("B4 Preferenze → Macchina: le regolazioni della macchina che erano sparse",
      all(w.acts[k].text().replace("&", "") in buttons for k in setup + ("setup_wizard", "wifi_wizard")), str(buttons))
inv = [x.text() for _k, x in dlg.rows("machine") if isinstance(x, QCheckBox)]
check("B4 Preferenze → Macchina: inversione degli assi", w.laser.inv_x.text() in inv and w.laser.inv_y.text() in inv)
total = len(dlg.rows())
n = dlg.filter("wifi")
check("B4 la ricerca nelle Preferenze stringe l'elenco", 1 <= n < total, f"{n}/{total}")
n = dlg.filter("zzzqqq")
check("B4 nessun risultato: lo dice", n == 0 and dlg.empty.isVisibleTo(dlg))
n = dlg.filter("")
check("B4 ricerca vuota: tornano tutte", n == total and not dlg.empty.isVisibleTo(dlg))
dlg.close()
spin()
check("B4 chiuse le Preferenze, le spunte del pannello funzionano ancora", (w.laser.optimize.setChecked(not before), spin(5),
      w.laser.optimize.isChecked() != before, w.laser.optimize.setChecked(before))[2])

# ============================================================================================ B6 · pannello Laser
from freelasercut.ui.widgets import SqueezeRow  # noqa: E402

row = SqueezeRow()
hl = QHBoxLayout(row)
hl.setContentsMargins(0, 0, 0, 0)
hl.setSpacing(4)
fixed = QPushButton("fisso")
fixed.setFixedWidth(100)
opt1, opt2 = QLabel("primo"), QLabel("secondo")
opt1.setFixedWidth(60)
opt2.setFixedWidth(40)
for x in (fixed, opt2, opt1):
    hl.addWidget(x)
row.set_optional([opt1, opt2])  # opt1 è il primo a sparire
row.show()
seen = {}
for width in (300, 150, 110):
    row.resize(width, 30)
    spin(10)
    seen[width] = (opt1.isVisibleTo(row), opt2.isVisibleTo(row))
check("B6 riga che si stringe: larga tutti, media via il primo facoltativo, stretta via tutti e due",
      seen == {300: (True, True), 150: (False, True), 110: (False, False)}, str(seen))
check("B6 la riga dichiara come larghezza minima solo i pezzi fissi", row.minimumSizeHint().width() == 100,
      str(row.minimumSizeHint().width()))
row.close()
check("B6 la riga di connessione può stringersi fino al pannello più stretto (300 px)",
      w.connbar.minimumSizeHint().width() <= 290, str(w.connbar.minimumSizeHint().width()))
check("B6 l'elenco delle porte mostra i nomi interi anche se la casella è stretta", w.port_combo.view().minimumWidth() >= 300)
if not BANCO:
    area = w.docks["laser"].widget()
    spin(40)
    check("B6 Classica: il pannello Laser non è più largo del suo spazio (niente tagliato a destra)",
          w.laser.width() <= area.viewport().width(), f"{w.laser.width()} > {area.viewport().width()}")
    check("B6 Classica: lo stato della connessione è in vista", w.pill.isVisibleTo(w.laser)
          and w.laser.rect().contains(QRect(w.pill.mapTo(w.laser, QPoint(0, 0)), w.pill.size())))
check("B6 l'inversione degli assi è in fondo al pannello, dopo la stima del lavoro",
      w.laser.inv_x.parent() is w.laser and w.laser.layout().indexOf(w.laser.inv_x) > w.laser.layout().indexOf(w.laser.summary)
      > w.laser.layout().indexOf(w.laser.verify_first))

# ============================================================================================ B7 · contrasto
def lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


if not BANCO:
    table = w.layers.tree
    w.show_panel(w.docks["layers"])
    table.setFocus()
    table.setCurrentItem(table.topLevelItem(0))
    spin(40)
    cell = table.visualRect(table.indexFromItem(table.topLevelItem(0), 2))
    img = table.viewport().grab(cell).toImage()
    px = [(c.red(), c.green(), c.blue()) for c in (QColor(img.pixel(x, y)) for y in range(img.height()) for x in range(img.width()))]
    bg = max(set(px), key=px.count)
    best = max(contrast(p, bg) for p in px)
    check(f"B7 tema {theme.THEME}: sulla riga selezionata dei livelli il testo si legge (contrasto ≥ 4,5)", best >= 4.5,
          f"contrasto {best:.2f}, sfondo {bg}")
    check("B7 stessa regola per elenchi e alberi (libreria materiali)",
          "QTreeWidget::item:selected, QListWidget::item:selected" in style.QSS_EXTRA
          and f"color: {theme.C['text']}" in style.QSS_EXTRA.split("QTreeWidget::item:selected, QListWidget::item:selected")[1][:90])

if MODE == "chiaro":  # il resto non dipende dal tema: basta la prova nel tema scuro
    code_ = 0 if all(results) else 1
    print(f"\n{sum(results)}/{len(results)} superati")
    from _uscita import esci  # noqa: E402

    esci(code_)

# ============================================================================================ A3 · ordine dei tagli
def old_order(polys, start=(0.0, 0.0), inner_first=True, optimize=True):
    """L'ordinamento com'era fino alla 0.19.1 (senza il limite dei 3000): il riferimento per «uguale a prima»."""
    n = len(polys)
    if n == 0 or not optimize:
        return polys
    children = [[] for _ in range(n)]
    if inner_first:
        for i, inner in enumerate(polys):
            for j, outer in enumerate(polys):
                if i != j and outer.closed and abs(outer.area()) > abs(inner.area()) and geom.contains(outer, inner):
                    children[j].append(i)
    remaining = [len(c) for c in children]
    parents = [[] for _ in range(n)]
    for j, cs in enumerate(children):
        for i in cs:
            parents[i].append(j)
    done = np.zeros(n, bool)
    reps = np.array([[p.pts[0][0], p.pts[0][1]] if not p.closed else
                     [sum(q[0] for q in p.pts) / len(p.pts), sum(q[1] for q in p.pts) / len(p.pts)] for p in polys])
    ends = np.array([[p.pts[-1][0], p.pts[-1][1]] for p in polys])
    cur = np.array(start, float)
    out = []
    for _ in range(n):
        avail = (~done) & (np.array(remaining) == 0)
        if not avail.any():
            avail = ~done
        idx = np.nonzero(avail)[0]
        d1 = np.hypot(reps[idx, 0] - cur[0], reps[idx, 1] - cur[1])
        d2 = np.hypot(ends[idx, 0] - cur[0], ends[idx, 1] - cur[1])
        k = int(idx[int(np.argmin(np.minimum(d1, d2)))])
        p = polys[k]
        if p.closed:
            pts = np.array(p.pts)
            vi = int(np.argmin(np.hypot(pts[:, 0] - cur[0], pts[:, 1] - cur[1])))
            p = geom.Poly(p.pts[vi:] + p.pts[:vi], True)
            last = p.pts[0]
        else:
            if math.dist(p.pts[-1], tuple(cur)) < math.dist(p.pts[0], tuple(cur)):
                p = p.reversed()
            last = p.pts[-1]
        out.append(p)
        done[k] = True
        for par in parents[k]:
            remaining[par] -= 1
        cur = np.array(last, float)
    return out


def old_depths(polys):
    n = len(polys)
    depth = [0] * n
    boxes = [p.bounds() if p.closed else None for p in polys]
    for i, inner in enumerate(polys):
        bi = inner.bounds()
        for j, outer in enumerate(polys):
            if i == j or not outer.closed:
                continue
            bo = boxes[j]
            if bi[0] < bo[0] or bi[1] < bo[1] or bi[2] > bo[2] or bi[3] > bo[3]:
                continue
            if abs(outer.area()) <= abs(inner.area()) and inner.closed:
                continue
            if geom.contains(outer, inner):
                depth[i] += 1
    return depth


def scene(rng, n):
    """Rettangoli con fori (anche fori dentro fori), poligoni nei due versi, linee aperte, pezzi sovrapposti."""
    out = []
    for _ in range(n):
        kind = rng.random()
        x, y = rng.uniform(0, 400), rng.uniform(0, 400)
        if kind < 0.5:
            a, b = rng.uniform(4, 60), rng.uniform(4, 60)
            out.append(([(x, y), (x + a, y), (x + a, y + b), (x, y + b)], True))
            if rng.random() < 0.6:
                out.append(([(x + a * .2, y + b * .2), (x + a * .5, y + b * .2), (x + a * .5, y + b * .6), (x + a * .2, y + b * .6)], True))
            if rng.random() < 0.3:
                out.append(([(x + a * .25, y + b * .25), (x + a * .4, y + b * .25), (x + a * .4, y + b * .5)], True))
        elif kind < 0.8:
            r, k = rng.uniform(2, 30), rng.randint(3, 24)
            p = [(x + r * math.cos(2 * math.pi * i / k), y + r * math.sin(2 * math.pi * i / k)) for i in range(k)]
            out.append((p[::-1] if rng.random() < .5 else p, True))
        else:
            out.append(([(x, y), (x + rng.uniform(-40, 40), y + rng.uniform(-40, 40)), (x + 5, y + 9)], False))
    rng.shuffle(out)
    return out


def polys_of(sc):
    return [geom.Poly(list(p), c) for p, c in sc]


def same(a, b):
    return [(p.pts, p.closed) for p in a] == [(p.pts, p.closed) for p in b]


for seed, n in ((1, 1), (2, 2), (3, 6), (4, 60), (5, 400)):
    sc = scene(random.Random(seed), n)
    for inner in (True, False):
        check(f"A3 {len(sc)} tracciati, fori prima {'sì' if inner else 'no'}: stesso ordine di prima",
              same(gcode.order_polys(polys_of(sc), (3.0, 7.0), inner, True), old_order(polys_of(sc), (3.0, 7.0), inner, True)))
    check(f"A3 {len(sc)} tracciati: stesse profondità di annidamento di prima",
          gcode._depths(polys_of(sc)) == old_depths(polys_of(sc)))
# forme doppie (stessa area, una sopra l'altra): capita con i disegni importati; nessuna è «dentro» l'altra
sc2 = scene(random.Random(11), 120)
sc2 = sc2 + sc2[:40]
random.Random(12).shuffle(sc2)
check(f"A3 {len(sc2)} tracciati con 40 forme doppie sovrapposte: stesso ordine e stesse profondità di prima",
      same(gcode.order_polys(polys_of(sc2), (0.0, 0.0), True, True), old_order(polys_of(sc2), (0.0, 0.0), True, True))
      and gcode._depths(polys_of(sc2)) == old_depths(polys_of(sc2)))
check("A3 nessun tracciato e ottimizzazione spenta: come prima",
      gcode.order_polys([], (0, 0)) == [] and same(gcode.order_polys(polys_of(sc), (0, 0), True, False), polys_of(sc)))
# oltre i 3000 tracciati: prima il controllo veniva saltato in silenzio
N_BIG = 3200
big = []
for i in range(N_BIG // 2):
    x, y = (i % 40) * 11.0, (i // 40) * 11.0
    big.append(([(x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)], True))
    big.append(([(x + 3, y + 3), (x + 7, y + 3), (x + 7, y + 7), (x + 3, y + 7)], True))
random.Random(3).shuffle(big)
t = time.perf_counter()
ordered = gcode.order_polys(polys_of(big), (0.0, 0.0), True, True)
took = time.perf_counter() - t
pos = {(round(p.bounds()[0], 3), round(p.bounds()[1], 3), round(abs(p.area()), 3)): k for k, p in enumerate(ordered)}
late = 0
for i in range(N_BIG // 2):
    x, y = (i % 40) * 11.0, (i // 40) * 11.0
    late += pos[(x + 3, y + 3, 16.0)] > pos[(x, y, 100.0)]
check(f"A3 {N_BIG} tracciati (oltre il vecchio limite di 3000): ogni foro viene tagliato prima del suo contorno",
      len(ordered) == N_BIG and late == 0, f"{late} fori dopo il contorno")
check(f"A3 {N_BIG} tracciati ordinati in un tempo ragionevole (prima: decine di secondi)", took < 12.0, f"{took:.1f} s")
d = gcode._depths(polys_of(big))
check(f"A3 {N_BIG} contorni: i fori hanno profondità 1 (prima, oltre i 3000, sempre 0: kerf dalla parte sbagliata)",
      sorted(set(d)) == [0, 1] and d.count(1) == N_BIG // 2)
t = time.perf_counter()
sc = scene(random.Random(8), 1300)
gcode.order_polys(polys_of(sc), (0.0, 0.0), True, True)
took = time.perf_counter() - t
check(f"A3 {len(sc)} tracciati annidati: meno di 3 secondi (prima circa 10)", took < 3.0, f"{took:.2f} s")

# ============================================================================================ A4 · calcoli lunghi
many = [at(RectShape(8, 6, layer=1 + i % 3), 5 + (i % 30) * 14, 5 + (i // 30) * 12) for i in range(450)]
ed.add(many, select=False)
spin()
check("A4 nelle prove automatiche il calcolo gira come ha sempre fatto (nessun tick)", busy.start(w, "x") is None)
ref = gcode.generate(ed.doc, w.profile, w.job_options())
os.environ["FLC_BUSY"] = "1"
os.environ["FLC_BUSY_DELAY"] = "0"
step0, busy.STEP = busy.STEP, 0.0
orig_tick = busy.Busy.tick
seen = {"ticks": 0, "dialog": 0, "modal": 0}


def spy(self):
    orig_tick(self)
    seen["ticks"] = self.ticks
    if self.dialog is not None and self.dialog.isVisible():
        seen["dialog"] += 1
        seen["modal"] += self.dialog.windowModality() == Qt.ApplicationModal


busy.Busy.tick = spy
job = w.build_job(show=False)
check("A4 con i segni di vita il lavoro preparato è identico, riga per riga", job is not None and job.lines == ref.lines)
check("A4 durante il calcolo la finestra riceve tempo e compare «Preparo il lavoro…» con Annulla",
      seen["ticks"] > 5 and seen["dialog"] > 0 and seen["modal"] == seen["dialog"], str(seen))
left = [d_ for d_ in w.findChildren(QProgressDialog) if d_.objectName() == "busyDialog" and d_.isVisible()]
check("A4 finito il calcolo: finestrella chiusa, cursore normale, nessun calcolo «in corso»",
      not left and QApplication.overrideCursor() is None and busy.Busy.active == 0)
kept = w.job


def cancel_soon(self):
    if self.ticks >= 3:
        self.cancelled = True
    orig_tick(self)


busy.Busy.tick = cancel_soon
r = w.build_job(show=False)
check("A4 Annulla interrompe la preparazione", r is None)
check("A4 dopo l'annullamento il lavoro di prima resta com'era", w.job is kept)
check("A4 dopo l'annullamento: cursore normale, niente finestrella, nessun calcolo «in corso»",
      QApplication.overrideCursor() is None and busy.Busy.active == 0
      and not [d_ for d_ in w.findChildren(QProgressDialog) if d_.objectName() == "busyDialog" and d_.isVisible()])
check("A4 il generatore non conserva il tick dopo un annullamento", gcode._TICK is None)
busy.Busy.tick = orig_tick
r = w.build_job(show=False)
check("A4 dopo un annullamento si può preparare di nuovo, con lo stesso risultato", r is not None and r.lines == ref.lines)
outer_busy = busy.Busy(w, "fuori")
check("A4 un calcolo lungo dentro un altro non apre una seconda finestrella", busy.start(w, "dentro") is None)
outer_busy.close()
check("A4 … e alla fine il conto torna a zero", busy.Busy.active == 0 and busy.start(w, "dopo") is not None)
busy.Busy.active = 0
busy.STEP = step0
os.environ.pop("FLC_BUSY", None)
os.environ.pop("FLC_BUSY_DELAY", None)
ed.select(many)
ed.delete()
spin()

# ============================================================================================ B3 · materiali
base = materials.builtin()
cut = next(m for m in base if m.operation == "taglio" and m.power == 100)
eng = next(m for m in base if m.operation == "incisione" and m.power < 60)
check("B3 senza rapporto (o con rapporto 1) le voci restano identiche",
      materials.scaled(cut, None) is cut and materials.scaled(cut, 1.0) is cut and materials.scaled(eng, 1.02) is eng)


def energy(m):
    return m.power * m.passes / m.speed


for ratio, name in ((0.25, "un quarto della potenza"), (0.5, "metà potenza"), (2.0, "il doppio della potenza")):
    for m in (cut, eng):
        s = materials.scaled(m, ratio)
        rel = energy(s) * ratio / energy(m)
        check(f"B3 {name}, {m.operation}: stessa energia per millimetro (entro l'arrotondamento)", 0.9 <= rel <= 1.12,
              f"{m.power}%/{m.speed} → {s.power}%/{s.speed}×{s.passes}: {rel:.3f}")
        check(f"B3 {name}, {m.operation}: potenza fra 1 e 100%, velocità mai sotto {materials.MIN_SPEED:g} mm/min",
              1 <= s.power <= 100 and s.speed >= min(m.speed, materials.MIN_SPEED), f"{s.power}% {s.speed}")
weak = materials.scaled(cut, 0.25)
check("B3 laser più debole, taglio già al 100%: resta 100% e rallenta", weak.power == 100 and weak.speed < cut.speed)
strong = materials.scaled(cut, 2.0)
check("B3 laser più forte: stessa velocità, meno potenza", strong.speed == cut.speed and strong.power == 50)
slow = materials.scaled(materials.Material("x", "taglio", 3, 100, 200, 2), 0.1)
check("B3 troppo lento per rallentare ancora: velocità minima e più passate",
      slow.speed == materials.MIN_SPEED and slow.passes > 2 and 0.9 <= energy(slow) * 0.1 / (100 * 2 / 200) <= 1.12,
      f"{slow.speed} ×{slow.passes}")
check("B3 la voce di partenza non viene toccata (la stima è una copia)", cut.power == 100 and cut.passes >= 1
      and materials.builtin()[base.index(cut)] == cut)
mine = materials.Material("Legno mio", "incisione", 0, 33, 1234, 1)
materials.save_user([mine])
lib = materials.library(0.25)
check("B3 nella libreria adattata le voci dell'utente restano come le ha salvate",
      lib[0] == mine and any(m != b for m, b in zip(lib[1:], materials.library()[1:])))
materials.save_user([])
prof = w.profile
keep = (prof.name, prof.optical_power)
check("B3 con il Longer B1 40W (la macchina della tabella) niente adattamento", w.material_reference()
      and w.material_ratio() is None and w.material_watts() is None)
prof.name, prof.optical_power = "Prova 10 W", "10 W"
check("B3 profilo con una potenza sola («10 W»): si usa quella", w.material_watts() == 10 and not w.material_reference()
      and abs(w.material_ratio() - 10 / 48) < 1e-9, str(w.material_watts()))
prof.name, prof.optical_power = "Prova / forbice", "20–40 W"
check("B3 profilo con una forbice («20–40 W»): niente adattamento finché l'utente non dice la sua potenza",
      w.material_watts() is None and w.material_ratio() is None)
w.set_material_watts(20)
check("B3 la potenza scritta dall'utente vale e si ricorda per quella macchina", w.material_watts() == 20
      and abs(w.material_ratio() - 20 / 48) < 1e-9)
from freelasercut.ui.dialogs_materials import MaterialLibraryDialog  # noqa: E402

md = MaterialLibraryDialog(None, w)
md.show()
spin()
shown = [md.tree.topLevelItem(i).child(j).data(0, Qt.UserRole) for i in range(md.tree.topLevelItemCount())
         for j in range(md.tree.topLevelItem(i).childCount())]
check("B3 finestra Libreria: con un altro laser compare la riga della potenza, già compilata",
      md.watts_row.isVisibleTo(md) and md.e_watts.value() == 20 and "20" in md.watts_note.text())
by_key = {m.key(): m for m in base}
check("B3 finestra Libreria: stesse voci, valori adattati alla potenza scritta",
      {s.key() for s in shown} == set(by_key) and all(s == materials.scaled(by_key[s.key()], 20 / 48) for s in shown)
      and any(s != by_key[s.key()] for s in shown))
md.e_watts.setValue(0)
spin()
shown0 = [md.tree.topLevelItem(i).child(j).data(0, Qt.UserRole) for i in range(md.tree.topLevelItemCount())
          for j in range(md.tree.topLevelItem(i).childCount())]
check("B3 potenza «non indicata»: tornano i valori della tabella",
      len(shown0) == len(base) and all(s == by_key[s.key()] for s in shown0) and w.material_ratio() is None)
md.close()
prof.name, prof.optical_power = keep
md = MaterialLibraryDialog(None, w)
check("B3 con il B1 40W la riga della potenza non c'è e i valori sono quelli di sempre",
      not md.watts_row.isVisibleTo(md) and md.ratio() is None)
md.close()
check("B3 anche l'assistente (comandi remoti) vede i valori adattati alla macchina attiva",
      w.remote is None or w.remote._material_ratio() is None)

# ============================================================================================ C1 · anteprime
def rel_json(ver, pre=False, draft=False, tag=None):
    tag = tag or ("v" + ver + ("-pre" if pre else ""))
    pfx = updater.DOWNLOAD_PREFIX + tag + "/"
    return {"tag_name": tag, "name": "FreeLaserCut " + ver, "body": "note", "draft": draft, "prerelease": pre,
            "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
            "assets": [{"name": f"FreeLaserCut-{ver}-Setup.exe", "browser_download_url": pfx + f"FreeLaserCut-{ver}-Setup.exe",
                        "size": 1000}, {"name": "SHA256SUMS.txt", "browser_download_url": pfx + "SHA256SUMS.txt", "size": 80}]}


check("C1 una versione in anteprima non è mai proposta a chi non l'ha chiesta",
      updater.parse_release(rel_json("9.9.9", pre=True)) is None)
stable = updater.parse_release(rel_json("9.9.8"))
check("C1 le versioni stabili arrivano come prima", stable is not None and stable.version == "9.9.8" and not stable.prerelease)
pre = updater.parse_release(rel_json("9.9.9", pre=True), allow_pre=True)
check("C1 il tag vX.Y.Z-pre è letto come versione X.Y.Z in anteprima, con il suo installatore",
      pre is not None and pre.version == "9.9.9" and pre.prerelease and pre.setup_url.endswith("v9.9.9-pre/FreeLaserCut-9.9.9-Setup.exe"))
listing = [rel_json("9.9.9", pre=True), rel_json("9.9.8"), rel_json("9.9.10", draft=True), rel_json("9.9.7", pre=True)]
best = updater.newest(listing)
check("C1 chi ha chiesto le anteprime riceve il numero più alto fra stabili e anteprime (mai le bozze)",
      best is not None and best.version == "9.9.9" and best.prerelease)
check("C1 dall'elenco, senza anteprime, si prende l'ultima stabile", updater.newest(listing, allow_pre=False).version == "9.9.8")
check("C1 a parità di numero vince la stabile",
      not updater.newest([rel_json("9.9.9", pre=True), rel_json("9.9.9")]).prerelease)
check("C1 elenco vuoto o risposta strana: nessuna versione, nessun errore",
      updater.newest([]) is None and updater.newest({"message": "x"}) is None and updater.newest([1, "a", None]) is None)
check("C1 gli indirizzi: «latest» per le stabili (come prima), l'elenco per le anteprime",
      updater.API_LATEST.endswith("/releases/latest") and "/releases?" in updater.API_RECENT)
up = w.updates
check("C1 di partenza le anteprime sono spente", not up.preview() and not w.acts["update_preview"].isChecked())
w.acts["update_preview"].trigger()
spin()
check("C1 la spunta di Aiuto accende le anteprime e si ricorda", up.preview() and w.qs.value("update_preview") == "true")
calls = []
real_async = updater.check_async
updater.check_async = lambda cb, timeout=10.0, **kw: calls.append(kw)
up.busy = False
mode0, up.mode = up.mode, "installer"
up.check(manual=False)
check("C1 con le anteprime accese il controllo le chiede", calls == [{"preview": True}], str(calls))
up.set_preview(False)
up.busy = False
up.check(manual=False)
check("C1 con le anteprime spente il controllo è quello di sempre", calls[-1] == {} and not w.acts["update_preview"].isChecked(),
      str(calls))
updater.check_async = real_async
up.busy = False
up.mode = mode0
wf = os.path.join(ROOT, ".github", "workflows", "installatore.yml")
text = open(wf, encoding="utf-8").read() if os.path.exists(wf) else ""
if "-pre" in text:  # il file di GitHub si aggiorna a mano (è protetto): finché è quello di prima non c'è niente da provare
    check("C1 su GitHub: il tag vX.Y.Z-pre è accettato e pubblica una pre-release, quello normale una versione per tutti",
          '"$GITHUB_REF_NAME" != "v$ver-pre"' in text and 'PRE="--prerelease=false"' in text
          and 'if [[ "$GITHUB_REF_NAME" == *-pre ]]; then PRE="--prerelease"' in text and text.count("$PRE") == 2)
else:
    print("--  C1 il file di GitHub (installatore.yml) non ha ancora la regola dei tag «-pre»: le anteprime si potranno "
          "pubblicare dopo averlo aggiornato")

# ============================================================================================ C2 · app.py
check("C2 la finestra della versione 0.1 non è più in app.py; i pannelli e gli aiuti che servono sì",
      not hasattr(flc_app, "MainWindow") and not hasattr(flc_app, "ControlPanel")
      and all(hasattr(flc_app, n) for n in ("MachinePanel", "ConsolePanel", "card", "muted", "_install_crash_log",
                                            "start_hang_watch", "finish_exit", "_main")))

# ============================================================================================ C3 · errori ignorati
from freelasercut.profile import config_dir  # noqa: E402

ign = os.path.join(config_dir(), diag.IGNORED_LOG)
if os.path.exists(ign):
    os.remove(ign)
diag._ignored_seen.clear()


def boom(where, n=1):
    for _ in range(n):
        try:
            raise ValueError("valore sbagliato in " + os.path.join(os.path.expanduser("~"), "file.txt"))
        except Exception:  # noqa: BLE001
            diag.ignored(where)


boom("prova uno", 5)
lines = open(ign, encoding="utf-8").read().splitlines() if os.path.exists(ign) else []
check("C3 un errore ignorato lascia una riga, una sola anche se si ripete", len(lines) == 1 and "[prova uno]" in lines[0]
      and "ValueError" in lines[0] and "test_v192_analisi.py:" in lines[0], str(lines))
check("C3 nella riga la cartella dell'utente (che contiene il suo nome) diventa «~»",
      lines and os.path.expanduser("~") not in lines[0] and "file.txt" in lines[0])
try:
    raise KeyError("altro")
except Exception:  # noqa: BLE001
    diag.ignored("prova due")
lines = open(ign, encoding="utf-8").read().splitlines()
check("C3 un altro punto del programma ha la sua riga", len(lines) == 2 and "[prova due]" in lines[1])
diag.ignored("fuori da un errore")
check("C3 chiamata fuori da un errore: non fa niente e non si rompe", len(open(ign, encoding="utf-8").read().splitlines()) == 2)
check("C3 «l'ultimo errore del programma» del rapporto resta quello vero (il registro è un file a parte)",
      "prova" not in diag.last_error_text() and "altro" not in diag.last_error_text())
zp = os.path.join(tempfile.mkdtemp(), "rapporto.zip")
inside = diag.make_report(zp, win=None)
check("C3 il registro degli errori ignorati entra nel rapporto per l'assistenza", diag.IGNORED_LOG in inside, str(inside))
src_auto = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
check("C3 il salvataggio automatico che non riesce ora lascia traccia", '_diag.ignored("salvataggio automatico")' in src_auto)

# ============================================================================================ C4 · indice
sys.path.insert(0, os.path.join(ROOT, "tests"))
appdata = os.environ["APPDATA"]
import run_tests as rt  # noqa: E402

os.environ["APPDATA"] = appdata
suites = rt.suite_list()
files = sorted(f for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("test_") and f.endswith(".py"))
listed = {f for f, _l, _a in suites}
check("C4 ogni file di prova è nell'elenco del lanciatore (nessuna prova dimenticata)", set(files) <= listed,
      str(sorted(set(files) - listed)))
text = rt.index_text()
check("C4 l'indice per area nomina tutte le suite", all(f"`{f}`" in text for f in listed) and text.count("\n- `") == len(suites))
check("C4 poche suite finiscono in «Altro»", text.split("## Altro")[1].count("\n- `") <= 6 if "## Altro" in text else True)
idx = os.path.join(ROOT, "tests", "INDICE.md")
check("C4 tests/INDICE.md è quello generato (si rigenera a ogni lancio delle prove)",
      os.path.exists(idx) and open(idx, encoding="utf-8").read() == text)

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
from _uscita import esci  # noqa: E402

esci(code_)
