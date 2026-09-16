# Generador de videos — VirtualArtistic

Motor de edición de video por código (FFmpeg + Python) para el cortometraje
**"12 meses / Un millón"**: historia narrativa en animación 2D, vertical 9:16.

## Qué hace

Toma el material en bruto (clips animados, voz en off, música) y lo ensambla
siguiendo un guion editable (`guion.json`), respetando reglas de montaje:
cortes secos, tarjetas de mes, intro en negro, niveles de audio y el único
fundido a negro final.

## Especificaciones del video

| Parámetro | Valor |
|---|---|
| Duración objetivo | 2:22 (142 s) |
| Formato | Vertical 9:16 · 1080×1920 · 30 fps |
| Estilo | Cinematográfico, lento, melancólico. Cortes secos. |
| Transiciones | Siempre corte seco (única excepción: fundido a negro en 2:13) |
| Intro | Primeros ~11 s en pantalla negra, solo voz en off (intencional) |

## Estructura del proyecto

```
guion.json          # El "timeline" editable: orden de clips, tarjetas, tiempos, audio
src/edit.py         # Motor de edición (lee guion.json y renderiza con FFmpeg)
assets/
  videos/           # Clips normalizados (clip_01.mp4 … clip_21.mp4)
  voz/              # voz_off.wav  (voz en off — PENDIENTE)
  musica/           # musica.wav   (música de fondo — PENDIENTE)
  logo/             # logo.png     (para el cierre — PENDIENTE)
  fuentes/          # tarjeta.ttf (tarjetas mes) · cierre.ttf (texto final)
build/              # Segmentos intermedios (se regeneran; ignorados por git)
output/             # Render final: cortometraje.mp4
```

## Cómo se usa

```bash
python3 src/edit.py --borrador   # preview rápido de baja calidad
python3 src/edit.py              # render final en alta calidad
```

## Estado actual del material

- [x] 10 de 21 clips animados (importados y normalizados)
- [ ] 11 clips restantes (clip_11 … clip_21)
- [ ] Voz en off (`assets/voz/voz_off.wav`) — **crítica: define el ritmo del corte**
- [ ] Música de fondo (`assets/musica/musica.wav`)
- [ ] Logo de cierre y texto final

## Reglas de audio (en `guion.json`)

- Voz: pista principal, nunca por debajo de -6 dB.
- Música: siempre por debajo de la voz (-18 a -22 dB).
- Silencio total de música entre 1:40 y 1:53 (bloque "Mes 11"), el punto clave.
