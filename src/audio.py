#!/usr/bin/env python3
"""
Mezcla de audio del cortometraje.

Construye una "cama musical" por regiones (musica base / musica de climax /
silencio total) y la combina con la voz en off, que siempre manda.

Reglas (ver guion.json -> "audio"):
- Voz: pista principal, normalizada; nunca por debajo de -6 dB.
- Musica: siempre por debajo de la voz (-18 a -22 dB).
- Ventana(s) de silencio total de musica en el momento clave (bloque Mes 11).
- La musica base se repite en bucle para cubrir toda la duracion.
- Una pista de "tension" distinta puede entrar en la region del climax.
"""
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERROR audio:\n", r.stderr[-1200:], file=sys.stderr)
        raise SystemExit(1)
    return r


def dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def region_musica(fuente, ini, fin, nivel_db, salida):
    """Genera un segmento de musica (en bucle si hace falta) del largo [ini,fin] al nivel dado."""
    largo = fin - ini
    run([
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", fuente,
        "-t", f"{largo:.3f}",
        "-af", f"volume={nivel_db}dB,afade=t=in:st=0:d=0.4,"
               f"afade=t=out:st={max(0, largo-0.6):.3f}:d=0.6",
        "-ar", "48000", "-ac", "2", salida,
    ])


def region_silencio(ini, fin, salida):
    largo = fin - ini
    run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r=48000:cl=stereo",
        "-t", f"{largo:.3f}", "-ar", "48000", "-ac", "2", salida,
    ])


def construir_cama(conf, build_dir, total):
    """Concatena las regiones de musica/silencio hasta cubrir `total` segundos."""
    a = conf["audio"]
    base = os.path.join(RAIZ, a["musica_base"])
    climax = os.path.join(RAIZ, a.get("musica_climax", a["musica_base"]))
    nivel = a["musica_nivel_db"]

    partes = []
    for i, reg in enumerate(a["regiones"]):
        out = os.path.join(build_dir, f"mus_{i:02d}.wav")
        tipo = reg["fuente"]
        if tipo == "silencio":
            region_silencio(reg["desde_seg"], reg["hasta_seg"], out)
        else:
            fuente = climax if tipo == "climax" else base
            nv = reg.get("nivel_db", nivel)
            region_musica(fuente, reg["desde_seg"], reg["hasta_seg"], nv, out)
        partes.append(out)

    lista = os.path.join(build_dir, "mus_list.txt")
    with open(lista, "w") as f:
        for p in partes:
            f.write(f"file '{p}'\n")
    cama = os.path.join(build_dir, "cama_musical.wav")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lista,
         "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", cama])
    return cama


def mezclar(conf, video_sin_audio, salida, build_dir):
    """Mezcla voz (dominante) + cama musical sobre el video final."""
    a = conf["audio"]
    voz = os.path.join(RAIZ, a["voz_archivo"])
    total = dur(video_sin_audio)

    cama = construir_cama(conf, build_dir, total)

    # loudnorm deja la voz fuerte y consistente; volume ajusta el objetivo.
    voz_ganancia = a.get("voz_nivel_db", -3.0)
    fc = (
        f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume={voz_ganancia}dB[voz];"
        f"[2:a]apad[mus];"
        f"[voz][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    run([
        "ffmpeg", "-y",
        "-i", video_sin_audio,
        "-i", voz,
        "-i", cama,
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest",
        salida,
    ])
    return salida


if __name__ == "__main__":
    conf = json.load(open(os.path.join(RAIZ, "guion.json"), encoding="utf-8"))
    video = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "build", "con_fade.mp4")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RAIZ, "output", "con_audio.mp4")
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    mezclar(conf, video, out, os.path.join(RAIZ, "build"))
    print("Audio mezclado ->", out)
