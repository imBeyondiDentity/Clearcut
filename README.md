# Enhancer

Sharpen, clean up and colour-grade video in one pass. There are two ways to use it, and both share the same filter chain, so they give the same look:

- **Browser app** (`index.html`): runs entirely on your device. Nothing is uploaded.
- **Python CLI** (`enhancer.py`): a thin wrapper around ffmpeg. Faster, handles big files, and can process several clips at once.

[Русская версия](README_ru.md)

## What it does

| Group | Controls |
| --- | --- |
| Size and smoothness | Upscale to 1080p, 1440p or 2160p (Lanczos, never scales down); frame-rate conversion to 24, 30, 48 or 60 fps with blend or motion interpolation |
| Clean-up | Denoise, sharpen, deflicker, deband |
| Colour | Contrast, brightness, saturation, vibrance, warmth |
| Look | Film grain |
| Output | H.264 quality (CRF) and encode speed; H.265 in the CLI |

Presets: **Neutral**, **AI clean** (for soft, slightly plastic AI-generated clips), **Cinematic**, **Crisp** and **Smooth**.

The filters are classic ffmpeg filters (`hqdn3d`, `unsharp`, `eq`, `minterpolate` and so on). They tighten and tidy a clip, but they do not invent new detail the way a neural upscaler does.

## Browser version

Open `index.html` (or the GitHub Pages site), choose a video, pick a preset or move the sliders, then press **Enhance**.

- The live preview shows colour, sharpening and grain. Hold **Hold to compare** to see the original.
- Denoise, upscale and frame rate are applied on export.
- The video engine (ffmpeg.wasm) is downloaded from a CDN the first time you press **Enhance**, so you need to be online once.
- The browser engine is single-threaded. Keep clips short (under about 300 MB), and avoid motion interpolation and 4K there. Use the CLI for those.

## Python CLI

Requirements: Python 3.9 or newer, plus `ffmpeg` and `ffprobe` on your `PATH`. There are no Python packages to install.

```
python enhancer.py clip.mp4
python enhancer.py clip.mp4 --preset ai-clean --height 1080
python enhancer.py a.mp4 b.mp4 --preset crisp
python enhancer.py clip.mp4 --fps 60 --interp motion --denoise 1
python enhancer.py clip.mp4 --preset cinematic --codec h265 --crf 20
python enhancer.py clip.mp4 --preset ai-clean --dry-run
```

The result is saved next to the original as `<name>_enhanced.mp4`, or wherever `-o` points when you give a single input. Options you pass override the preset.

| Option | Range | Notes |
| --- | --- | --- |
| `--preset` | neutral, ai-clean, cinematic, crisp, smooth | `--list-presets` shows the values |
| `--height` / `--scale` | e.g. 1080 / 2 | Only scales up |
| `--fps` | e.g. 60 | |
| `--interp` | blend, motion | motion is slow but smoother |
| `--denoise` | 0 to 10 | |
| `--sharpen` | 0 to 2 | |
| `--deflicker`, `--deband` | on or off | `--no-deflicker` turns a preset value off |
| `--contrast`, `--brightness`, `--saturation`, `--vibrance`, `--warmth` | -100 to 100 | |
| `--grain` | 0 to 40 | |
| `--crf` | 14 to 28 | lower is better quality |
| `--codec` | h264, h265 | |
| `--x264-preset` | ultrafast to veryslow | default `medium` |
| `--dry-run` | | prints the ffmpeg command and stops |

Audio is copied untouched when it is AAC, MP3 or ALAC. Anything else is re-encoded to AAC at 320 kbps.

## Tips

- For clips straight out of an AI video generator, start with **AI clean**, then nudge sharpen and grain to taste. A little grain hides the plastic look.
- Denoise before you sharpen, which is the order the chain already uses. Pushing both high makes smearing worse.
- Frame interpolation can warp fast motion and fine patterns. Check the result before using it.

## Licence

MIT. See [LICENSE](LICENSE).
