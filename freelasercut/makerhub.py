# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""MakerHub (maker-hub.it), un servizio esterno, di altri: i loro strumenti per il laser, dal menu Strumenti
(fino alla 0.19.1 fra le funzioni in prova, dalla 0.19.2 per tutti).

«Strumenti MakerHub» (menu Strumenti e barra di sinistra) apre nel browser il loro sito, dove si sceglie uno dei
quattro programmi: Dima Lab, Forma Lab, Hinge Lab, Split Lab. Fino alla 0.19.1 c'erano quattro voci, una per
programma, che portavano tutte alla stessa pagina.
Dalla 0.18.14 quei programmi hanno il pulsante «Manda a FreeLaserCut»: il disegno arriva sul piano di lavoro senza
scaricarlo e importarlo a mano (vedi makerhub_link.py, che è la parte che lo riceve).

Questo file non fa rete: apre soltanto una pagina nel browser dell'utente, quando lui lo chiede.

Storia: la 0.18.10 aveva «FreeLaserCut Live» (codice di collegamento e ascolto del loro server), tolto perché sul
sito non era attivo: resta nel tag v0.18.10. La 0.18.11 aveva la sola voce «Scatola a incastri».

Nome e logo sono di MakerHub, usati con il loro permesso.
"""
import os
import urllib.parse

DOMAIN = "maker-hub.it"
SITE_URL = "https://app.maker-hub.it/?da=freelasercut"  # «da=»: loro contano chi arriva da qui

# I quattro programmi di MakerHub per il laser. Sul loro sito (un'unica pagina, con l'accesso) lo strumento si sceglie
# dopo, dal loro menu: per questo dalla 0.19.2 FreeLaserCut ha un solo comando «Strumenti MakerHub» che apre il sito,
# invece di quattro voci che portavano tutte alla stessa pagina.
TOOL_NAMES = ("Dima Lab", "Forma Lab", "Hinge Lab", "Split Lab")

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "makerhub.png")
ICON_SIZE = 20  # come le icone degli altri strumenti (ui/style.icon)
ICON_INSET = 0.075  # il riquadro arancione sta un po' dentro la casella, come i disegni delle altre icone
ICON_RADIUS = 0.22  # angoli tondi, in proporzione al lato


def safe_url(url):
    """L'indirizzo, se è https e di maker-hub.it; altrimenti None. Il programma apre nel browser solo questi."""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or not (host == DOMAIN or host.endswith("." + DOMAIN)):
        return None
    return u.geturl()


def _tile(px, faded=False):
    """Il logo arancione in un riquadro con gli angoli tondi, su fondo trasparente, largo px pixel."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap

    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    src = QImage(LOGO)
    if src.isNull():
        return pm
    m = px * ICON_INSET
    box = QRectF(m, m, px - 2 * m, px - 2 * m)
    side = max(1, round(box.width()))
    small = src.scaled(side, side, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)  # riduzione di qualità, una volta
    if faded:
        small = small.convertToFormat(QImage.Format_Grayscale8)
    clip = QPainterPath()
    clip.addRoundedRect(box, box.width() * ICON_RADIUS, box.width() * ICON_RADIUS)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.setClipPath(clip)
    if faded:
        p.setOpacity(0.45)
    p.drawImage(box, small)
    p.end()
    return pm


def icon(size=ICON_SIZE):
    """L'icona di MakerHub per menu e ricerca dei comandi: il loro logo a colori (non si ricolora con il tema, come
    fanno le altre: l'arancione si legge sia sul chiaro sia sullo scuro), nitido anche sugli schermi ad alta densità."""
    from PySide6.QtGui import QIcon

    ic = QIcon()
    for scale in (1, 2, 3):
        ic.addPixmap(_tile(size * scale), QIcon.Mode.Normal)
        ic.addPixmap(_tile(size * scale, faded=True), QIcon.Mode.Disabled)
    return ic


def open_site():
    """Apre nel browser dell'utente il sito degli strumenti di MakerHub. -> True se il sistema l'ha aperto."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    url = safe_url(SITE_URL)
    return bool(url) and bool(QDesktopServices.openUrl(QUrl(url)))
