# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Stampa e taglia (0.18.5; per tutti dalla 0.19.5, prima era fra le funzioni in prova).

Tre passi, nella stessa finestra che resta aperta accanto al piano:
1. prepara: immagine da stampare a colori (facoltativa) e le due crocette;
2. stampa: il PDF al 100% con disegno e crocette;
3. allinea: foglio sul piano, testa sulle due crocette con frecce o joystick e Puntino/Lucciola (gli stessi comandi
   della scheda Movimento, jogpad.py), e il disegno va sopra il foglio vero.
Poi si avvia il lavoro come sempre (coordinate assolute): si tagliano solo i livelli con l'uscita accesa.
La matematica e la stampa sono in core/print_cut.py.
"""
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import io_formats
from ..core import print_cut as pc
from freelasercut.i18n import tr  # noqa: E402



class PrintCutDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main, self.ed, self.ctl = main, main.editor, main.ctl
        self.pts = [None, None]  # punti presi con la testa (coordinate del piano)
        self.last_info = None  # esito dell'ultimo allineamento
        self.setWindowTitle(tr("Stampa e taglia"))
        self.setMinimumWidth(470)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Per tagliare attorno a qualcosa di già stampato (adesivi, etichette, cartoncino).<br>"
                          "<b>Si stampa</b> quello che sta sui livelli con l'uscita spenta, crocette comprese. "
                          "<b>Si taglia</b> quello che ha l'uscita accesa."))
        intro.setWordWrap(True)
        v.addWidget(intro)

        # ---- 1. prepara
        g1 = QGroupBox(tr("1 · Prepara il disegno"))
        l1 = QVBoxLayout(g1)
        self.b_image = QPushButton(tr("Aggiungi un'immagine da stampare a colori…"))
        self.b_image.setToolTip(tr("L'importazione normale porta le foto in grigi, perché il laser incide solo quelli. "
                                   "Da qui l'immagine resta a colori e va su un livello che il laser non tocca."))
        self.b_image.clicked.connect(lambda: self.add_image())
        self.b_marks = QPushButton(tr("Metti le due crocette"))
        self.b_marks.setToolTip(tr("Due crocette fuori dal disegno, in alto a sinistra (un cerchio) e in basso a destra "
                                   "(due cerchi). Se ci sono già, le rimette attorno al disegno di adesso."))
        self.b_marks.clicked.connect(lambda: self.add_marks())
        self.l_marks = QLabel("")
        self.l_marks.setWordWrap(True)
        for w in (self.b_image, self.b_marks, self.l_marks):
            l1.addWidget(w)
        v.addWidget(g1)

        # ---- 2. stampa
        g2 = QGroupBox(tr("2 · Stampa"))
        l2 = QVBoxLayout(g2)
        row = QHBoxLayout()
        self.page = QComboBox()
        for name in pc.PAGES:
            self.page.addItem(name, name)
        self.b_pdf = QPushButton(tr("Salva il PDF da stampare…"))
        self.b_pdf.clicked.connect(lambda: self.save_pdf())
        row.addWidget(QLabel(tr("Foglio")))
        row.addWidget(self.page)
        row.addWidget(self.b_pdf, 1)
        l2.addLayout(row)
        tip = QLabel(tr("Stampa il PDF al <b>100%</b> («dimensioni reali»), senza «adatta alla pagina»."))
        tip.setWordWrap(True)
        l2.addWidget(tip)
        v.addWidget(g2)

        # ---- 3. allinea
        g3 = QGroupBox(tr("3 · Allinea il disegno al foglio"))
        l3 = QVBoxLayout(g3)
        how = QLabel(tr("Fissa il foglio sul piano (anche un po' storto), fai l'homing, poi porta la testa sul centro "
                        "di ogni crocetta con le frecce (o il joystick) e il Puntino o la Lucciola."))
        how.setWordWrap(True)
        l3.addWidget(how)
        # 0.19.5: lo stesso sistema della scheda Movimento (frecce con passi, Puntino e Lucciola al centro, joystick)
        from .jogpad import JogPad

        self.pad = JogPad(self.ctl, main.qs, lambda: main.profile, main.canvas.head_pos, main.move.feed.value)
        self.pad.attach_laser(main.laser)
        self.jog_btns = self.pad.jog_buttons
        self.l_pos = QLabel("")
        self.l_pos.setWordWrap(True)
        jr = QHBoxLayout()
        jr.addWidget(self.pad, 0)
        jr.addSpacing(12)
        jr.addWidget(self.l_pos, 1)
        l3.addLayout(jr)
        self.b_take, self.l_take, self.b_cam = [], [], []
        for i, txt in enumerate((tr("La testa è sulla crocetta 1 (un cerchio)"),
                                 tr("La testa è sulla crocetta 2 (due cerchi)"))):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, i=i: self.take(i + 1))
            # 0.20.2 (Leone, 15/11): con la camera della testa calibrata la crocetta si prende dal mirino, senza dover
            # prima portare il laser sul centro della camera
            bc = QPushButton(tr("◎ Dal centro camera"))
            bc.setToolTip(tr("Il centro della crocetta è il punto sotto il mirino della camera della testa (serve la "
                             "camera calibrata)"))
            bc.clicked.connect(lambda _=False, i=i: self.take_from_camera(i + 1))
            lab = QLabel("—")
            r = QHBoxLayout()
            r.addWidget(b, 1)
            r.addWidget(bc)
            r.addWidget(lab)
            l3.addLayout(r)
            self.b_take.append(b)
            self.b_cam.append(bc)
            self.l_take.append(lab)
        self.l_cam = QLabel(tr("Con la camera della testa: porta il mirino sul centro della crocetta (Laser → Vista della "
                               "testa…, un clic sul video) e premi «Dal centro camera»."))
        self.l_cam.setWordWrap(True)
        l3.addWidget(self.l_cam)
        self.scale = QCheckBox(tr("Correggi anche la scala della stampa"))
        self.scale.setChecked(True)
        self.scale.setToolTip(tr("Le stampanti sbagliano spesso le misure di qualche decimo di millimetro: con la "
                                 "spunta il taglio segue la stampa vera. Senza, le misure restano quelle del disegno."))
        l3.addWidget(self.scale)
        self.b_align = QPushButton(tr("Allinea il disegno al foglio"))
        self.b_align.clicked.connect(lambda: self.align())
        l3.addWidget(self.b_align)
        v.addWidget(g3)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.close)
        v.addWidget(close)

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.ed.changed.connect(self.refresh)
        self.refresh()
        # le scritte che vanno a capo ingannano il calcolo dell'altezza: senza questo le frecce restano schiacciate
        self.resize(self.minimumWidth(), max(self.sizeHint().height(), self.layout().heightForWidth(self.minimumWidth())) + 16)

    # ------------------------------------------------------------------ stato
    def say(self, text, bad=False):
        self.msg.setText(("⚠ " if bad else "") + text)
        return not bad

    def head(self):
        p = self.main.canvas.head_pos() if self.ctl.connected else None
        return None if p is None else (p.x(), p.y())

    def machine_ready(self):
        """None se si può prendere un punto, altrimenti il motivo."""
        if not self.ctl.connected:
            return tr("Collega il laser.")
        if self.ctl.job_active or self.ctl.checking:
            return tr("C'è un lavoro in corso.")
        if self.main.profile.homing and not self.ctl.homed:
            return tr("Fai prima l'homing: serve perché la posizione della testa sia quella vera del piano.")
        if self.ctl.last_status.get("state") != "Idle":
            return tr("Aspetta che la testa sia ferma (stato: {0}).", self.ctl.last_status.get("state", "?"))
        if self.head() is None:
            return tr("Non conosco ancora la posizione della testa.")
        return None

    def refresh(self):
        doc = self.ed.doc
        m1, m2 = pc.find_marks(doc)
        have = m1 is not None and m2 is not None
        if have:
            (x1, y1), (x2, y2) = pc.mark_center(m1), pc.mark_center(m2)
            import math

            self.l_marks.setText(tr("Crocette sul disegno: distanza {0:.1f} mm.", math.hypot(x2 - x1, y2 - y1)))
        else:
            self.l_marks.setText(tr("Le crocette non ci sono ancora."))
        self.b_pdf.setEnabled(have)
        why = self.machine_ready()
        moving_ok = self.ctl.connected and not (self.ctl.job_active or self.ctl.checking)
        self.pad.set_connected(moving_ok)
        for b in self.b_take:
            b.setEnabled(have and why is None)
            b.setToolTip(why or "")
        cam_why = self.camera_ready()
        for b in self.b_cam:
            b.setVisible(cam_why != "none")
            b.setEnabled(have and why is None and cam_why is None)
            b.setObjectName("primary" if cam_why is None else "")
        self.l_cam.setVisible(cam_why is None)
        h = self.head()
        self.l_pos.setText(tr("Testa: X {0:.2f}  Y {1:.2f}", round(h[0], 2) + 0.0, round(h[1], 2) + 0.0) if h else (why or ""))
        for i in (0, 1):
            p = self.pts[i]
            self.l_take[i].setText("—" if p is None else f"X {p[0]:.2f}  Y {p[1]:.2f}")
        self.b_align.setEnabled(have and all(p is not None for p in self.pts))

    # ------------------------------------------------------------------ 1. prepara
    def add_image(self, path=None):
        if path is None:
            exts = " ".join("*" + e for e in io_formats.IMAGE_EXT)
            path, _ = QFileDialog.getOpenFileName(self, tr("Immagine da stampare"), self.main.qs.value("last_dir", ""),
                                                  tr("Immagini ({0})", exts))
            if not path:
                return None
        doc = self.ed.doc
        made = []

        def do():
            made[:] = pc.import_print_image(doc, path)
            b = pc.design_bounds(doc)
            s = made[0]
            # accanto a quello che c'è già, oppure a 20 mm dall'angolo del piano
            x = 20.0 if b.isNull() else b.left()
            y = 20.0 if b.isNull() else b.bottom() + 10.0
            sb = s.bounds()
            from PySide6.QtGui import QTransform

            s.apply(QTransform.fromTranslate(x - sb.left(), y - sb.top()))
            doc.add(s)
            self.ed.selection = [s]

        try:
            self.ed.run(tr("Immagine da stampare"), do)
        except (pc.PrintCutError, OSError, ValueError) as exc:
            self.say(tr("Non riesco ad aprire {0}: {1}", os.path.basename(path), exc), True)
            return None
        self.ed.selection_changed.emit()
        self.say(tr("Immagine aggiunta sul livello «{0}» (a colori, il laser non la tocca). Mettila dove vuoi, disegna "
                    "attorno le linee di taglio su un livello normale, poi metti le crocette.",
                    doc.layer(made[0].layer).label()))
        return made[0]

    def add_marks(self):
        doc = self.ed.doc
        b = pc.design_bounds(doc)
        if b.isNull():
            return self.say(tr("Il piano è vuoto: prima metti il disegno, poi le crocette."), True)
        made = []

        def do():
            old = [m for m in pc.find_marks(doc) if m is not None]
            layer = old[0].layer if old else pc.print_layer(doc, tr("Crocette"))
            if layer is None:
                raise pc.PrintCutError(tr("Non ci sono più livelli liberi per le crocette."))
            doc.layer(layer).output = False
            if old:
                doc.remove(old)
                self.ed.selection = [s for s in self.ed.selection if s not in old]
            (x1, y1), (x2, y2) = pc.mark_positions(b)
            for n, x, y in ((1, x1, y1), (2, x2, y2)):
                m = pc.make_mark(n, x, y, layer)
                doc.add(m)
                made.append(m)

        try:
            self.ed.run(tr("Crocette di Stampa e taglia"), do)
        except pc.PrintCutError as exc:
            return self.say(str(exc), True)
        self.ed.selection_changed.emit()
        self.pts = [None, None]
        pb = pc.print_bounds(doc)
        note = ""
        if pc.page_fit(pb, self.page.currentData()) is None:
            note = " " + tr("Attenzione: con le crocette il disegno misura {0:.0f} × {1:.0f} mm e non entra in un "
                            "foglio {2}.", pb.width(), pb.height(), self.page.currentData())
        self.say(tr("Crocette messe: la 1 (un cerchio) in alto a sinistra, la 2 (due cerchi) in basso a destra. Puoi "
                    "spostarle, ma tienile lontane fra loro.") + note, bool(note))
        self.refresh()
        return made

    # ------------------------------------------------------------------ 2. stampa
    def save_pdf(self, path=None):
        doc = self.ed.doc
        if path is None:
            base = os.path.splitext(os.path.basename(doc.path or ""))[0] or tr("stampa-e-taglia")
            start = os.path.join(self.main.qs.value("last_dir", "") or "", base + ".pdf")
            path, _ = QFileDialog.getSaveFileName(self, tr("Salva il PDF da stampare"), start, "PDF (*.pdf)")
            if not path:
                return None
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
        try:
            info = pc.export_pdf(doc, path, self.page.currentData())
        except pc.PrintCutError as exc:
            self.say(str(exc), True)
            return None
        self.say(tr("PDF salvato ({0}, {1}). Stampalo al 100%, senza «adatta alla pagina»: {2}", info["page"],
                    tr("orizzontale") if info["landscape"] else tr("verticale"), path))
        return info

    # ------------------------------------------------------------------ 3. allinea
    def jog(self, dx, dy):
        """Un passo con le frecce (passo scelto nella fila, velocità del jog della scheda Movimento)."""
        if not self.ctl.connected or self.ctl.job_active or self.ctl.checking:
            return
        self.pad.jog_press(dx, dy)
        self.pad.jog_release()

    def lights_off(self):
        """Spegne Lucciola e joystick (dopo l'allineamento e alla chiusura)."""
        self.pad.joy.stop()
        if self.main.laser._glow_on:
            self.main.laser.glow_stop()

    def head_card(self):
        cam = getattr(self.main, "camera", None)
        return getattr(cam, "head", None)

    def camera_ready(self):
        """None se si può prendere la crocetta dal centro della camera della testa, "none" se non c'è una camera della
        testa, altrimenti il motivo."""
        card_ = self.head_card()
        if card_ is None or (card_.src is None and card_.model is None):
            return "none"
        if card_.src is None:
            return tr("Camera della testa non aperta")
        if not card_.ready():
            return tr("Calibra prima la camera della testa")
        return None

    def take_from_camera(self, number):
        """Crocetta presa dal punto sotto il mirino della camera della testa."""
        why = self.machine_ready()
        cam_why = self.camera_ready()
        if why or cam_why:
            return self.say(why or (cam_why if cam_why != "none" else tr("Nessuna camera della testa")), True)
        card_ = self.head_card()
        c = card_.model.center(self.head())
        return self.take(number, pos=(float(c[0]), float(c[1])))

    def take(self, number, pos=None):
        """Prende la posizione della testa come centro della crocetta 1 o 2 (pos: solo per le prove)."""
        if pos is None:
            why = self.machine_ready()
            if why:
                return self.say(why, True)
            pos = self.head()
        self.pts[number - 1] = (float(pos[0]), float(pos[1]))
        other = self.pts[2 - number]
        if other is None:
            self.say(tr("Crocetta {0} presa. Ora porta la testa sulla crocetta {1}.", number, 3 - number))
        else:
            self.say(tr("Crocette prese tutte e due: premi «Allinea il disegno al foglio»."))
        self.refresh()
        return True

    def align(self):
        doc = self.ed.doc
        m1, m2 = pc.find_marks(doc)
        if m1 is None or m2 is None:
            return self.say(tr("Mancano le due crocette sul disegno."), True)
        if any(p is None for p in self.pts):
            return self.say(tr("Prendi prima le due crocette con la testa."), True)
        try:
            tf, info = pc.fit(pc.mark_center(m1), pc.mark_center(m2), self.pts[0], self.pts[1], self.scale.isChecked())
        except pc.PrintCutError as exc:
            return self.say(str(exc), True)
        prof = self.main.profile
        after = pc.cut_bounds(doc, tf)
        if pc.outside_bed(after, (prof.bed_x, prof.bed_y)):
            return self.say(tr("Con il foglio in quella posizione il taglio uscirebbe dall'area di lavoro "
                               "({0:.0f} × {1:.0f} mm): sposta il foglio più dentro al piano e riprendi le crocette.",
                               prof.bed_x, prof.bed_y), True)
        self.lights_off()

        def do():
            for s in list(doc.shapes):  # tutto il piano insieme, anche le forme bloccate: stampa e taglio a registro
                s.apply(tf)

        self.ed.run(tr("Stampa e taglia: allinea al foglio"), do)
        self.pts = [None, None]
        self.last_info = info
        combo = self.main.laser.start_from
        i = combo.findData("absolute")
        if i >= 0 and combo.currentIndex() != i:
            combo.setCurrentIndex(i)
        text = tr("Disegno allineato al foglio: ruotato di {0:+.2f}°, distanza fra le crocette {1:.2f} mm sul foglio "
                  "contro {2:.2f} mm nel disegno ({3:+.2f}%).", info["angle"], info["measured"], info["drawn"],
                  (info["scale"] - 1.0) * 100.0)
        if not info["scaled"] and info["residual"] > 0.15:
            text += " " + tr("Senza correzione della scala restano {0:.2f} mm di differenza su ogni crocetta.",
                             info["residual"])
        if abs(info["angle"]) > 45.0:
            text += " " + tr("Il foglio risulta molto ruotato: se non è così, hai scambiato le due crocette "
                             "(Ctrl+Z e riprendile).")
        text += " " + tr("Ora controlla con Contorno e avvia il lavoro (coordinate assolute). Non muovere il foglio. "
                         "Ctrl+Z riporta il disegno com'era.")
        self.say(text)
        self.refresh()
        return info

    def closeEvent(self, ev):
        self._timer.stop()
        try:
            self.ed.changed.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        self.lights_off()
        super().closeEvent(ev)
