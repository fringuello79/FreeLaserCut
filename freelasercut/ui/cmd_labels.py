# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto → Mostra i nomi sotto i comandi: sotto ogni icona delle barre compare un nome corto, piccolo,
nella lingua scelta. Spento di partenza; la scelta si ricorda."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar, QToolButton


FONT_PX = 9  # appena leggibile su un monitor 1920 × 1080


LANGS = ("it", "en", "es", "fr", "pt")
# azione: nomi corti nelle lingue di FreeLaserCut (non passano da tr: lo stesso parola qui deve poter essere
# più corta che nei menu, dove c'è posto)
SHORT = {
    "new": ("Nuovo", "New", "Nuevo", "Nuevo", "Novo"),
    "open": ("Apri", "Open", "Abrir", "Ouvrir", "Abrir"),
    "save": ("Salva", "Save", "Guardar", "Enreg.", "Salvar"),
    "import": ("Importa", "Import", "Importar", "Importer", "Importar"),
    "undo": ("Annulla", "Undo", "Deshac.", "Annuler", "Desfazer"),
    "redo": ("Rifai", "Redo", "Rehacer", "Rétablir", "Refazer"),
    "cut": ("Taglia", "Cut", "Cortar", "Couper", "Recortar"),
    "copy": ("Copia", "Copy", "Copiar", "Copier", "Copiar"),
    "paste": ("Incolla", "Paste", "Pegar", "Coller", "Colar"),
    "delete": ("Elimina", "Delete", "Borrar", "Suppr.", "Excluir"),
    "duplicate": ("Duplica", "Duplicate", "Duplicar", "Dupliquer", "Duplicar"),
    "group": ("Gruppo", "Group", "Agrupar", "Grouper", "Agrupar"),
    "ungroup": ("Separa", "Ungroup", "Desagr.", "Dégroup.", "Desagr."),
    "weld": ("Fondi", "Weld", "Soldar", "Souder", "Soldar"),
    "union": ("Unione", "Union", "Unión", "Union", "União"),
    "difference": ("Sottrai", "Subtract", "Restar", "Soustr.", "Subtrair"),
    "intersection": ("Interseca", "Intersect", "Intersec.", "Intersec.", "Interseç."),
    "xor": ("Esclusione", "Exclude", "Excluir", "Exclure", "Excluir"),
    "flip_h": ("Rifletti↔", "Flip↔", "Espejo↔", "Miroir↔", "Espelho↔"),
    "flip_v": ("Rifletti↕", "Flip↕", "Espejo↕", "Miroir↕", "Espelho↕"),
    "rot_ccw": ("Ruota⟲", "Rotate⟲", "Girar⟲", "Rot.⟲", "Girar⟲"),
    "rot_cw": ("Ruota⟳", "Rotate⟳", "Girar⟳", "Rot.⟳", "Girar⟳"),
    "align_left": ("Sinistra", "Left", "Izq.", "Gauche", "Esq."),
    "align_hcenter": ("Centro↔", "Center↔", "Centro↔", "Centre↔", "Centro↔"),
    "align_right": ("Destra", "Right", "Der.", "Droite", "Dir."),
    "align_top": ("Alto", "Top", "Arriba", "Haut", "Topo"),
    "align_vcenter": ("Centro↕", "Center↕", "Centro↕", "Centre↕", "Centro↕"),
    "align_bottom": ("Basso", "Bottom", "Abajo", "Bas", "Base"),
    "align_center": ("Centra", "Center", "Centrar", "Centrer", "Centrar"),
    "dist_h": ("Distr.↔", "Distr.↔", "Distr.↔", "Rép.↔", "Distr.↔"),
    "dist_v": ("Distr.↕", "Distr.↕", "Distr.↕", "Rép.↕", "Distr.↕"),
    "nest": ("Nesting", "Nesting", "Nesting", "Nesting", "Nesting"),
    "offset": ("Offset", "Offset", "Offset", "Décal.", "Offset"),
    "grid_array": ("Griglia", "Grid", "Rejilla", "Grille", "Grade"),
    "circ_array": ("Cerchio", "Circular", "Circular", "Cercle", "Circular"),
    "along_path": ("Su tracciato", "On path", "En trazo", "Sur tracé", "No traço"),
    "to_path": ("Converti", "Convert", "Convertir", "Convertir", "Converter"),
    "zoom_in": ("Zoom+", "Zoom+", "Zoom+", "Zoom+", "Zoom+"),
    "zoom_out": ("Zoom−", "Zoom−", "Zoom−", "Zoom−", "Zoom−"),
    "fit": ("Adatta", "Fit", "Ajustar", "Ajuster", "Ajustar"),
    "fit_sel": ("Su selez.", "To sel.", "A selec.", "Sur sél.", "Na sel."),
    "preview": ("Anteprima", "Preview", "Vista", "Aperçu", "Prévia"),
    "trace": ("Vettori", "Trace", "Vector.", "Vector.", "Vetor."),
    "photo": ("Foto", "Photo", "Foto", "Photo", "Foto"),
    "exact_shape": ("Misure", "Exact", "Medidas", "Mesures", "Medidas"),
    "code": ("Codici", "Codes", "Códigos", "Codes", "Códigos"),
    "text_path": ("Testo curvo", "Curved text", "Texto curvo", "Texte courbe", "Texto curvo"),
    "variables": ("Variabili", "Variables", "Variables", "Variables", "Variáveis"),
    "materials": ("Materiali", "Materials", "Mater.", "Matér.", "Materiais"),
    "material_test": ("Test", "Test", "Prueba", "Test", "Teste"),
    "identify": ("Riconosci", "Identify", "Detectar", "Identif.", "Detectar"),
    "help_mode": ("Guida", "Help", "Ayuda", "Aide", "Ajuda"),
    "select": ("Seleziona", "Select", "Selecc.", "Sélection", "Selec."),
    "nodes": ("Nodi", "Nodes", "Nodos", "Nœuds", "Nós"),
    "line": ("Linea", "Line", "Línea", "Ligne", "Linha"),
    "rect": ("Rettangolo", "Rectangle", "Rectáng.", "Rectangle", "Retâng."),
    "ellipse": ("Ellisse", "Ellipse", "Elipse", "Ellipse", "Elipse"),
    "polygon": ("Poligono", "Polygon", "Polígono", "Polygone", "Polígono"),
    "star": ("Stella", "Star", "Estrella", "Étoile", "Estrela"),
    "special": ("Forme", "Shapes", "Formas", "Formes", "Formas"),
    "text": ("Testo", "Text", "Texto", "Texte", "Texto"),
    "measure": ("Misura", "Measure", "Medir", "Mesurer", "Medir"),
    "position": ("Vai qui", "Go here", "Ir aquí", "Aller ici", "Ir aqui"),
    "frame": ("Contorno", "Frame", "Contorno", "Contour", "Contorno"),
    "verify": ("Verifica", "Check", "Verificar", "Vérifier", "Verificar"),
    "start": ("Avvia", "Start", "Iniciar", "Démarrer", "Iniciar"),
    "pause": ("Pausa", "Pause", "Pausa", "Pause", "Pausa"),
    "stop": ("Stop", "Stop", "Stop", "Stop", "Parar"),
    "home": ("Homing", "Homing", "Homing", "Homing", "Homing"),
    "connect": ("Connetti", "Connect", "Conectar", "Connecter", "Conectar"),
    "fire_guard": ("Fiamme", "Flames", "Llamas", "Flammes", "Chamas"),
    "phone": ("Telefono", "Phone", "Teléfono", "Téléphone", "Celular"),
}


