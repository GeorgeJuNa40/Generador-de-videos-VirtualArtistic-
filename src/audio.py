#!/usr/bin/env python3
"""
Mezcla de audio del cortometraje, guiada por build/schedule.json.

Modelo: la linea ENSAMBLADA intercala tramos de VOZ (narracion) con TARJETAS
de mes que son SILENCIO TOTAL (voz y musica) + un efecto de sonido.

- Voz: se corta en trozos segun el schedule y se separa con silencios en las
  tarjetas (la voz se pausa de verdad en cada mes).
- Musica: base suave; se calla en cada tarjeta y en el bloque climax (Mes 11).
- SFX: un impacto grave en cada tarjeta de mes.
- El cierre (despues del cuerpo) queda en silencio.
"""
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERROR audio:\n", " ".join(str(c) for c in cmd[:6]),
              "\n", r.stderr[-1400:], file=sys.stderr)
        raise SystemExit(1)
    return r


def dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", path],
        capture_output=True, text=True).stdout.strip())


def silencio(bd, i, d):
    out = os.path.join(bd, f"a_sil_{i:03d}.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", f"{d:.3f}", out])
    return out


def concat_wav(bd, piezas, salida):
    lst = os.path.join(bd, "a_list.txt")
    with open(lst, "w") as f:
        for p in piezas:
            f.write(f"file '{p}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-ar", "48000", "-ac", "2", salida])
    return salida


def construir_voz(conf, sched, bd):
    """Voz recortada en trozos con silencios reales en las tarjetas."""
    voz = os.path.join(RAIZ, conf["audio"]["voz_archivo"])
    piezas = []
    for i, seg in enumerate(sched["orden"]):
        if seg["tipo"] == "voz":
            out = os.path.join(bd, f"a_voz_{i:03d}.wav")
            run(["ffmpeg", "-y", "-ss", f"{seg['voz_ini']:.3f}", "-t", f"{seg['dur']:.3f}",
                 "-i", voz, "-ar", "48000", "-ac", "2", out])
            piezas.append(out)
        else:  # card -> silencio
            piezas.append(silencio(bd, i, seg["dur"]))
    return concat_wav(bd, piezas, os.path.join(bd, "voz_cuerpo.wav"))


def construir_musica(conf, sched, bd, total):
    """Musica base continua que se calla en tarjetas y en el bloque climax."""
    a = conf["audio"]
    base = os.path.join(RAIZ, a["musica_base"])
    nivel = a["musica_nivel_db"]
    # base continua a lo largo de todo el cuerpo
    base_full = os.path.join(bd, "base_full.wav")
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", base, "-t", f"{total:.3f}",
         "-af", f"volume={nivel}dB", "-ar", "48000", "-ac", "2", base_full])

    clx = sched.get("climax") or {}
    orden = sched["orden"]
    fpre = conf["audio"].get("musica_fade_pre_card_seg", 1.2)  # bajar musica antes del mes
    piezas, t = [], 0.0
    for i, seg in enumerate(orden):
        d = seg["dur"]
        muteado = seg["tipo"] == "card"
        if seg["tipo"] == "voz" and clx and t >= clx["t_ini"] - 0.01 and t < clx["t_fin"] - 0.01:
            muteado = True  # silencio de musica en el climax (Mes 11)
        if muteado:
            piezas.append(silencio(bd, 1000 + i, d))
        else:
            out = os.path.join(bd, f"a_mus_{i:03d}.wav")
            afs = []
            # si el SIGUIENTE es una tarjeta (o es el ultimo tramo): bajar la musica al final
            ultimo = (i + 1 >= len(orden))
            if ultimo or orden[i + 1]["tipo"] == "card":
                fd = min(fpre, d)
                afs.append(f"afade=t=out:st={max(0, d-fd):.3f}:d={fd:.3f}")
            # si el ANTERIOR fue una tarjeta: entrar la musica con un fade suave
            if i > 0 and orden[i - 1]["tipo"] == "card":
                afs.append("afade=t=in:st=0:d=0.8")
            af = (",".join(afs)) if afs else "anull"
            run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-t", f"{d:.3f}", "-i", base_full,
                 "-af", af, "-ar", "48000", "-ac", "2", out])
            piezas.append(out)
        t += d
    return concat_wav(bd, piezas, os.path.join(bd, "mus_cuerpo.wav"))


def construir_sfx(conf, sched, bd):
    """Pista de SFX: impacto en cada tarjeta, silencio en el resto."""
    a = conf["audio"]
    nivel = a.get("sfx_nivel_db", -6.0)
    piezas = []
    for i, seg in enumerate(sched["orden"]):
        d = seg["dur"]
        if seg["tipo"] == "card" and seg.get("sfx"):
            src = os.path.join(RAIZ, seg["sfx"])
            out = os.path.join(bd, f"a_sfx_{i:03d}.wav")
            boost = conf["audio"].get("sfx_boost_db", 2.0)
            # el sfx ya es fuerte; leve realce + limitador. Entra de inmediato (t=0).
            run(["ffmpeg", "-y", "-i", src, "-t", f"{d:.3f}",
                 "-af", f"volume={boost}dB,alimiter=limit=0.97,apad,atrim=0:{d:.3f}",
                 "-ar", "48000", "-ac", "2", out])
            piezas.append(out)
        else:
            piezas.append(silencio(bd, 2000 + i, d))
    return concat_wav(bd, piezas, os.path.join(bd, "sfx_cuerpo.wav"))


def mezclar(conf, video_sin_audio, salida, build_dir):
    sched = json.load(open(os.path.join(build_dir, "schedule.json")))
    total_video = dur(video_sin_audio)
    total_cuerpo = sched["total_cuerpo"]

    voz = construir_voz(conf, sched, build_dir)
    mus = construir_musica(conf, sched, build_dir, total_cuerpo)
    sfx = construir_sfx(conf, sched, build_dir)

    voz_gan = conf["audio"].get("voz_nivel_db", -2.0)
    # voz dominante (loudnorm) + musica + sfx; todo rellenado hasta la duracion del video
    fc = (
        f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume={voz_gan}dB[v];"
        f"[2:a]anull[m];[3:a]anull[s];"
        f"[v][m][s]amix=inputs=3:duration=longest:dropout_transition=0:normalize=0,"
        f"apad,atrim=0:{total_video:.3f}[a]"
    )
    run([
        "ffmpeg", "-y",
        "-i", video_sin_audio, "-i", voz, "-i", mus, "-i", sfx,
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
        "-t", f"{total_video:.3f}", salida,
    ])
    return salida


if __name__ == "__main__":
    conf = json.load(open(os.path.join(RAIZ, "guion.json"), encoding="utf-8"))
    video = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "build", "con_fade.mp4")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RAIZ, "output", "con_audio.mp4")
    mezclar(conf, video, out, os.path.join(RAIZ, "build"))
    print("Audio mezclado ->", out)
