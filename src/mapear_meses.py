#!/usr/bin/env python3
"""Propone el tiempo de cada tarjeta de mes: ubica la frase-ancla en el texto,
la mapea proporcionalmente sobre la duracion de la voz y la ajusta (snap) a la
pausa real mas cercana detectada en el audio."""
import subprocess, re, os
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
voz = os.path.join(RAIZ, "assets", "voz", "voz_off.wav")
txt = open(os.path.join(RAIZ, "assets", "voz", "narracion.txt"), encoding="utf-8").read()

def dur(p):
    return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nokey=1:noprint_wrappers=1",p],capture_output=True,text=True).stdout)

TOTAL = dur(voz)

# 1) pausas reales (punto medio de cada silencio)
out = subprocess.run(["ffmpeg","-i",voz,"-af","silencedetect=noise=-33dB:d=0.35","-f","null","-"],
                     capture_output=True,text=True).stderr
st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
pausas = [round((a+b)/2,2) for a,b in zip(st,en)]

# 2) texto limpio (sin etiquetas de break) y mapa char->posicion
limpio = re.sub(r"\[break[^\]]*\]", "", txt)
limpio = re.sub(r"\s+", " ", limpio).strip()
N = len(limpio)

# frases-ancla que disparan cada tarjeta de mes
anclas = {
    "Mes 1":  "Empiezas por lo obvio",
    "Mes 3":  "Decides subir de nivel",
    "Mes 5":  "Contratas a alguien interno",
    "Mes 8":  "Enfrente hay alguien que no sabe",
    "Mes 11": "Y hay una pregunta que llevas cuatro meses",
    "Mes 12": "Miras el saldo por ultima vez",
}
# normalizar acentos para buscar
def norm(s):
    for a,b in zip("áéíóúÁÉÍÓÚ","aeiouAEIOU"): s=s.replace(a,b)
    return s
limpio_n = norm(limpio)

print(f"Voz total: {TOTAL:.1f}s | {len(pausas)} pausas detectadas\n")
print(f"{'Tarjeta':8} {'char%':>6} {'t.prop':>8} {'t.pausa':>8}   frase")
for mes, frase in anclas.items():
    idx = limpio_n.find(norm(frase))
    if idx < 0:
        print(f"{mes:8}  NO ENCONTRADA: {frase}"); continue
    frac = idx / N
    t_prop = frac * TOTAL
    t_snap = min(pausas, key=lambda p: abs(p - t_prop))
    print(f"{mes:8} {frac*100:5.1f}% {t_prop:7.1f}s {t_snap:7.1f}s   \"{frase}...\"")