def short_names(lang=None):
    """Nomi corti per le icone nella lingua scelta (al massimo una decina di lettere)."""
    from freelasercut import i18n

    lang = lang or i18n.language()
    i = LANGS.index(lang) if lang in LANGS else 1
    return {k: v[i] for k, v in SHORT.items()}


def _keys(win):
    out = {}
    for k, a in getattr(win, "acts", {}).items():
        out[a] = k
    for k, a in getattr(win, "tool_actions", {}).items():
        out[a] = k
    return out


def label_actions(win):
    """Dà a ogni azione con icona il suo nome corto (iconText): lo usano solo i pulsanti con il testo sotto."""
    names = short_names()
    for a, k in _keys(win).items():
        if k in names:
            a.setIconText(names[k])


def _buttons(win):
    """Pulsanti a sola icona delle barre (Classica) e del Banco, con la loro azione."""
    seen = []
    for tb in win.findChildren(QToolBar):
        if tb is getattr(win, "numeric", None) or tb is getattr(win, "palette", None):
            continue
        for a in tb.actions():
            w = tb.widgetForAction(a)
            if isinstance(w, QToolButton) and not a.isSeparator() and not a.icon().isNull():
                seen.append(w)
    for b in win.findChildren(QToolButton):
        if b in seen or b.objectName() not in ("bcTool",):
            continue
        a = b.defaultAction()
        if a is not None and not a.icon().isNull():
            seen.append(b)
    return seen


def apply(win, on):
    label_actions(win)
    sheet = f"QToolButton {{ font-size: {FONT_PX}px; padding: 1px 0px 0px 0px; margin: 0px; }}"
    for tb in win.findChildren(QToolBar):
        if tb is getattr(win, "numeric", None) or tb is getattr(win, "palette", None) or tb.objectName() == "bcTopBar":
            continue
        if tb.property("flc_lbl_style") is None:
            tb.setProperty("flc_lbl_style", int(tb.toolButtonStyle().value))
            tb.setProperty("flc_lbl_sheet", tb.styleSheet())
        if on:
            tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            tb.setStyleSheet((tb.property("flc_lbl_sheet") or "") + sheet + " QToolBar { spacing: 0px; } QToolBar::separator:horizontal { width: 1px; margin: 4px 2px; } QToolBar::separator:vertical { height: 1px; margin: 2px 4px; }")
        else:
            tb.setToolButtonStyle(Qt.ToolButtonStyle(int(tb.property("flc_lbl_style"))))
            tb.setStyleSheet(tb.property("flc_lbl_sheet") or "")
    for b in _buttons(win):
        if isinstance(b.parent(), QToolBar):
            continue
        if b.property("flc_lbl_style") is None:
            b.setProperty("flc_lbl_style", int(b.toolButtonStyle().value))
            b.setProperty("flc_lbl_sheet", b.styleSheet())
        if on:
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            extra = (" QToolButton { min-width: 40px; max-width: 76px; min-height: 44px; max-height: 44px; "
                     "padding: 2px 3px 1px 3px; }") if b.objectName() == "bcTool" else ""
            b.setStyleSheet((b.property("flc_lbl_sheet") or "") + sheet + extra)
        else:
            b.setToolButtonStyle(Qt.ToolButtonStyle(int(b.property("flc_lbl_style"))))
            b.setStyleSheet(b.property("flc_lbl_sheet") or "")
        b.adjustSize()
    banco = getattr(win, "banco", None)
    if banco is not None:
        for name in ("island", "view_box"):
            w = getattr(banco, name, None)
            if w is not None:
                w.adjustSize()
        if hasattr(banco, "relayout"):
            banco.relayout()
