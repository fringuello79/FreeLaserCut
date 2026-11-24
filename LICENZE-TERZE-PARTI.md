# Licenze di terze parti

FreeLaserCut è distribuito con la licenza **GNU GPL 3.0 o successiva** (file `LICENSE`).
Usa e, nell'installatore per Windows e nell'AppImage per Linux, include componenti di altri autori, ciascuno con la propria licenza.
I testi completi sono nella cartella `licenze-terze-parti/` (e, nell'installazione, anche nelle cartelle
`*.dist-info` di ogni libreria dentro `python\Lib\site-packages`).

## Inclusi nel codice sorgente

| Componente | Uso | Licenza | Testo |
|---|---|---|---|
| Inter (Rasmus Andersson) | carattere dell'interfaccia e del logo | SIL Open Font License 1.1 | `freelasercut/assets/licenses/Inter-OFL.txt` |
| JetBrains Mono | carattere a larghezza fissa | SIL Open Font License 1.1 | `freelasercut/assets/licenses/JetBrainsMono-OFL.txt` |
| Lucide | icone | ISC | `freelasercut/assets/licenses/Lucide-ISC.txt` |

## Inclusi nell'installatore per Windows

| Componente | Licenza | Testo |
|---|---|---|
| Python 3.14 (CPython, build python-build-standalone) | PSF License 2.0 | `python-CPython-PSF.txt` |
| — OpenSSL | Apache 2.0 | `python-openssl-3.txt` |
| — libffi, expat, liblzma (xz), mpdecimal, bzip2, zlib / zlib-ng, zstd | licenze permissive (MIT, BSD e simili) | `python-*.txt` |
| — SQLite | pubblico dominio | — |
| Qt 6 e PySide6 / Shiboken6 6.12 (The Qt Company) | GNU LGPL 3.0 | `LGPL-3.0.txt` |
| NumPy | BSD 3-Clause (con parti 0BSD, MIT, Zlib, CC0) | `numpy-BSD-3-Clause.txt` |
| OpenCV (opencv-python) | Apache 2.0; componenti di terze parti tra cui FFmpeg (LGPL 2.1) | `opencv-Apache-2.0.txt`, `opencv-terze-parti.txt` |
| Numba | BSD 2-Clause | `numba-BSD-2-Clause.txt`, `numba-terze-parti.txt` |
| llvmlite (con LLVM) | BSD 2-Clause; LLVM: Apache 2.0 con eccezione LLVM | `llvmlite-BSD-2-Clause.txt`, `llvmlite-terze-parti.txt` |
| Pillow | MIT-CMU (HPND) | `Pillow-MIT-CMU.txt` |
| ezdxf | MIT | `ezdxf-MIT.txt` |
| fontTools | MIT | `fonttools-MIT.txt` |
| pyclipper (Clipper di Angus Johnson) | MIT / Boost | `pyclipper-MIT.txt` |
| svgelements | MIT | `svgelements-MIT.txt` |
| pyserial | BSD 3-Clause | `pyserial-BSD-3-Clause.txt` |
| pyusb (dalla 0.22.5, per parlare con le schede USB delle K40 in «Studia la macchina») | BSD 3-Clause | `pyusb-BSD-3-Clause.txt` |
| Hershey-Fonts (font a linea singola Hershey) | MIT | `Hershey-Fonts-MIT.txt` |
| pyparsing | MIT | `pyparsing-MIT.txt` |
| typing_extensions | PSF License 2.0 | `typing_extensions-PSF.txt` |
| segno (codici QR) | BSD 3-Clause | `segno-BSD-3-Clause.txt` |
| python-barcode (codici a barre) | MIT | `python-barcode-MIT.txt` |
| pygame-ce 2.5 (dalla 0.21.2, solo per leggere il joystick fisico), con dentro SDL2 e le librerie di SDL per immagini, caratteri e suoni | GNU LGPL 2.1; SDL2: zlib; le altre come elencato | `pygame-ce-LGPL-2.1.txt`, `pygame-ce-terze-parti.txt` |

