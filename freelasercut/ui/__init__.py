# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Interfaccia di FreeLaserCut (editor, pannelli, finestra principale)."""


def _qt69_menu_fix():
    """0.22.5: con PySide6 6.9 (il pacchetto per i Mac Intel con macOS 13, pull request #29) chiedere a un'azione il suo
    menu (QAction.menu()) e poi lasciar andare l'azione rende inservibile il menu: «Internal C++ object (QMenu) already
    deleted», menu che spariscono, chiusure improvvise. Qui ogni azione a cui si chiede il menu resta tenuta in vita.
    Con PySide6 6.10 e più recenti (le versioni normali) non cambia niente: la correzione non si attiva."""
    try:
        import PySide6
        from PySide6.QtGui import QAction
        ver = tuple(int(x) for x in PySide6.__version__.split(".")[:2])
    except Exception:  # noqa: BLE001
        return False
    if ver >= (6, 10) or getattr(QAction, "_flc_menu_fix", False):
        return False
    originale = QAction.menu
    tenute = {}

    def menu(self):
        m = originale(self)
        if m is not None:
            tenute[id(self)] = (self, m)  # l'azione e il suo menu restano vivi finché vive il programma
        return m

    QAction.menu = menu
    QAction._flc_menu_fix = True
    QAction._flc_menu_tenute = tenute
    return True


QT69_MENU_FIX = _qt69_menu_fix()
