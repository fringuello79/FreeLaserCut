# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Prepara la cartella del pacchetto MSIX per il Microsoft Store (lo Store firma il pacchetto: niente avvisi
di SmartScreen). Usa la stessa cartella build/stage dell'installatore.

    python build/prepara_installer.py                 (se build/stage non c'è ancora)
    python build/prepara_msix.py --identity NOME --publisher "CN=..." --display fringuello79
    makeappx pack /d build\\msix_layout /p build\\FreeLaserCut-<versione>.msix     (Windows SDK, su Windows)

Identity e Publisher si copiano da Partner Center → la tua app → Identità del prodotto.
"""
import argparse
import os
import re
import shutil
import sys

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
STAGE = os.path.join(BUILD, "stage")
LAYOUT = os.path.join(BUILD, "msix_layout")


def version():
    txt = open(os.path.join(ROOT, "freelasercut", "__init__.py"), encoding="utf-8").read()
    v = re.search(r'__version__ = "([^"]+)"', txt).group(1)
    parts = (v.split(".") + ["0", "0", "0"])[:3]
    return ".".join(parts) + ".0"  # lo Store vuole la quarta cifra a 0


def assets(dest):
    from PIL import Image

    logo = Image.open(os.path.join(ROOT, "docs", "logo", "logo_1024.png")).convert("RGBA")
    os.makedirs(dest, exist_ok=True)

    def square(name, size):
        logo.resize((size, size), Image.LANCZOS).save(os.path.join(dest, name))

    square("StoreLogo.png", 50)
    square("Square44x44Logo.png", 44)
    square("Square150x150Logo.png", 150)
    square("Square310x310Logo.png", 310)
    wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
    icon = logo.resize((130, 130), Image.LANCZOS)
    wide.paste(icon, (90, 10), icon)
    wide.save(os.path.join(dest, "Wide310x150Logo.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--identity", default="fringuello79.FreeLaserCut")  # Partner Center → Product identity
    ap.add_argument("--publisher", default="CN=8996ADD5-BD72-4563-B3A0-3BBBF2AF8C40")
    ap.add_argument("--display", default="fringuello79")
    ap.add_argument("--name", default="Free Laser Cut")  # nome riservato in Partner Center
    a = ap.parse_args()
    if not os.path.isdir(os.path.join(STAGE, "python")):
        sys.exit("Manca build/stage: esegui prima python build/prepara_installer.py")
    shutil.rmtree(LAYOUT, ignore_errors=True)
    shutil.copytree(STAGE, LAYOUT, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    assets(os.path.join(LAYOUT, "Assets"))
    man = open(os.path.join(BUILD, "msix", "AppxManifest.xml"), encoding="utf-8").read()
    for k, v in (("{IDENTITY_NAME}", a.identity), ("{PUBLISHER}", a.publisher), ("{PUBLISHER_DISPLAY}", a.display), ("{DISPLAY_NAME}", a.name),
                 ("{VERSION}", version())):
        man = man.replace(k, v)
    open(os.path.join(LAYOUT, "AppxManifest.xml"), "w", encoding="utf-8").write(man)
    print(f"Pronto: {LAYOUT} (versione {version()})")
    print(rf"Su Windows: makeappx pack /d build\msix_layout /p build\FreeLaserCut-{version()}.msix")


if __name__ == "__main__":
    main()
