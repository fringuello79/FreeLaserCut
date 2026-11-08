# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Uscita delle suite che aprono la finestra principale.

Su Windows os._exit() con i thread di Qt ancora vivi (porta, camera, timer) può chiudere il processo con
«access violation» (0xC0000005) DOPO che tutti i controlli sono passati: la suite risulta interrotta.
TerminateProcess chiude subito il processo senza far girare la pulizia delle librerie (come in test_v150…v170).
"""
import os
import sys


def esci(code):
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    os._exit(code)
