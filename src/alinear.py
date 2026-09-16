#!/usr/bin/env python3
"""
Alineacion forzada texto<->voz con aeneas (precisa, palabra a palabra).
Genera build/alineacion.json con {ini, fin, texto} por fragmento.
"""
import os, json, subprocess, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOZ = os.path.join(RAIZ, "assets", "voz", "voz_off.wav")
FRAGS = os.path.join(RAIZ, "build", "frags.txt")
OUT = os.path.join(RAIZ, "build", "alineacion.json")


def alinear(forzar=False):
    """Devuelve [(ini, fin, texto)]. Cachea en build/alineacion.json."""
    sys.path.insert(0, os.path.join(RAIZ, "src"))
    import subtitulos
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    lineas = subtitulos.lineas_texto()
    open(FRAGS, "w", encoding="utf-8").write("\n".join(lineas) + "\n")

    r = subprocess.run(["python3", "-m", "aeneas.tools.execute_task",
        VOZ, FRAGS,
        "task_language=spa|is_text_type=plain|os_task_file_format=json",
        OUT], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(OUT):
        print("ERROR aeneas:\n", r.stderr[-800:], file=sys.stderr)
        raise SystemExit(1)
    d = json.load(open(OUT))
    return [(float(f["begin"]), float(f["end"]), f["lines"][0]) for f in d["fragments"]]


if __name__ == "__main__":
    frs = alinear()
    print(f"{len(frs)} fragmentos alineados. Ultimo fin: {frs[-1][1]:.2f}s")
