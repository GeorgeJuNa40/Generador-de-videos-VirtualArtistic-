#!/usr/bin/env python3
"""
Motor de edicion de video para "VirtualArtistic".
Lee guion.json y ensambla el cortometraje con FFmpeg.

Modelo de tiempo: cada segmento tiene un fin ABSOLUTO (hasta_seg) tomado de las
pausas reales de la voz (guion_voz.json). Asi el video queda alineado con la
narracion. Las tarjetas de mes consumen tiempo dentro de esa linea (la voz
sigue sonando por debajo). Cuando faltan clips para cubrir una ventana, cada
clip se ralentiza (tono lento/melancolico) descartando el ultimo segundo, que
es donde se degrada la animacion.

Uso:
    python3 src/edit.py --borrador     # preview rapido (baja calidad)
    python3 src/edit.py                # render final alta calidad + audio
    python3 src/edit.py --solo-video   # sin mezclar audio
"""
import argparse
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUION = os.path.join(RAIZ, "guion.json")
BUILD = os.path.join(RAIZ, "build")
OUTPUT = os.path.join(RAIZ, "output")
CLIPS = os.path.join(RAIZ, "assets", "videos")
FOTOS = os.path.join(RAIZ, "assets", "fotos")
CLEAN_MAX = 4.2  # segundos utiles por clip antes de que se degrade la animacion


def es_foto(nombre):
    return str(nombre).startswith("foto_")


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd[:5]), "...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERROR FFmpeg:\n", r.stderr[-1500:], file=sys.stderr)
        raise SystemExit(1)
    return r


def cfg():
    with open(GUION, encoding="utf-8") as f:
        return json.load(f)


def dur_archivo(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", p],
        capture_output=True, text=True).stdout.strip())


NUEVOS = os.path.join(RAIZ, "assets", "nuevos")


def clip_path(n):
    if es_foto(n):
        return os.path.join(FOTOS, n + ".jpg")
    if str(n).startswith("nuevo_"):
        return os.path.join(NUEVOS, n + ".mp4")
    return os.path.join(CLIPS, n + ".mp4")


def existe(n):
    return not str(n).startswith("PENDIENTE") and os.path.exists(clip_path(n))


def anima_foto(nombre, salida, W, H, FPS, target, borrador, fade_out=0.0, enfasis=False):
    """Ken Burns: zoom lento sobre una foto fija hasta cubrir `target` seg (nitido).
    Opcional: `fade_out` (fundido a negro al final) para suavizar la entrada de un mes."""
    src = clip_path(nombre)
    crf, preset = crf_preset(borrador)
    frames = max(1, int(round(target * FPS)))
    zmax = 1.20 if enfasis else 1.14   # un poco mas de zoom si es la toma de enfasis
    fade = ""
    if fade_out and fade_out > 0.05:
        fade = f",fade=t=out:st={max(0, target-fade_out):.3f}:d={fade_out:.3f}"
    vf = (
        f"scale=-2:{H*2}:flags=lanczos,crop={W*2}:{H*2},"
        f"zoompan=z='min(1+0.0008*on,{zmax})':d={frames}:"
        f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':s={W}x{H}:fps={FPS},"
        f"format=yuv420p{fade}"
    )
    run(["ffmpeg", "-y", "-loop", "1", "-i", src, "-t", f"{target:.3f}",
         "-vf", vf, "-an", "-c:v", "libx264", "-crf", crf, "-preset", preset,
         "-pix_fmt", "yuv420p", salida])


def crf_preset(borrador):
    return ("30", "veryfast") if borrador else ("18", "medium")


# ---------------------------------------------------------------- primitivos

def _enfasis_suffix(target, fade_out, enfasis, W, H):
    """Filtros extra para el clip previo a un mes: leve zoom de enfasis + fundido a negro."""
    extra = ""
    if enfasis:
        # acercamiento lento (push-in) de ~4% para dar enfasis antes de cortar
        z = 1.0 + 0.05 * (1.0)  # objetivo ~1.05 al final
        extra += (f",scale=w=trunc(iw*1.06/2)*2:h=trunc(ih*1.06/2)*2,"
                  f"crop={W}:{H}")
    if fade_out and fade_out > 0.05:
        extra += f",fade=t=out:st={max(0, target-fade_out):.3f}:d={fade_out:.3f}"
    return extra


