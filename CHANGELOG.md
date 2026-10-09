# Changelog

All notable changes to this project are recorded here.

## 1.1.0 - 2026-10-09

### Added
- Browser "black box": the state of a run is saved every second, so a dead tab is detected on the next load.
- Crash banner and `CRASHREPORT.txt` download, plus a Diagnostics card with Self-check, Download report and Copy report.
- Self-check that encodes a tiny test clip through the current filter chain.
- Memory estimate and a warning for heavy settings, and a stall warning when the encoder stops responding.
- CLI `CRASHREPORT.txt` for ffprobe or ffmpeg failures and unexpected errors.

### Changed
- Redesigned page to match the Trio and Airband style.
- Lighter encoder settings for the Best speed in the browser, to use less memory.

### Fixed
- Reset now clears everything, and the same file can be chosen again.
- Engine start-up error "failed to import ffmpeg-core.js" (the module core is tried first).
- The engine is restarted after a crash instead of being reused.
- Progress listeners no longer stack up over repeated runs.
- CLI could hang when ffmpeg wrote a lot to stderr.
- CLI showed a raw traceback for unreadable files.

## 1.0.0 - 2026-10-08

First release.

### Added
- Browser app (`index.html`) with a live colour, sharpen and grain preview, a hold-to-compare button and an RU/EN switch.
- Python CLI (`clearcut.py`) built on ffmpeg, with batch input, presets, `--dry-run` and a progress readout.
- One shared filter chain, in the order: deflicker, denoise, deband, frame interpolation, upscale, sharpen, colour, grain.
- Presets: Neutral, AI clean, Cinematic, Crisp and Smooth.
- Upscaling to 1080p, 1440p and 2160p (Lanczos, never scales down).
- Frame-rate conversion to 24, 30, 48 and 60 fps with blend or motion interpolation.
- H.264 output in both versions and H.265 in the CLI.
- Audio is copied untouched when the container allows it.
- MIT licence, README and Russian translations of both documents.
