# Changelog

All notable changes to this project are recorded here.

## 1.0.0 - 2026-10-08

First release.

### Added
- Browser app (`index.html`) with a live colour, sharpen and grain preview, a hold-to-compare button and an RU/EN switch.
- Python CLI (`enhancer.py`) built on ffmpeg, with batch input, presets, `--dry-run` and a progress readout.
- One shared filter chain, in the order: deflicker, denoise, deband, frame interpolation, upscale, sharpen, colour, grain.
- Presets: Neutral, AI clean, Cinematic, Crisp and Smooth.
- Upscaling to 1080p, 1440p and 2160p (Lanczos, never scales down).
- Frame-rate conversion to 24, 30, 48 and 60 fps with blend or motion interpolation.
- H.264 output in both versions and H.265 in the CLI.
- Audio is copied untouched when the container allows it.
- MIT licence, README and Russian translations of both documents.