def normaliza_clip(nombre, salida, W, H, FPS, target, borrador, fade_out=0.0, enfasis=False):
    """Escala a WxH y ajusta el clip a `target` segundos: recorta o ralentiza.
    Opcional: `fade_out` (fundido a negro al final) y `enfasis` (leve zoom) para
    suavizar la entrada de un mes."""
    src = clip_path(nombre)
    usable = CLEAN_MAX
    crf, preset = crf_preset(borrador)
    escala = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}")
    extra = _enfasis_suffix(target, fade_out, enfasis, W, H)
    if target <= usable:
        vf = f"{escala}{extra},fps={FPS},format=yuv420p"
        run(["ffmpeg", "-y", "-i", src, "-t", f"{target:.3f}",
             "-vf", vf, "-an", "-c:v", "libx264", "-crf", crf, "-preset", preset,
             "-pix_fmt", "yuv420p", salida])
    else:
        factor = target / usable
        vf = (f"trim=0:{usable:.3f},{escala},setpts={factor:.4f}*PTS{extra},"
              f"fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-i", src,
             "-vf", vf, "-an", "-t", f"{target:.3f}",
             "-c:v", "libx264", "-crf", crf, "-preset", preset,
             "-pix_fmt", "yuv420p", salida])


def negro(salida, W, H, FPS, dur, borrador):
    crf, preset = crf_preset(borrador)
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur:.3f}",
         "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", crf,
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", salida])


def tarjeta(texto, salida, W, H, FPS, dur, fuente, fondo, color, borrador):
    fondo = fondo.replace("#", "0x")
    tam = int(H * 0.055)
    txt = texto.replace(":", "\\:").replace("'", "")
    # el texto entra y sale con un fundido suave (no golpe seco)
    fi, fo = 0.4, 0.4
    a = f"'if(lt(t,{fi}),t/{fi},if(gt(t,{dur-fo:.2f}),max(0,({dur}-t)/{fo}),1))'"
    draw = (f"drawtext=fontfile='{fuente}':text='{txt}':fontcolor={color}:"
            f"fontsize={tam}:x=(w-text_w)/2:y=(h-text_h)/2:alpha={a}")
    crf, preset = crf_preset(borrador)
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c={fondo}:s={W}x{H}:r={FPS}:d={dur:.3f}",
         "-vf", f"{draw},format=yuv420p", "-c:v", "libx264", "-crf", crf,
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", salida])


