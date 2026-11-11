#!/usr/bin/env bash
# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
# NSIS (il programma che costruisce l'installatore per Windows) senza passare da apt.
#
# Serve quando gli archivi di Ubuntu non rispondono dalle macchine di GitHub (11/11/2026: due Release non uscite).
# Scarica i due pacchetti ufficiali di Ubuntu 24.04 (gli stessi che installerebbe apt) da uno degli specchi qui
# sotto, che stanno su reti diverse da quella di Ubuntu, e li installa SOLO se la loro impronta SHA-256 è quella
# scritta qui, presa dall'indice ufficiale di Ubuntu (noble/universe, letto in https l'11/11/2026): da qualunque
# specchio arrivino, sono byte per byte i file di Ubuntu.
#
# Uso:  bash build/nsis_senza_apt.sh        (se makensis c'è già non fa niente)
# Per le prove: NSIS_MIRRORS (elenco separato da spazi), NSIS_SUDO (vuoto = senza sudo), NSIS_DIR (cartella di lavoro).
set -u

VERSIONE="3.09-4ubuntu1"
FILES="nsis-common_${VERSIONE}_all.deb nsis_${VERSIONE}_amd64.deb"
sha_di() {
    case "$1" in
        nsis-common_*) echo "49471b9debdee4751ebb4caf6b705cc4c678eebfaecefbe56362258893f85859" ;;
        nsis_*) echo "9e061bef1a8b611aeb2ea76d9a3bd7722b960ca1a9dff8e38d2ab51e5a8f5e5b" ;;
    esac
}
SPECCHI="${NSIS_MIRRORS:-https://mirrors.kernel.org/ubuntu https://mirror.math.princeton.edu/pub/ubuntu https://ftp.halifax.rwth-aachen.de/ubuntu https://mirrors.mit.edu/ubuntu https://mirror.csclub.uwaterloo.ca/ubuntu https://ftp.fau.de/ubuntu https://archive.ubuntu.com/ubuntu}"
SUDO="${NSIS_SUDO-sudo}"
DIR="${NSIS_DIR:-$(mktemp -d)}"

if command -v makensis >/dev/null 2>&1 && [ -z "${NSIS_FORZA:-}" ]; then
    echo "makensis c'è già: $(makensis -VERSION 2>/dev/null)"
    exit 0
fi

for f in $FILES; do
    buono=0
    for s in $SPECCHI; do
        url="$s/pool/universe/n/nsis/$f"
        if curl -fsSL --connect-timeout 10 -m 120 -o "$DIR/$f" "$url" 2>/dev/null; then
            if echo "$(sha_di "$f")  $DIR/$f" | sha256sum -c - >/dev/null 2>&1; then
                echo "preso $f da $s (impronta giusta)"
                buono=1
                break
            fi
            echo "::warning::$f da $s ha un'impronta diversa da quella di Ubuntu: scartato"
            rm -f "$DIR/$f"
        else
            echo "$s non risponde per $f"
        fi
    done
    if [ "$buono" -ne 1 ]; then
        echo "::error::non trovo $f con l'impronta giusta su nessuno specchio" >&2
        exit 1
    fi
done

# nell'ordine: prima i file comuni, poi il programma (che ne dipende). Le sue altre dipendenze (libc, libstdc++, zlib)
# sulle macchine di GitHub ci sono già.
$SUDO dpkg -i "$DIR/nsis-common_${VERSIONE}_all.deb" "$DIR/nsis_${VERSIONE}_amd64.deb" || exit 1
makensis -VERSION
