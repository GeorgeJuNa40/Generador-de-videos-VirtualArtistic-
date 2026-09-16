#!/usr/bin/env python3
"""Extrae el 'mapa de ritmo' de la voz en off: segmentos de habla separados por
pausas naturales. Estos segmentos son los puntos de corte guia para el montaje."""
import subprocess, re, json, os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
voz = os.path.join(RAIZ, "assets", "voz", "voz_off.wav")

def dur(p):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nokey=1:noprint_wrappers=1",p],capture_output=True,text=True)
    return float(r.stdout.strip())

def main(noise="-30dB", d="0.6"):
    total = dur(voz)
    out = subprocess.run(["ffmpeg","-i",voz,"-af",
        f"silencedetect=noise={noise}:d={d}","-f","null","-"],
        capture_output=True,text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends   = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    # construir segmentos de habla (entre pausas)
    segs, cursor = [], 0.0
    for s, e in zip(starts, ends):
        if s > cursor + 0.15:
            segs.append({"ini": round(cursor,2), "fin": round(s,2),
                         "dur": round(s-cursor,2)})
        cursor = e
    if cursor < total - 0.15:
        segs.append({"ini": round(cursor,2), "fin": round(total,2),
                     "dur": round(total-cursor,2)})
    data = {"duracion_voz": round(total,2), "n_segmentos": len(segs), "segmentos": segs}
    json.dump(data, open(os.path.join(RAIZ,"guion_voz.json"),"w"),
              ensure_ascii=False, indent=2)
    for i,s in enumerate(segs):
        print(f"  seg {i:02d}  [{s['ini']:6.2f} -> {s['fin']:6.2f}]  ({s['dur']:.1f}s)")
    print(f"\nVoz total: {total:.1f}s | {len(segs)} segmentos de habla")

if __name__ == "__main__":
    main()