def concat(archivos, salida):
    lf = os.path.join(BUILD, "concat.txt")
    with open(lf, "w") as f:
        for p in archivos:
            f.write(f"file '{p}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lf, "-c", "copy", salida])


# ---------------------------------------------------------------- ensamblado

def shots_bloque(W, fill, pins, pin_dur):
    """Devuelve [(clip, dur)] que suman W.
    Con pins: se 'teje' el bloque -> cada clip corre desde su frase hasta la
    frase del siguiente (el primero cubre desde el inicio del bloque).
    Sin pins: reparte los clips de relleno de forma uniforme."""
    pins = sorted(pins, key=lambda x: x[0])
    pins = [(max(0.0, min(off, W - 0.1)), c) for off, c in pins]

    if pins:
        offs = [o for o, c in pins]
        clips = [c for o, c in pins]
        shots = []
        for i, c in enumerate(clips):
            a = 0.0 if i == 0 else offs[i]
            b = offs[i + 1] if i + 1 < len(clips) else W
            shots.append((c, max(0.3, b - a)))
        total = sum(d for _, d in shots)
        shots[-1] = (shots[-1][0], shots[-1][1] + (W - total))
        return shots

    # sin pins: reparto uniforme del relleno (o negro si no hay)
    n = max(1, len(fill))
    share = W / n
    if not fill:
        return [(None, W)]
    return [(fill[i], share) for i in range(len(fill))] or [(None, W)]


def _pool_reuso(conf):
    """Lista ordenada de clips reales disponibles, para rellenar huecos por reuso."""
    pool = []
    for item in conf["timeline"]:
        if item["tipo"] == "bloque":
            for c in item["clips"]:
                if existe(c) and c not in pool:
                    pool.append(c)
    return pool


def construir(conf, borrador, reuso=False):
    W, H, FPS = conf["meta"]["ancho"], conf["meta"]["alto"], conf["meta"]["fps"]
    est = conf["estilo"]
    fuente = os.path.join(RAIZ, est["tarjeta_fuente"])
    pin_dur = est.get("pin_duracion_seg", 4.0)
    os.makedirs(BUILD, exist_ok=True)

    pool = _pool_reuso(conf) if reuso else []
    rr = 0  # indice rotatorio para reuso

    segmentos, cierre_segs, faltantes = [], [], []
    vc = 0.0   # cursor en la VOZ (tiempo de la narracion)
    t = 0.0    # cursor en la linea ENSAMBLADA (con silencios de tarjetas)
    idx = 0
    orden = []      # secuencia de audio en tiempo ensamblado
    climax = None

    for item in conf["timeline"]:
        tt = item["tipo"]

        if tt == "negro":
            dur = item["hasta_seg"] - vc
            out = os.path.join(BUILD, f"s{idx:03d}_negro.mp4")
            negro(out, W, H, FPS, dur, borrador)
            segmentos.append(out)
            orden.append({"tipo": "voz", "dur": round(dur, 3), "voz_ini": round(vc, 3)})
            vc = item["hasta_seg"]; t += dur; idx += 1

        elif tt == "tarjeta":
            dur = item["duracion_seg"]
            out = os.path.join(BUILD, f"s{idx:03d}_{item['id']}.mp4")
            tarjeta(item["texto"], out, W, H, FPS, dur, fuente,
                    est["tarjeta_color_fondo"], est["tarjeta_color_texto"], borrador)
            segmentos.append(out)
            orden.append({"tipo": "card", "dur": round(dur, 3),
                          "sfx": item.get("sfx"), "silencio": item.get("silencio_total", True)})
            t += dur; idx += 1

        elif tt == "bloque":
            ventana = item["hasta_seg"] - vc   # ventana = trozo de VOZ que cubre el bloque
            # pins (clips nuevos) que caen dentro de este bloque -> offset dentro del bloque
            pins_bloque = [(pn["en"] - vc, pn["clip"]) for pn in conf.get("pins", [])
                           if vc - 0.01 <= pn["en"] < item["hasta_seg"] - 0.01]
            shots = shots_bloque(ventana, item["clips"], pins_bloque, pin_dur)
            # la ultima toma antes de un mes lleva fundido a negro + enfasis (menos brusco)
            pre_card = item["id"] != "b_mes_12"
            for si, (c, d) in enumerate(shots):
                ult = pre_card and si == len(shots) - 1
                fout = min(0.5, d * 0.4) if ult else 0.0
                out = os.path.join(BUILD, f"s{idx:03d}_{c or 'negro'}.mp4")
                if c and existe(c) and es_foto(c):
                    anima_foto(c, out, W, H, FPS, d, borrador, fade_out=fout, enfasis=ult)
                elif c and existe(c):
                    normaliza_clip(c, out, W, H, FPS, d, borrador, fade_out=fout, enfasis=ult)
                elif reuso and pool:
                    if c:
                        faltantes.append(c)
                    real = pool[rr % len(pool)]; rr += 1
                    normaliza_clip(real, out, W, H, FPS, d, borrador)
                else:
                    if c:
                        faltantes.append(c)
                    negro(out, W, H, FPS, d, borrador)
                segmentos.append(out); idx += 1
            orden.append({"tipo": "voz", "dur": round(ventana, 3), "voz_ini": round(vc, 3)})
            if item["id"] == "b_mes_11":
                climax = {"t_ini": round(t, 3), "t_fin": round(t + ventana, 3)}
            vc = item["hasta_seg"]; t += ventana

        elif tt == "fundido_negro":
            continue  # se aplica en post

        elif tt == "cierre":
            cierre_segs = cierre(item, conf, borrador, idx)
            idx += len(cierre_segs)

    schedule = {"orden": orden, "total_cuerpo": round(t, 3),
                "voz_total": round(vc, 3), "climax": climax}
    with open(os.path.join(BUILD, "schedule.json"), "w") as f:
        json.dump(schedule, f, indent=2)
    return segmentos, cierre_segs, faltantes


def _beat_texto(t1, t2, salida, W, H, FPS, dur, fuente, borrador):
    """Un 'beat' de cierre: dos lineas de texto blanco delgado con fade in/out."""
    crf, preset = crf_preset(borrador)
    tam = int(H * 0.032)
    a = f"'if(lt(t,0.6),t/0.6,if(gt(t,{dur-0.6:.2f}),({dur}-t)/0.6,1))'"
    t1 = t1.replace(":", "\\:").replace("'", "")
    t2 = t2.replace(":", "\\:").replace("'", "")
    draw = (
        f"drawtext=fontfile='{fuente}':text='{t1}':fontcolor=white:fontsize={tam}:"
        f"x=(w-text_w)/2:y=h/2-{tam}:alpha={a},"
        f"drawtext=fontfile='{fuente}':text='{t2}':fontcolor=white:fontsize={tam}:"
        f"x=(w-text_w)/2:y=h/2+{int(tam*0.4)}:alpha={a}"
    )
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur:.3f}",
         "-vf", f"{draw},format=yuv420p", "-c:v", "libx264", "-crf", crf,
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", salida])


