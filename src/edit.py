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


def clip_path(n):
    if es_foto(n):
        return os.path.join(FOTOS, n + ".jpg")
    return os.path.join(CLIPS, n + ".mp4")


def existe(n):
    return not str(n).startswith("PENDIENTE") and os.path.exists(clip_path(n))


def anima_foto(nombre, salida, W, H, FPS, target, borrador):
    """Ken Burns: zoom lento sobre una foto fija hasta cubrir `target` seg (nitido)."""
    src = clip_path(nombre)
    crf, preset = crf_preset(borrador)
    frames = max(1, int(round(target * FPS)))
    # sobre-escala para dar margen al zoom y evitar tembleque
    vf = (
        f"scale=-2:{H*2}:flags=lanczos,crop={W*2}:{H*2},"
        f"zoompan=z='min(1+0.0008*on,1.14)':d={frames}:"
        f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':s={W}x{H}:fps={FPS},"
        f"format=yuv420p"
    )
    run(["ffmpeg", "-y", "-loop", "1", "-i", src, "-t", f"{target:.3f}",
         "-vf", vf, "-an", "-c:v", "libx264", "-crf", crf, "-preset", preset,
         "-pix_fmt", "yuv420p", salida])


def crf_preset(borrador):
    return ("30", "veryfast") if borrador else ("18", "medium")


# ---------------------------------------------------------------- primitivos

def normaliza_clip(nombre, salida, W, H, FPS, target, borrador):
    """Escala a WxH y ajusta el clip a `target` segundos: recorta o ralentiza."""
    src = clip_path(nombre)
    usable = CLEAN_MAX
    crf, preset = crf_preset(borrador)
    escala = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}")
    if target <= usable:
        # recorte simple desde el inicio
        vf = f"{escala},fps={FPS},format=yuv420p"
        run(["ffmpeg", "-y", "-i", src, "-t", f"{target:.3f}",
             "-vf", vf, "-an", "-c:v", "libx264", "-crf", crf, "-preset", preset,
             "-pix_fmt", "yuv420p", salida])
    else:
        # ralenti: tomar `usable` seg limpios y estirarlos a `target`
        factor = target / usable
        vf = (f"trim=0:{usable:.3f},{escala},setpts={factor:.4f}*PTS,"
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
    draw = (f"drawtext=fontfile='{fuente}':text='{txt}':fontcolor={color}:"
            f"fontsize={tam}:x=(w-text_w)/2:y=(h-text_h)/2")
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
            clips = item["clips"]
            n = len(clips)
            share = ventana / n
            for c in clips:
                out = os.path.join(BUILD, f"s{idx:03d}_{c}.mp4")
                if existe(c) and es_foto(c):
                    anima_foto(c, out, W, H, FPS, share, borrador)
                elif existe(c):
                    normaliza_clip(c, out, W, H, FPS, share, borrador)
                elif reuso and pool:
                    faltantes.append(c)
                    real = pool[rr % len(pool)]; rr += 1
                    normaliza_clip(real, out, W, H, FPS, share, borrador)
                else:
                    faltantes.append(c)
                    negro(out, W, H, FPS, share, borrador)
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

    # 1a) Primer beat: "Hay otra version de la historia / donde el mes 12 no termina asi."
    b1 = os.path.join(BUILD, f"s{idx:03d}_cierre_beat1.mp4")
    _beat_texto(item.get("beat1_1", ""), item.get("beat1_2", ""), b1,
                W, H, FPS, item["negro_beat1_seg"], fuente, borrador)
    outs.append(b1)

    # 1b) Segundo beat: "El tiempo no se recupera. / Tu crecimiento, si."
    b2 = os.path.join(BUILD, f"s{idx+1:03d}_cierre_beat2.mp4")
    _beat_texto(item.get("beat2_1", ""), item.get("beat2_2", ""), b2,
                W, H, FPS, item["negro_beat2_seg"], fuente, borrador)
    outs.append(b2)
    idx += 1  # ya consumimos un indice extra

    # 2) Logo: icono a color sobre negro + nombre (blanco) + tagline (gris), con fade
    dur2 = item["negro_logo_seg"]
    icono = os.path.join(RAIZ, item.get("logo_icono", "assets/logo/icono.png"))
    nombre = item.get("logo_nombre", "").replace("'", "")
    tagline = item.get("logo_tagline", "").replace("&", "\\&").replace("'", "")
    out2 = os.path.join(BUILD, f"s{idx+1:03d}_cierre_logo.mp4")
    if os.path.exists(icono):
        fexpr = f"'if(lt(t,0.7),t/0.7,if(gt(t,{dur2-0.6:.2f}),({dur2}-t)/0.6,1))'"
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
    else:
        negro(out2, W, H, FPS, dur2, borrador)
    outs.append(out2)

    # 3) Negro final
    out3 = os.path.join(BUILD, f"s{idx+2:03d}_cierre_negro.mp4")
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
