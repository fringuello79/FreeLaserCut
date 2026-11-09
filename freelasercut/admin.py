# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Funzioni in prova, sbloccabili con il codice amministratore (0.17.16).

Nel codice c'è solo l'impronta (SHA-256) del codice, non il codice: chi usa il programma non vede le funzioni ancora
in prova finché non le sblocca. Il programma è open source, quindi non è una protezione: serve solo a tenerle da parte.
"""
import hashlib

_SALT = "freelasercut-admin:"
_HASH = "f915aac0206845f55208d19ebe8ad1bfa742060a744f01777a42c9989cd46fcf"
KEY = "admin_unlocked"


def check(code):
    """Il codice è giusto? (maiuscole e minuscole e spazi ai lati non contano)"""
    c = str(code or "").strip().lower()
    return bool(c) and hashlib.sha256((_SALT + c).encode("utf-8")).hexdigest() == _HASH


def unlocked(qs):
    return qs.value(KEY) in (True, "true")


def set_unlocked(qs, on):
    qs.setValue(KEY, bool(on))