### Qt e PySide6 (LGPL 3.0)

Le librerie Qt e PySide6 sono incluse **senza modifiche**, come file separati (DLL e moduli `.pyd` nella
cartella `python\Lib\site-packages\PySide6`): chi vuole può sostituirle con altre versioni compatibili.
Il codice sorgente di Qt è disponibile su <https://download.qt.io/official_releases/qt/> e quello di
PySide6 su <https://download.qt.io/official_releases/QtForPython/> (versione 6.12.0).
Le licenze dei componenti di terze parti usati da Qt sono elencate su <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

Il pacchetto aggiuntivo per macOS Ventura su Intel include Python 3.13.18 (PSF License 2.0),
Qt, PySide6 Essentials e Shiboken6 6.9.3
(LGPL 3.0) e OpenCV headless 4.11.0.86 (Apache 2.0, con componenti di terze parti). I sorgenti sono
disponibili negli archivi Qt e Qt for Python indicati sopra e nel
[repository OpenCV](https://github.com/opencv/opencv/tree/4.11.0) e nel
[repository delle wheel OpenCV](https://github.com/opencv/opencv-python/tree/4.11.0.86).

### Come si ottengono questi componenti

L'installatore li scarica dalle fonti ufficiali (PyPI e il progetto python-build-standalone su GitHub) con lo
script `build/prepara_installer.py`, senza modificarli. Le versioni esatte sono indicate nello script.

## Marchi

I nomi di prodotti e marchi citati sono dei rispettivi titolari e sono usati solo per indicare la compatibilità.

## Inclusi nell'AppImage per Linux (dalla 0.18.0)

Gli stessi componenti dell'installatore per Windows, nelle versioni per Linux, con queste differenze:

| Componente | Licenza | Testo |
|---|---|---|
| Python 3.14 per Linux (python-build-standalone), con dentro anche ncurses (MIT/X11), libedit (BSD) e libuuid (BSD 3-Clause) | PSF License 2.0 e licenze permissive | `python-CPython-PSF.txt`, `python-*.txt`, `usr/python/lib/python3.14/LICENSE.txt` nell'AppImage |
| OpenCV nella versione «headless» (opencv-python-headless: senza la sua copia di Qt) | Apache 2.0; componenti di terze parti tra cui FFmpeg (LGPL 2.1) | `opencv-Apache-2.0.txt`, `opencv-terze-parti.txt` |
| xcb-util: libxcb-cursor, libxcb-icccm, libxcb-image, libxcb-keysyms, libxcb-render-util, libxcb-util (dai pacchetti di Ubuntu 22.04, perché molte distribuzioni non le installano e Qt 6 le chiede) | MIT/X11 | `xcb-util-MIT.txt` |
| estensioni di libxcb: libxcb-randr, libxcb-render, libxcb-shape, libxcb-shm, libxcb-sync, libxcb-xfixes, libxcb-xkb (dai pacchetti di Ubuntu 22.04, dalla 0.18.1) | MIT/X11 | `libxcb-MIT.txt` |
| libxkbcommon-x11 e, dalla 0.20.5, libxkbcommon (dai pacchetti di Ubuntu 22.04, sempre in coppia: stessa versione) | MIT | `libxkbcommon-MIT.txt` |
| GLib: solo libgthread-2.0 (dal pacchetto libglib2.0-0 di Ubuntu 22.04, dalla 0.20.5: Qt la chiede e openSUSE non la installa di serie). Sorgente: <https://gitlab.gnome.org/GNOME/glib> (versione 2.72) | GNU LGPL 2.1 o successiva | `glib-LGPL-2.1.txt` |
| runtime dell'AppImage (AppImage/type2-runtime) | MIT | — |

Le librerie sono incluse senza modifiche, come file separati: si possono sostituire con quelle del sistema.

