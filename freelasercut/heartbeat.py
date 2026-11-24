# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.6: «battito» del caricamento. Mentre il programma si avvia, i punti che vengono chiamati spesso (un'icona, un
pulsante, un pannello) chiamano beat(): se la schermata d'avvio è aperta ed è passato il tempo di un fotogramma, si
ridisegna, così l'incisione dei nomi resta fluida anche mentre si costruisce la finestra. A schermata chiusa non fa
niente e non costa niente (un confronto)."""

hook = None  # la funzione da chiamare (Splash.pulse), None quando la schermata d'avvio non c'è


def beat():
    h = hook
    if h is not None:
        try:
            h()
        except Exception:  # noqa: BLE001 — il battito non deve mai fermare il caricamento
            pass
