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
    """Musica combinada continua que se calla en tarjetas y en el bloque climax,
    con una capa de TENSION que construye hacia el clima."""
    a = conf["audio"]
    nivel = a["musica_nivel_db"]
    clx = sched.get("climax") or {}

    # 1) cama base: combinar varias pistas (mas cuerpo/dramatismo) o una sola
    combinar = a.get("musica_combinar") or [a["musica_base"]]
    base_full = os.path.join(bd, "base_full.wav")
    cmd = ["ffmpeg", "-y"]
    for tr in combinar:
        cmd += ["-stream_loop", "-1", "-i", os.path.join(RAIZ, tr)]
    if len(combinar) == 1:
        fc = f"[0:a]volume={nivel}dB[out]"
    else:
        pre = "".join(f"[{i}:a]volume={-3.0*i:.1f}dB[a{i}];" for i in range(len(combinar)))
        mix = "".join(f"[a{i}]" for i in range(len(combinar)))
        fc = pre + f"{mix}amix=inputs={len(combinar)}:normalize=0[mx];[mx]volume={nivel}dB[out]"
    cmd += ["-filter_complex", fc, "-map", "[out]", "-t", f"{total:.3f}",
            "-ar", "48000", "-ac", "2", base_full]
    run(cmd)

    # 2) capa de tension que entra ~18s antes del climax y crece
    tension = a.get("musica_tension")
    if tension and clx:
        ov = min(18.0, clx["t_ini"])
        ini = max(0.0, clx["t_ini"] - ov)
        base_dram = os.path.join(bd, "base_dram.wav")
        ten = os.path.join(RAIZ, tension)
        fc2 = (
            f"[1:a]atrim=0:{ov:.2f},adelay={int(ini*1000)}|{int(ini*1000)},"
            f"volume={nivel+4:.1f}dB,afade=t=in:st={ini:.2f}:d=3,"
            f"afade=t=out:st={clx['t_ini']-0.4:.2f}:d=0.4[ten];"
            f"[0:a][ten]amix=inputs=2:normalize=0[out]"
        )
        run(["ffmpeg", "-y", "-i", base_full, "-i", ten,
             "-filter_complex", fc2, "-map", "[out]", "-t", f"{total:.3f}",
             "-ar", "48000", "-ac", "2", base_dram])
        base_full = base_dram

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


def construir_sfx(conf, sched, bd, total):
    """Pista de SFX del cuerpo: cada sonido de mes se coloca con ADELANTO (lead)
    para que su golpe caiga justo en la entrada de la tarjeta (el 'build' suena
    sobre el oscurecimiento del clip previo)."""
    a = conf["audio"]
    boost = a.get("sfx_boost_db", -3.0)
    lead = a.get("sfx_lead_seg", 1.5)
    # posiciones (tiempo ensamblado) de cada tarjeta con sfx
    starts, t = [], 0.0
    src = None
    for seg in sched["orden"]:
        if seg["tipo"] == "card" and seg.get("sfx"):
            starts.append(max(0.0, t - lead)); src = os.path.join(RAIZ, seg["sfx"])
        t += seg["dur"]
    out = os.path.join(bd, "sfx_cuerpo.wav")
    if not starts or not src:
        return silencio(bd, 9000, total) if False else _sfx_silencio(bd, total, out)
    # base de silencio + cada sfx retrasado (adelay) y mezclado
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    for _ in starts:
        cmd += ["-i", src]
    fil = [f"[0:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS[base]"]
    labels = ["[base]"]
    for i, st in enumerate(starts, start=1):
        ms = int(round(st * 1000))
        fil.append(f"[{i}:a]volume={boost}dB,adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    fil.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,"
               f"atrim=0:{total:.3f}[out]")
    cmd += ["-filter_complex", ";".join(fil), "-map", "[out]", "-t", f"{total:.3f}",
            "-ar", "48000", "-ac", "2", out]
    run(cmd)
    return out


def _sfx_silencio(bd, total, out):
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", out])
    return out


def mezclar(conf, video_sin_audio, salida, build_dir):
    sched = json.load(open(os.path.join(build_dir, "schedule.json")))
    total_video = dur(video_sin_audio)
    total_cuerpo = sched["total_cuerpo"]

    voz = construir_voz(conf, sched, build_dir)
    mus = construir_musica(conf, sched, build_dir, total_cuerpo)
    sfx = construir_sfx(conf, sched, build_dir, total_cuerpo)

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
