#!/usr/bin/env python3
"""
Genera subtitulos (.ass) temporizados sobre el audio real de la voz.

No hay ASR disponible en el entorno, asi que se usa un metodo robusto:
1. Se parte la narracion en lineas cortas y legibles.
2. Se reparte el tiempo proporcional al numero de caracteres sobre la
   duracion real de la voz.
3. Los limites de cada linea se "pegan" (snap) a las pausas reales
   detectadas en el audio -> las palabras aparecen cuando se dicen.

Estilo cinematografico: blanco, borde negro, abajo-centro.
"""
import subprocess, re, os
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOZ = os.path.join(RAIZ, "assets", "voz", "voz_off.wav")
TXT = os.path.join(RAIZ, "assets", "voz", "narracion.txt")
ASS = os.path.join(RAIZ, "build", "subtitulos.ass")

MAX_CHARS = 52  # por linea (vertical, legible)


def dur(p):
    return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nokey=1:noprint_wrappers=1",p],capture_output=True,text=True).stdout)


def pausas():
    out = subprocess.run(["ffmpeg","-i",VOZ,"-af","silencedetect=noise=-33dB:d=0.30","-f","null","-"],
                         capture_output=True,text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return [ (a+b)/2 for a,b in zip(st,en) ]


def lineas_texto():
    txt = open(TXT, encoding="utf-8").read()
    txt = re.sub(r"\[break[^\]]*\]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    # partir en frases por puntuacion fuerte, conservando el signo
    trozos = re.split(r"(?<=[\.\?\!])\s+", txt)
    lineas = []
    for t in trozos:
        t = t.strip()
        if not t:
            continue
        if len(t) <= MAX_CHARS:
            lineas.append(t)
        else:
            # partir frases largas por comas / conjunciones sin pasar MAX_CHARS
            parts = re.split(r"(?<=,)\s+", t)
            buf = ""
            for p in parts:
                if len(buf) + len(p) + 1 <= MAX_CHARS:
                    buf = (buf + " " + p).strip()
                else:
                    if buf:
                        lineas.append(buf)
                    # si un fragmento aun es muy largo, partir por palabras
                    while len(p) > MAX_CHARS:
                        corte = p.rfind(" ", 0, MAX_CHARS)
                        corte = corte if corte > 0 else MAX_CHARS
                        lineas.append(p[:corte].strip()); p = p[corte:].strip()
                    buf = p
            if buf:
                lineas.append(buf)
    return lineas


def ts(s):
    h = int(s//3600); m = int((s%3600)//60); seg = s%60
    return f"{h:d}:{m:02d}:{seg:05.2f}"


def main():
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    T = dur(VOZ)
    ps = pausas()
    lineas = lineas_texto()
    total_chars = sum(len(l) for l in lineas)

    # tiempos por reparto proporcional de caracteres
    bordes = [0.0]
    acum = 0
    for l in lineas:
        acum += len(l)
        bordes.append(acum / total_chars * T)

    # snap de cada borde interno a la pausa mas cercana (si esta a < 0.9s)
    def snap(t):
        if not ps:
            return t
        p = min(ps, key=lambda x: abs(x - t))
        return p if abs(p - t) < 0.9 else t
    bordes = [bordes[0]] + [snap(b) for b in bordes[1:-1]] + [T]
    # asegurar monotonia
    for i in range(1, len(bordes)):
        if bordes[i] <= bordes[i-1] + 0.3:
            bordes[i] = bordes[i-1] + 0.3

    # fusionar lineas demasiado cortas (< 1.0s) con la siguiente, para que se lean
    MIN = 1.0
    fl, fb = [], [bordes[0]]
    i = 0
    while i < len(lineas):
        texto = lineas[i]; fin = bordes[i+1]; j = i
        while (fin - fb[-1]) < MIN and j+1 < len(lineas) \
                and len(texto + " " + lineas[j+1]) <= MAX_CHARS + 24:
            j += 1; texto = texto + " " + lineas[j]; fin = bordes[j+1]
        fl.append(texto); fb.append(fin); i = j + 1
    lineas, bordes = fl, fb

    # desplazar los tiempos de voz al tiempo ENSAMBLADO (sumando las pausas de las
    # tarjetas de mes que ocurren antes de cada momento) usando build/schedule.json
    sched_path = os.path.join(RAIZ, "build", "schedule.json")
    if os.path.exists(sched_path):
        import json
        sched = json.load(open(sched_path))
        cards = []  # (frontera_voz, duracion_pausa)
        vacc = 0.0
        for seg in sched["orden"]:
            if seg["tipo"] == "voz":
                vacc += seg["dur"]
            else:
                cards.append((vacc, seg["dur"]))
        def shift(v):
            return v + sum(d for vb, d in cards if v >= vb - 0.05)
        bordes = [shift(b) for b in bordes]

    # escribir ASS (1080x1920)
    cab = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Liberation Sans,52,&H00FFFFFF,&H00000000,&H96000000,-1,0,1,3,2,2,80,80,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ASS, "w", encoding="utf-8") as f:
        f.write(cab)
        for i, l in enumerate(lineas):
            ini, fin = bordes[i], bordes[i+1]
            texto = l.replace("\n", " ")
            f.write(f"Dialogue: 0,{ts(ini)},{ts(fin)},Sub,,0,0,0,,{texto}\n")

    print(f"Voz {T:.1f}s | {len(lineas)} lineas | {len(ps)} pausas -> {ASS}")
    for i, l in enumerate(lineas):
        print(f"  [{bordes[i]:6.2f} -> {bordes[i+1]:6.2f}] {l}")


if __name__ == "__main__":
    main()
