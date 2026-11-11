#!/usr/bin/env bash
# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
# Installa pacchetti di sistema sulle macchine di GitHub (Ubuntu) senza restare appesi quando gli archivi non rispondono.
#
# L'11/11/2026 le Release 0.18.11 e 0.18.12 non sono uscite: dalle macchine di GitHub prima non si risolveva
# azure.archive.ubuntu.com (lo specchio che usano per primo), poi nemmeno archive.ubuntu.com. apt aspetta 20 secondi
# per ogni file e per ogni archivio: i lavori restavano fermi anche 40 minuti prima di fallire.
#
# Uso:  bash build/apt_install.sh pacchetto [pacchetto…]
# 1. se lo specchio di Azure non si risolve, lo toglie dall'elenco (restano gli archivi di Ubuntu);
# 2. PRIMA di chiamare apt controlla che un archivio risponda davvero: se dopo tre controlli nessuno risponde,
#    rinuncia subito (uscita 75), in un paio di minuti invece di decine;
# 3. altrimenti prova due volte, ogni comando con un tempo massimo.
# Chi può fare a meno di apt (vedi build/nsis_senza_apt.sh) prosegue per un'altra strada quando questo script fallisce.
# Per le prove: APT_MIRRORS_FILE, APT_RETRY_WAIT (secondi), APT_SUDO (vuoto = senza sudo), APT_TIMEOUT (secondi).
set -u

MIRRORS="${APT_MIRRORS_FILE:-/etc/apt/apt-mirrors.txt}"
WAIT="${APT_RETRY_WAIT:-20}"
SUDO="${APT_SUDO-sudo}"
LIMITE="${APT_TIMEOUT:-240}"
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

risponde() {
    curl -fsS -o /dev/null --connect-timeout 10 -m 20 "$1" 2>/dev/null
}

un_archivio_risponde() {
    if [ -f "$MIRRORS" ] && grep -q "$AZURE" "$MIRRORS" && risponde "http://$AZURE/ubuntu/dists/"; then
        return 0
    fi
    risponde "https://archive.ubuntu.com/ubuntu/dists/"
}

installa() {
    timeout "$LIMITE" $SUDO apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update \
        && timeout "$LIMITE" $SUDO apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 \
            install -y "$@"
}

getent hosts "$AZURE" >/dev/null 2>&1 || senza_azure "il nome non si risolve"

vivo=0
for controllo in 1 2 3; do
    if un_archivio_risponde; then
        vivo=1
        break
    fi
    echo "::warning::gli archivi dei pacchetti non rispondono (controllo $controllo di 3)"
    [ "$controllo" -lt 3 ] && sleep "$WAIT"
done
if [ "$vivo" -ne 1 ]; then
    echo "::error::gli archivi di Ubuntu non rispondono da questa macchina: non installo $* (guasto di rete, non del programma)" >&2
    exit 75
fi

for giro in 1 2; do
    if installa "$@"; then
        exit 0
    fi
    echo "::warning::installazione dei pacchetti non riuscita (tentativo $giro di 2)"
    senza_azure "dopo un tentativo fallito"
    [ "$giro" -lt 2 ] && sleep "$WAIT"
done
echo "::error::non riesco a installare i pacchetti di sistema: $*" >&2
exit 1