def cierre(item, conf, borrador, idx):
    W, H, FPS = conf["meta"]["ancho"], conf["meta"]["alto"], conf["meta"]["fps"]
    fuente = os.path.join(RAIZ, "assets", "fuentes", "cierre.ttf")   # texto final (delgado)
    marca = os.path.join(RAIZ, "assets", "fuentes", "tarjeta.ttf")    # nombre marca (bold)
    crf, preset = crf_preset(borrador)
    outs = []

    # 1) Primera frase: "Hay otra version de la historia / donde el mes 12 no termina asi."
    b1 = os.path.join(BUILD, f"s{idx:03d}_cierre_beat1.mp4")
    _beat_texto(item.get("beat1_1", ""), item.get("beat1_2", ""), b1,
                W, H, FPS, item["negro_beat1_seg"], fuente, borrador)
    outs.append(b1)
    idx += 1

    # 1b) Segunda frase (opcional): "El tiempo no se recupera. / Tu crecimiento, si."
    if item.get("beat2_1"):
        b2 = os.path.join(BUILD, f"s{idx:03d}_cierre_beat2.mp4")
        _beat_texto(item.get("beat2_1", ""), item.get("beat2_2", ""), b2,
                    W, H, FPS, item.get("negro_beat2_seg", 3.5), fuente, borrador)
        outs.append(b2)
        idx += 1

    # 2) Logo. Si hay logo_imagen, se usa la imagen ORIGINAL a pantalla completa;
    #    si no, se arma la version dark (icono + nombre).
    dur2 = item["negro_logo_seg"]
    out2 = os.path.join(BUILD, f"s{idx:03d}_cierre_logo.mp4")
    logo_img = os.path.join(RAIZ, item.get("logo_imagen", "")) if item.get("logo_imagen") else ""
    if logo_img and os.path.exists(logo_img):
        # llenar el ancho y recortar (quita las barras negras de la imagen -> logo mas grande)
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"fade=t=in:st=0:d=0.7,fade=t=out:st={dur2-0.6:.2f}:d=0.6,format=yuv420p"
        )
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", logo_img,
             "-vf", vf, "-t", f"{dur2:.3f}",
             "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
             "-pix_fmt", "yuv420p", out2])
    else:
        icono = os.path.join(RAIZ, item.get("logo_icono", "assets/logo/icono.png"))
        nombre = item.get("logo_nombre", "").replace("'", "")
        tagline = item.get("logo_tagline", "").replace("&", "\\&").replace("'", "")
        fc = (
            f"[1:v]scale=440:-1[ic];"
            f"[0:v][ic]overlay=(W-w)/2:(H-h)/2-140[b];"
            f"[b]drawtext=fontfile='{marca}':text='{nombre}':fontcolor=white:fontsize=76:"
            f"x=(w-text_w)/2:y=h/2+120[b2];"
            f"[b2]drawtext=fontfile='{fuente}':text='{tagline}':fontcolor=0xB0B0B0:fontsize=34:"
            f"x=(w-text_w)/2:y=h/2+210,fade=t=in:st=0:d=0.7,fade=t=out:st={dur2-0.6:.2f}:d=0.6,format=yuv420p"
        )
        run(["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur2:.3f}",
             "-i", icono, "-filter_complex", fc,
             "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-t", f"{dur2:.3f}", out2])
    outs.append(out2)
    idx += 1

    # 3) Negro final
    out3 = os.path.join(BUILD, f"s{idx:03d}_cierre_negro.mp4")
    negro(out3, W, H, FPS, item["negro_final_seg"], borrador)
    outs.append(out3)
    return outs


