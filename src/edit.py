#!/usr/bin/env python3
"""
Motor de edicion de video para "VirtualArtistic".
Lee guion.json y ensambla el cortometraje con FFmpeg.

Reglas clave (ver guion.json):
- Formato vertical 1080x1920 @ 30fps.
- Cortes SIEMPRE secos, salvo el fundido a negro definido en el timeline.
- Cada clip se escala/recorta a 1080x1920 y se corta a su duracion,
  descartando el ultimo segundo del render original (donde se degrada).
- Tarjetas de mes: negro puro + texto blanco bold centrado, sin animacion.
- Los primeros segundos (intro_negro) son pantalla negra: solo voz en off.
- Audio: la voz manda; la musica siempre por debajo, con ventana(s) de silencio.

Uso:
    python3 src/edit.py                # render completo (usa lo que haya)
    python3 src/edit.py --solo-video   # solo pista de video (sin audio)
    python3 src/edit.py --cards         # solo (re)genera las tarjetas
    python3 src/edit.py --borrador      # render rapido de baja calidad (preview)
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


def run(cmd, **kw):
    """Ejecuta un comando y aborta con mensaje claro si falla."""
    print("  $", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "")
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print("ERROR en FFmpeg:\n", r.stderr[-1500:], file=sys.stderr)
        raise SystemExit(1)
    return r


def cfg():
    with open(GUION, encoding="utf-8") as f:
        return json.load(f)


def clip_path(nombre):
    return os.path.join(CLIPS, nombre + ".mp4")


def existe_clip(nombre):
    return not nombre.startswith("PENDIENTE") and os.path.exists(clip_path(nombre))


# ---------------------------------------------------------------- primitivos

def normaliza_clip(nombre, salida, W, H, FPS, dur, descartar_final, borrador):
    """Escala a WxH (cubrir+recortar), fija fps y corta a `dur` segundos."""
    src = clip_path(nombre)
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={W}:{H},fps={FPS},format=yuv420p"
    )
    crf = "30" if borrador else "18"
    preset = "veryfast" if borrador else "medium"
    run([
        "ffmpeg", "-y", "-i", src,
        "-t", f"{dur:.3f}",
        "-vf", vf, "-an",
        "-c:v", "libx264", "-crf", crf, "-preset", preset,
        "-pix_fmt", "yuv420p",
        salida,
    ])


def negro(salida, W, H, FPS, dur, borrador):
    """Genera un clip de pantalla negra pura de `dur` segundos (sin audio)."""
    crf = "30" if borrador else "18"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur:.3f}",
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}",
        salida,
    ])


def tarjeta(texto, salida, W, H, FPS, dur, fuente, color_fondo, color_texto, borrador):
    """Tarjeta de mes: fondo negro puro + texto centrado bold. Corte seco, sin animacion."""
    fondo = color_fondo.replace("#", "0x")
    tam = int(H * 0.055)  # ~105px en 1920 de alto
    txt = texto.replace(":", "\\:").replace("'", "")
    draw = (
        f"drawtext=fontfile='{fuente}':text='{txt}':"
        f"fontcolor={color_texto}:fontsize={tam}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2"
    )
    crf = "30" if borrador else "18"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={fondo}:s={W}x{H}:r={FPS}:d={dur:.3f}",
        "-vf", f"{draw},format=yuv420p",
        "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}",
        salida,
    ])


def concat_demuxer(lista_archivos, salida):
    """Une segmentos con corte seco usando el concat demuxer (sin recodificar)."""
    listfile = os.path.join(BUILD, "concat.txt")
    with open(listfile, "w") as f:
        for p in lista_archivos:
            f.write(f"file '{p}'\n")
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
        "-c", "copy", salida,
    ])


# ---------------------------------------------------------------- ensamblado

def construir_segmentos(conf, borrador):
    """Recorre el timeline y genera cada segmento normalizado. Devuelve la lista ordenada."""
    W = conf["meta"]["ancho"]
    H = conf["meta"]["alto"]
    FPS = conf["meta"]["fps"]
    est = conf["estilo"]
    descartar = est["recorte_final_descartar_seg"]
    dur_def = est["clip_duracion_max_seg"] - descartar + est["recorte_final_descartar_seg"]
    # duracion por defecto de cada clip (dentro del rango permitido)
    dur_clip = min(est["clip_duracion_max_seg"], 4.0)
    fuente = os.path.join(RAIZ, est["tarjeta_fuente"])

    os.makedirs(BUILD, exist_ok=True)
    segmentos = []
    idx = 0
    faltantes = []

    for item in conf["timeline"]:
        t = item["tipo"]
        if t == "negro":
            out = os.path.join(BUILD, f"seg_{idx:03d}_negro.mp4")
            negro(out, W, H, FPS, item["duracion_seg"], borrador)
            segmentos.append(out); idx += 1

        elif t == "tarjeta":
            out = os.path.join(BUILD, f"seg_{idx:03d}_{item['id']}.mp4")
            tarjeta(item["texto"], out, W, H, FPS, item["duracion_seg"],
                    fuente, est["tarjeta_color_fondo"], est["tarjeta_color_texto"], borrador)
            segmentos.append(out); idx += 1

        elif t == "bloque":
            for c in item["clips"]:
                if existe_clip(c):
                    out = os.path.join(BUILD, f"seg_{idx:03d}_{c}.mp4")
                    normaliza_clip(c, out, W, H, FPS, dur_clip, descartar, borrador)
                    segmentos.append(out); idx += 1
                else:
                    # marcador negro para clips aun no entregados (solo en borrador)
                    faltantes.append(c)
                    out = os.path.join(BUILD, f"seg_{idx:03d}_FALTA_{c}.mp4")
                    negro(out, W, H, FPS, dur_clip, borrador)
                    segmentos.append(out); idx += 1

        elif t == "fundido_negro":
            # se aplica en la mezcla final; aqui no genera segmento propio
            continue

        elif t == "cierre":
            # cierre: texto final delgado + logo + negro
            outs = construir_cierre(item, conf, borrador, idx)
            segmentos.extend(outs); idx += len(outs)

    return segmentos, faltantes


def construir_cierre(item, conf, borrador, idx):
    """Negro con texto blanco delgado, luego logo, luego negro."""
    W = conf["meta"]["ancho"]; H = conf["meta"]["alto"]; FPS = conf["meta"]["fps"]
    fuente = os.path.join(RAIZ, "assets", "fuentes", "cierre.ttf")
    outs = []

    # 1) texto final delgado centrado
    out1 = os.path.join(BUILD, f"seg_{idx:03d}_cierre_texto.mp4")
    tam = int(H * 0.030)
    txt = item.get("texto_final", "").replace(":", "\\:").replace("'", "")
    draw = (f"drawtext=fontfile='{fuente}':text='{txt}':fontcolor=white:"
            f"fontsize={tam}:x=(w-text_w)/2:y=(h-text_h)/2")
    crf = "30" if borrador else "18"
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={item['negro_texto_seg']:.3f}",
         "-vf", f"{draw},format=yuv420p",
         "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-t", f"{item['negro_texto_seg']:.3f}", out1])
    outs.append(out1)

    # 2) logo centrado sobre negro (si existe)
    logo = os.path.join(RAIZ, item.get("logo", ""))
    out2 = os.path.join(BUILD, f"seg_{idx+1:03d}_cierre_logo.mp4")
    if os.path.exists(logo):
        run(["ffmpeg", "-y",
             "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={item['negro_logo_seg']:.3f}",
             "-i", logo,
             "-filter_complex",
             "[1:v]scale=iw*0.5:-1[lg];[0:v][lg]overlay=(W-w)/2:(H-h)/2,format=yuv420p",
             "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-t", f"{item['negro_logo_seg']:.3f}", out2])
    else:
        negro(out2, W, H, FPS, item["negro_logo_seg"], borrador)
    outs.append(out2)

    # 3) negro final
    out3 = os.path.join(BUILD, f"seg_{idx+2:03d}_cierre_negro.mp4")
    negro(out3, W, H, FPS, item["negro_final_seg"], borrador)
    outs.append(out3)
    return outs


def aplica_fundido(entrada, salida, conf):
    """Aplica el unico fundido a negro definido en el timeline (2:13)."""
    fade = next((i for i in conf["timeline"] if i["tipo"] == "fundido_negro"), None)
    if not fade:
        os.replace(entrada, salida); return
    ini = fade["en_seg"]; dur = fade["duracion_seg"]
    run(["ffmpeg", "-y", "-i", entrada,
         "-vf", f"fade=t=out:st={ini}:d={dur},format=yuv420p",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", salida])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-video", action="store_true", help="solo pista de video, sin audio")
    ap.add_argument("--borrador", action="store_true", help="render rapido de preview")
    args = ap.parse_args()

    conf = cfg()
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(OUTPUT, exist_ok=True)

    print("== Construyendo segmentos ==")
    segmentos, faltantes = construir_segmentos(conf, args.borrador)

    print("== Uniendo con cortes secos ==")
    unido = os.path.join(BUILD, "unido.mp4")
    concat_demuxer(segmentos, unido)

    print("== Aplicando fundido a negro final ==")
    con_fade = os.path.join(BUILD, "con_fade.mp4")
    aplica_fundido(unido, con_fade, conf)

    destino = os.path.join(OUTPUT, "borrador.mp4" if args.borrador else "cortometraje.mp4")
    os.replace(con_fade, destino)

    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", destino],
        capture_output=True, text=True).stdout.strip()
    print(f"\nListo -> {destino}")
    print(f"Duracion: {dur}s (objetivo {conf['meta']['duracion_objetivo_seg']}s)")
    if faltantes:
        print(f"\nClips PENDIENTES (marcados con negro): {', '.join(faltantes)}")


if __name__ == "__main__":
    main()
