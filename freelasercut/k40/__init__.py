# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""K40 con la scheda M2 Nano (e sorelle Lihuiyu): driver in costruzione, non ancora collegato all'interfaccia.

Pezzi:
- codici: codici di velocità;
- scrittore: dal movimento (taglio, spostamento, laser acceso/spento) ai comandi della scheda, a pezzi con le attese;
- da_gcode: dal G-code che FreeLaserCut prepara per le macchine GRBL ai pezzi per la K40.

Conoscenze tecniche da fonti aperte (MeerK40t, licenza MIT; pagina «Lhystudios M2 Nano» di EduTech Wiki): vedi
RICONOSCIMENTI-TECNICI.md. Il codice è scritto da capo.
"""