def aplica_fundido(entrada, salida, conf):
    fade = next((i for i in conf["timeline"] if i["tipo"] == "fundido_negro"), None)
    if not fade:
        os.replace(entrada, salida); return
    d = fade["duracion_seg"]
    if fade.get("auto_final"):
        st = max(0.0, dur_archivo(entrada) - d)   # fundido en el ultimo tramo del cuerpo
    else:
        st = fade["en_seg"]
    run(["ffmpeg", "-y", "-i", entrada,
         "-vf", f"fade=t=out:st={st:.3f}:d={d},format=yuv420p",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", salida])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-video", action="store_true")
    ap.add_argument("--borrador", action="store_true")
    ap.add_argument("--reuso", action="store_true",
                    help="rellena clips faltantes reusando los reales (para preview)")
    ap.add_argument("--sin-subs", action="store_true", help="no quemar subtitulos")
    args = ap.parse_args()

    conf = cfg()
    os.makedirs(BUILD, exist_ok=True); os.makedirs(OUTPUT, exist_ok=True)

    print("== Construyendo segmentos (alineados a la voz) ==")
    segmentos, cierre_segs, faltantes = construir(conf, args.borrador, reuso=args.reuso)

    print("== Uniendo cuerpo con cortes secos ==")
    cuerpo = os.path.join(BUILD, "cuerpo.mp4")
    concat(segmentos, cuerpo)

    print("== Fundido a negro (solo al final del cuerpo) ==")
    cuerpo_fade = os.path.join(BUILD, "cuerpo_fade.mp4")
    aplica_fundido(cuerpo, cuerpo_fade, conf)

    print("== Pegando el cierre despues del fundido ==")
    con_fade = os.path.join(BUILD, "con_fade.mp4")
    concat([cuerpo_fade] + cierre_segs, con_fade)

    if args.solo_video:
        destino = os.path.join(OUTPUT, "cortometraje_sin_audio.mp4")
        os.replace(con_fade, destino)
    else:
        print("== Mezclando audio (voz + musica) ==")
        from audio import mezclar
        con_audio = os.path.join(BUILD, "con_audio.mp4")
        mezclar(conf, con_fade, con_audio, BUILD)

        destino = os.path.join(OUTPUT, "borrador.mp4" if args.borrador else "cortometraje.mp4")
        if args.sin_subs:
            os.replace(con_audio, destino)
        else:
            print("== Generando y quemando subtitulos ==")
            import subtitulos
            subtitulos.main()
            ass = os.path.join(BUILD, "subtitulos.ass").replace(":", "\\:")
            crf, preset = crf_preset(args.borrador)
            run(["ffmpeg", "-y", "-i", con_audio,
                 "-vf", f"subtitles='{ass}'",
                 "-c:v", "libx264", "-crf", crf, "-preset", preset,
                 "-pix_fmt", "yuv420p", "-c:a", "copy", destino])

    # Ajuste opcional a una duracion maxima (p.ej. limite de 3 min de Instagram).
    # Comprime video y audio por igual, conservando la sincronia.
    maxd = conf["meta"].get("duracion_maxima_seg")
    if maxd and not args.solo_video:
        actual = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", destino],
            capture_output=True, text=True).stdout.strip())
        if actual > maxd:
            objetivo = maxd - 0.5
            factor = actual / objetivo
            print(f"== Ajustando duracion {actual:.1f}s -> {objetivo:.1f}s (x{factor:.4f}) ==")
            tmp = os.path.join(BUILD, "ajustado.mp4")
            run(["ffmpeg", "-y", "-i", destino,
                 "-filter_complex", f"[0:v]setpts=PTS/{factor:.5f}[v];[0:a]atempo={factor:.5f}[a]",
                 "-map", "[v]", "-map", "[a]",
                 "-c:v", "libx264", "-crf", "18" if not args.borrador else "26",
                 "-preset", "medium", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "256k", tmp])
            os.replace(tmp, destino)

    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nokey=1:noprint_wrappers=1", destino],
                         capture_output=True, text=True).stdout.strip()
    print(f"\nListo -> {destino}\nDuracion: {dur}s (voz {conf['meta']['duracion_objetivo_seg']}s)")
    if faltantes:
        print(f"\nClips PENDIENTES (negro provisional): {', '.join(sorted(set(faltantes)))}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(RAIZ, "src"))
    main()
