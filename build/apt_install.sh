#!/usr/bin/env bash
# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
# Installa pacchetti di sistema sulle macchine di GitHub (Ubuntu), senza farsi fermare dallo specchio dei pacchetti.
#
# L'11/11/2026 la Release 0.18.11 non è uscita perché azure.archive.ubuntu.com, lo specchio che le macchine di GitHub
# usano per primo, non si risolveva più («Temporary failure resolving»): i lavori restavano 5–10 minuti ad aspettare
# e poi fallivano, due volte di fila. Gli archivi veri di Ubuntu (archive.ubuntu.com) rispondevano.
#
# Uso:  bash build/apt_install.sh pacchetto [pacchetto…]
# 1. se lo specchio di Azure non si risolve, lo toglie dall'elenco PRIMA di provare (restano gli archivi di Ubuntu);
# 2. prova fino a 4 volte, con una pausa; dopo il primo fallimento toglie comunque lo specchio di Azure.
# Per le prove: APT_MIRRORS_FILE (elenco degli specchi), APT_RETRY_WAIT (secondi di pausa), APT_SUDO (vuoto = senza sudo).
set -u

MIRRORS="${APT_MIRRORS_FILE:-/etc/apt/apt-mirrors.txt}"
WAIT="${APT_RETRY_WAIT:-30}"
SUDO="${APT_SUDO-sudo}"
AZURE="azure.archive.ubuntu.com"

if [ "$#" -eq 0 ]; then
    echo "uso: bash build/apt_install.sh pacchetto [pacchetto…]" >&2
    exit 2
fi

senza_azure() {
    # toglie lo specchio di Azure dall'elenco, se c'è e se resta almeno un altro archivio
    if [ -f "$MIRRORS" ] && grep -q "$AZURE" "$MIRRORS" && grep -v "$AZURE" "$MIRRORS" | grep -q "http"; then
        echo "::warning::$AZURE non risponde: uso gli archivi di Ubuntu ($1)"
        grep -v "$AZURE" "$MIRRORS" | $SUDO tee "$MIRRORS.nuovo" >/dev/null && $SUDO mv "$MIRRORS.nuovo" "$MIRRORS"
    fi
}

installa() {
    $SUDO apt-get -o Acquire::Retries=2 update && $SUDO apt-get -o Acquire::Retries=2 install -y "$@"
}

getent hosts "$AZURE" >/dev/null 2>&1 || senza_azure "il nome non si risolve"

for giro in 1 2 3 4; do
    if installa "$@"; then
        exit 0
    fi
    echo "::warning::installazione dei pacchetti non riuscita (tentativo $giro di 4)"
    senza_azure "dopo un tentativo fallito"
    [ "$giro" -lt 4 ] && sleep "$WAIT"
done
echo "::error::non riesco a installare i pacchetti di sistema: $*" >&2
exit 1
