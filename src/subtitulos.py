#!/usr/bin/env python3
"""
Genera subtitulos (.ass) temporizados sobre el audio real de la voz.

Sin ASR disponible, se usa un metodo anclado al habla real:
1. Se detectan los TRAMOS DE HABLA (entre pausas) con sus tiempos exactos.
2. Se reparte el texto proporcional a la DURACION de cada tramo de habla
   (no al tiempo total), construyendo un mapa caracter -> tiempo por tramos.
   Asi cada palabra cae cuando realmente se pronuncia y las transiciones de
   parrafo van al ritmo de la voz.
3. Se agrupan en lineas legibles y se desplazan al tiempo ENSAMBLADO (con las
   pausas de las tarjetas de mes) usando build/schedule.json.

Estilo cinematografico: blanco, borde negro, abajo-centro.
"""
import subprocess, re, os, json
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOZ = os.path.join(RAIZ, "assets", "voz", "voz_off.wav")
TXT = os.path.join(RAIZ, "assets", "voz", "narracion.txt")
ASS = os.path.join(RAIZ, "build", "subtitulos.ass")
MAX_CHARS = 50


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", p], capture_output=True, text=True).stdout)


def tramos_habla(total):
    """Intervalos [s,e] donde HAY voz (complemento de los silencios)."""
    out = subprocess.run(["ffmpeg", "-i", VOZ, "-af", "silencedetect=noise=-33dB:d=0.25",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    sil = list(zip(st, en))
    runs, cur = [], 0.0
    for a, b in sil:
        if a > cur + 0.05:
            runs.append((cur, a))
        cur = b
    if cur < total - 0.05:
        runs.append((cur, total))
    return runs or [(0.0, total)]


def char2time(runs, total_chars):
    """Mapa caracter->tiempo, lineal por tramo de habla (anclado al audio)."""
    dur_total = sum(e - s for s, e in runs)
    segs, c = [], 0.0
    for s, e in runs:
        b = (e - s) / dur_total * total_chars
        segs.append([c, c + b, s, e]); c += b
    segs[-1][1] = total_chars
    def t_of(cc):
        cc = max(0.0, min(total_chars, cc))
        for c0, c1, t0, t1 in segs:
            if cc <= c1 + 1e-6:
                return t0 + (cc - c0) / (c1 - c0) * (t1 - t0) if c1 > c0 else t0
        return segs[-1][3]
    return t_of


def lineas_texto():
    txt = open(TXT, encoding="utf-8").read()
    txt = re.sub(r"\[break[^\]]*\]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    trozos = re.split(r"(?<=[\.\?\!])\s+", txt)
    lineas = []
    for t in trozos:
        t = t.strip()
        if not t:
            continue
        if len(t) <= MAX_CHARS:
            lineas.append(t)
        else:
            parts = re.split(r"(?<=,)\s+", t)
            buf = ""
            for p in parts:
                if len(buf) + len(p) + 1 <= MAX_CHARS:
                    buf = (buf + " " + p).strip()
                else:
                    if buf:
                        lineas.append(buf)
                    while len(p) > MAX_CHARS:
                        corte = p.rfind(" ", 0, MAX_CHARS)
                        corte = corte if corte > 0 else MAX_CHARS
                        lineas.append(p[:corte].strip()); p = p[corte:].strip()
                    buf = p
            if buf:
                lineas.append(buf)
    return lineas


def ts(s):
    h = int(s // 3600); m = int((s % 3600) // 60); seg = s % 60
    return f"{h:d}:{m:02d}:{seg:05.2f}"


def main():
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    T = dur(VOZ)
    runs = tramos_habla(T)
    lineas = lineas_texto()
    total_chars = sum(len(l) for l in lineas)
    t_of = char2time(runs, total_chars)

    # tiempos de cada linea via mapa caracter->tiempo (anclado al habla real)
    bordes = [0.0]; acum = 0
    for l in lineas:
        acum += len(l)
        bordes.append(t_of(acum))
    for i in range(1, len(bordes)):
        if bordes[i] <= bordes[i-1] + 0.25:
            bordes[i] = bordes[i-1] + 0.25

    # fusionar lineas demasiado cortas (< 1.0s) para que se lean
    MIN = 1.0
    fl, fb = [], [bordes[0]]
    i = 0
    while i < len(lineas):
        texto = lineas[i]; fin = bordes[i+1]; j = i
        while (fin - fb[-1]) < MIN and j+1 < len(lineas) \
                and len(texto + " " + lineas[j+1]) <= MAX_CHARS + 22:
            j += 1; texto = texto + " " + lineas[j]; fin = bordes[j+1]
        fl.append(texto); fb.append(fin); i = j + 1
    lineas, bordes = fl, fb

    # desplazar al tiempo ENSAMBLADO (sumar pausas de meses previas) con schedule.json
    sp = os.path.join(RAIZ, "build", "schedule.json")
    if os.path.exists(sp):
        sched = json.load(open(sp))
        cards, vacc = [], 0.0
        for seg in sched["orden"]:
            if seg["tipo"] == "voz":
                vacc += seg["dur"]
            else:
                cards.append((vacc, seg["dur"]))
        def shift(v):
            return v + sum(d for vb, d in cards if v >= vb - 0.05)
        bordes = [shift(b) for b in bordes]

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
            f.write(f"Dialogue: 0,{ts(bordes[i])},{ts(bordes[i+1])},Sub,,0,0,0,,{l}\n")
    print(f"Voz {T:.1f}s | {len(runs)} tramos habla | {len(lineas)} lineas -> {ASS}")


if __name__ == "__main__":
    main()
