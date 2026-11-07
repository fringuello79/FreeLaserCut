# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tabelle GRBL 1.1: descrizioni in italiano di impostazioni, allarmi ed errori."""
from freelasercut.i18n import tr  # noqa: E402

# numero -> (descrizione, unità)
SETTINGS = {
    0: (tr("Durata impulso step"), "µs"),
    1: (tr("Ritardo inattività motori"), "ms"),
    2: (tr("Inversione impulso step (maschera)"), "mask"),
    3: (tr("Inversione direzione (maschera)"), "mask"),
    4: (tr("Inverti abilitazione step"), "bool"),
    5: (tr("Inverti pin finecorsa"), "bool"),
    6: (tr("Inverti pin sonda"), "bool"),
    10: (tr("Contenuto report di stato (maschera)"), "mask"),
    11: (tr("Deviazione di giunzione"), "mm"),
    12: (tr("Tolleranza archi"), "mm"),
    13: (tr("Report in pollici"), "bool"),
    20: (tr("Soft limits"), "bool"),
    21: (tr("Hard limits"), "bool"),
    22: (tr("Ciclo di homing"), "bool"),
    23: (tr("Direzione homing (maschera)"), "mask"),
    24: (tr("Velocità homing fine"), "mm/min"),
    25: (tr("Velocità ricerca homing"), "mm/min"),
    26: (tr("Debounce homing"), "ms"),
    27: (tr("Distacco dal finecorsa"), "mm"),
    30: (tr("Potenza massima laser (S max)"), "S"),
    31: (tr("Potenza minima laser (S min)"), "S"),
    32: (tr("Modalità laser"), "bool"),
    100: (tr("Passi/mm asse X"), "step/mm"),
    101: (tr("Passi/mm asse Y"), "step/mm"),
    102: (tr("Passi/mm asse Z"), "step/mm"),
    110: (tr("Velocità massima X"), "mm/min"),
    111: (tr("Velocità massima Y"), "mm/min"),
    112: (tr("Velocità massima Z"), "mm/min"),
    120: (tr("Accelerazione X"), "mm/s²"),
    121: (tr("Accelerazione Y"), "mm/s²"),
    122: (tr("Accelerazione Z"), "mm/s²"),
    130: (tr("Corsa massima X"), "mm"),
    131: (tr("Corsa massima Y"), "mm"),
    132: (tr("Corsa massima Z"), "mm"),
}

# schede ESP32 a 6 assi (come la LS_ESP32 del B1): assi A, B, C non usati dal laser
for _base, _label, _unit in ((100, tr("Passi/mm asse"), "step/mm"), (110, tr("Velocità massima"), "mm/min"),
                             (120, tr("Accelerazione"), "mm/s²"), (130, tr("Corsa massima"), "mm")):
    for _i, _ax in enumerate("ABC", start=3):
        SETTINGS[_base + _i] = (tr("{0} {1} (non usato dal laser)", _label, _ax), _unit)

# parametri propri del firmware Longer/MKS: senza documentazione pubblica, sola lettura in FreeLaserCut
VENDOR_SETTINGS = set(range(28, 30)) | set(range(33, 100))
VENDOR_LABEL = (tr("Parametro del firmware Longer/MKS (non documentato): sola lettura"), "")
for _n in (28, 37, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54):
    SETTINGS.setdefault(_n, VENDOR_LABEL)
SETTINGS[51] = (tr("Tipo di scheda (firmware Longer/MKS): sola lettura"), "")

# 0.17.2: area di lavoro credibile per un laser da hobby o da laboratorio. Un valore fuori (visto: $131=234500,
# probabilmente «234.500» letto senza il punto) non diventa il piano: FreeLaserCut lo ignora, avvisa e rilegge.
TRAVEL_MIN, TRAVEL_MAX = 10.0, 3000.0


def travel_ok(value):
    """Corsa ($130/$131) credibile, in mm."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return TRAVEL_MIN <= v <= TRAVEL_MAX


def bad_travel(settings):
    """[(numero, "valore")] di $130/$131 presenti ma non credibili. Lo zero non conta: molte schede lo lasciano
    così quando la corsa non è impostata, e allora il piano resta quello del profilo, come sempre."""
    out = []
    for n in (130, 131):
        v = (settings or {}).get(n, (settings or {}).get(str(n)))
        if v is None:
            continue
        try:
            if float(v) == 0:
                continue
        except (TypeError, ValueError):
            pass
        if not travel_ok(v):
            out.append((n, str(v)))
    return out


# impostazioni che contano di più per un laser: evidenziate nell'interfaccia
KEY_SETTINGS = {21, 22, 30, 31, 32, 110, 111, 120, 121, 130, 131}

ALARMS = {
    1: tr("Finecorsa attivato durante il movimento: posizione persa, rifai l'homing"),
    2: tr("Comando oltre l'area di lavoro (soft limits)"),
    3: tr("Reset durante il movimento: posizione persa, rifai l'homing"),
    4: tr("Sonda non nello stato iniziale"),
    5: tr("Sonda non toccata"),
    6: tr("Homing interrotto da un reset"),
    7: tr("Homing fallito: porta di sicurezza aperta"),
    8: tr("Homing fallito: finecorsa non rilasciato"),
    9: tr("Homing fallito: finecorsa non trovato"),
    10: tr("Homing fallito: finecorsa doppio"),
}

ERRORS = {
    1: tr("Lettera di comando mancante"),
    2: tr("Valore numerico non valido"),
    3: tr("Comando $ non riconosciuto"),
    4: tr("Valore negativo non ammesso"),
    5: tr("Homing non abilitato ($22)"),
    6: tr("Impulso step troppo breve"),
    7: tr("Lettura memoria impostazioni fallita"),
    8: tr("Comando $ non ammesso durante il movimento"),
    9: tr("Bloccato da allarme: sblocca ($X) o fai homing ($H)"),
    10: tr("I soft limits richiedono l'homing"),
    11: tr("Riga troppo lunga"),
    12: tr("Velocità di step troppo alta"),
    13: tr("Porta di sicurezza aperta"),
    14: tr("Riga di avvio troppo lunga"),
    15: tr("Jog oltre l'area di lavoro"),
    16: tr("Comando di jog non valido"),
    17: tr("La modalità laser richiede l'uscita PWM"),
    20: tr("Comando G-code non supportato"),
    21: tr("Comandi in conflitto nella stessa riga"),
    22: tr("Avanzamento F non impostato"),
    23: tr("Serve un valore intero"),
    24: tr("Più comandi che usano gli assi nella stessa riga"),
    25: tr("Parola G-code ripetuta"),
    26: tr("Assi mancanti nel comando"),
    27: tr("Numero di riga non valido"),
    28: tr("Valore mancante"),
    29: "G59.x non supportato",
    30: "G53 ammesso solo con G0 o G1",
    31: tr("Assi non usati nella riga"),
    32: tr("Arco senza assi nel piano selezionato"),
    33: tr("Destinazione del movimento non valida"),
    34: tr("Geometria dell'arco non valida"),
    35: tr("Arco senza offset"),
    36: tr("Parole G-code non usate"),
    37: tr("Offset utensile non valido"),
    38: tr("Numero utensile non valido"),
}

# colore per stato macchina (usato da UI)
STATE_COLORS = {
    "Idle": "#30A46C",
    "Run": "#2E7CF6",
    "Jog": "#22B8CF",
    "Hold": "#F5A524",
    "Door": "#F5A524",
    "Home": "#8E6CF0",
    "Alarm": "#E5484D",
    "Check": "#8A9BBE",
    "Sleep": "#8A9BBE",
}
