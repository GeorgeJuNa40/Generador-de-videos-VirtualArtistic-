#!/usr/bin/env python3
"""Tiempo exacto de cada tarjeta de mes usando la alineacion forzada (aeneas):
se ubica el fragmento que inicia cada frase-ancla y se toma su tiempo de inicio."""
import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))
import alinear

ANCLAS = {
    "Mes 1":  "Empiezas por lo obvio",
    "Mes 3":  "Decides subir de nivel",
    "Mes 5":  "Contratas a alguien interno",
    "Mes 8":  "Enfrente hay alguien que no sabe",
    "Mes 11": "Y hay una pregunta que llevas cuatro meses",
    "Mes 12": "Miras el saldo por",
}


def norm(s):
    for a, b in zip("áéíóúÁÉÍÓÚ", "aeiouAEIOU"):
        s = s.replace(a, b)
    return s.lower()


def tiempos_meses():
    frags = alinear.alinear()
    res = {}
    for mes, frase in ANCLAS.items():
        fn = norm(frase)
        cand = [ini for ini, fin, txt in frags if norm(txt).startswith(fn) or fn in norm(txt)]
        if cand:
            res[mes] = round(min(cand), 2)
    return res


if __name__ == "__main__":
    for mes, t in tiempos_meses().items():
        print(f"  {mes:8} -> {t:.2f}s")
