#!/usr/bin/env python3
"""Clearcut: video clean-up and enhancement on top of ffmpeg.

One pass does: deflicker, denoise, deband, frame interpolation, upscale,
sharpen, colour grade and film grain. The filter chain here is mirrored
by the browser version (index.html), so both give the same look.

Usage:
    python clearcut.py clip.mp4
    python clearcut.py clip.mp4 --preset ai-clean --height 1080
    python clearcut.py a.mp4 b.mp4 --sharpen 0.8 --fps 60 --interp motion

Needs ffmpeg and ffprobe on the PATH. Licence: MIT.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
from dataclasses import asdict, dataclass, fields
from pathlib import Path

__version__ = "1.1.0"


@dataclass
class Settings:
    """Every slider in the browser version has a field here."""

    height: int = 0          # target height in pixels, 0 = keep
    scale: float = 0.0       # alternative to height: multiply the source size
    denoise: float = 0.0     # 0..10
    deflicker: bool = False
    deband: bool = False
    fps: float = 0.0         # target frame rate, 0 = keep
    interp: str = "blend"    # "blend" (fast) or "motion" (slow, smoother)
    sharpen: float = 0.0     # 0..2
    contrast: float = 0.0    # -100..100
    brightness: float = 0.0  # -100..100
    saturation: float = 0.0  # -100..100
    vibrance: float = 0.0    # -100..100
    warmth: float = 0.0      # -100..100 (negative = cooler)
    grain: float = 0.0       # 0..40
    crf: int = 18            # lower = better quality, bigger file


PRESETS: dict[str, dict] = {
    "neutral": {},
    "ai-clean": {
        "height": 1080, "denoise": 2.5, "deband": True, "sharpen": 0.7,
        "contrast": 8, "saturation": 6, "grain": 4,
    },
    "cinematic": {
        "denoise": 1.5, "deband": True, "sharpen": 0.4, "contrast": 15,
        "saturation": -6, "warmth": 12, "grain": 10,
    },
    "crisp": {
        "denoise": 1.5, "sharpen": 1.2, "contrast": 10, "saturation": 10,
        "vibrance": 20,
    },
    "smooth": {
        "denoise": 1.0, "fps": 60, "interp": "motion", "sharpen": 0.3,
    },
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_filters(s: Settings, src_height: int) -> list[str]:
    """Return the ffmpeg video filters in processing order."""
    chain: list[str] = []

    if s.deflicker:
        chain.append("deflicker=size=5:mode=am")

    if s.denoise > 0:
        d = clamp(s.denoise, 0, 10)
        # The tiny offset rounds halves up, matching the browser version.
        a, b, c, e = (f"{v + 1e-9:.2f}" for v in
                      (d, d * 0.75, d * 1.5, d * 1.1))
        chain.append(f"hqdn3d={a}:{b}:{c}:{e}")

    if s.deband:
        chain.append("deband=1thr=0.02:2thr=0.02:3thr=0.02:blur=1")

    if s.fps > 0:
        if s.interp == "motion":
            chain.append(
                f"minterpolate=fps={s.fps:g}:mi_mode=mci:mc_mode=aobmc"
                ":me_mode=bidir:vsbmc=1"
            )
        else:
            chain.append(f"minterpolate=fps={s.fps:g}:mi_mode=blend")

    # Only ever scale up. Scaling down would throw detail away.
    target = s.height
    if not target and s.scale > 1:
        target = int(round(src_height * s.scale / 2) * 2)
    if target and target > src_height:
        chain.append(f"scale=-2:{target}:flags=lanczos")

    if s.sharpen > 0:
        amount = clamp(s.sharpen, 0, 2)
        chain.append(f"unsharp=5:5:{amount:.2f}:5:5:0")

    eq_parts = []
    if s.contrast:
        eq_parts.append(f"contrast={1 + s.contrast / 200:.3f}")
    if s.brightness:
        eq_parts.append(f"brightness={s.brightness / 500:.3f}")
    if s.saturation:
        eq_parts.append(f"saturation={1 + s.saturation / 100:.3f}")
    if eq_parts:
        chain.append("eq=" + ":".join(eq_parts))

    if s.vibrance:
        chain.append(f"vibrance=intensity={s.vibrance / 100:.3f}")

    if s.warmth:
        a = s.warmth / 100 * 0.25
        chain.append(
            f"colorbalance=rs={a:.3f}:rm={a:.3f}:rh={a:.3f}"
            f":bs={-a:.3f}:bm={-a:.3f}:bh={-a:.3f}"
        )

    if s.grain > 0:
        chain.append(f"noise=alls={clamp(s.grain, 0, 40):.0f}:allf=t")

    chain.append("format=yuv420p")
    return chain


class ProbeError(Exception):
    """ffprobe failed or the file has no video."""

    def __init__(self, msg: str, detail: str = ""):
        super().__init__(msg)
        self.detail = detail


def probe(path: Path) -> dict:
    """Read size, duration and audio codec with ffprobe."""
    res = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise ProbeError("ffprobe could not read the file",
                         res.stderr.strip())
    try:
        data = json.loads(res.stdout)
        video = next(x for x in data["streams"]
                     if x["codec_type"] == "video")
    except (ValueError, KeyError, StopIteration):
        raise ProbeError("no video stream found", res.stderr.strip())
    audio = next((x for x in data["streams"] if x["codec_type"] == "audio"), None)
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration": float(data["format"].get("duration", 0) or 0),
        "audio_codec": audio["codec_name"] if audio else None,
    }


def build_command(src: Path, dst: Path, s: Settings, info: dict,
                  codec: str, x264_preset: str) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(src)]
    cmd += ["-vf", ",".join(build_filters(s, info["height"]))]

    if codec == "h265":
        cmd += ["-c:v", "libx265", "-tag:v", "hvc1", "-crf", str(s.crf)]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(s.crf)]
    cmd += ["-preset", x264_preset]

    # Keep the original audio untouched when the container allows it.
    if info["audio_codec"] in ("aac", "mp3", "alac"):
        cmd += ["-c:a", "copy"]
    elif info["audio_codec"]:
        cmd += ["-c:a", "aac", "-b:a", "320k"]
    else:
        cmd += ["-an"]

    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
            str(dst)]
    return cmd


def run_with_progress(cmd: list[str], duration: float) -> tuple[int, str]:
    """Run ffmpeg, show progress, return (exit code, stderr tail)."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        errors="replace",
    )
    assert proc.stdout is not None and proc.stderr is not None
    lines: list[str] = []

    # Drain stderr on its own thread. Reading it after stdout can
    # deadlock once ffmpeg fills the stderr pipe.
    def drain() -> None:
        for ln in proc.stderr:  # type: ignore[union-attr]
            lines.append(ln.rstrip())
            del lines[:-40]

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and duration and value.isdigit():
            done = min(100.0, int(value) / 1_000_000 / duration * 100)
            print(f"\r  {done:5.1f}%", end="", flush=True)
    code = proc.wait()
    t.join(timeout=5)
    print("\r  100.0%" if code == 0 else "\r  failed ", flush=True)
    tail = "\n".join(lines)
    if code != 0:
        last = [x for x in lines if x.strip()]
        print(last[-1] if last else "ffmpeg failed", file=sys.stderr)
    return code, tail


# ---------- crash report ----------

W = 58  # report width, so it reads well in a narrow window


def _ram_gb() -> str:
    try:
        n = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return f"{n / 2**30:.1f} GB"
    except (AttributeError, ValueError, OSError):
        return "unknown"


def _tool_version(tool: str) -> str:
    try:
        out = subprocess.run([tool, "-version"], capture_output=True,
                             text=True, timeout=10).stdout
        return out.splitlines()[0][:W - 14] if out else "no output"
    except (OSError, subprocess.SubprocessError):
        return "not found"


def _hints(code: int | None, tail: str, info: dict | None,
           s: Settings | None) -> list[str]:
    t = tail.lower()
    out: list[str] = []
    if code is not None and code < 0:
        out.append("ffmpeg was killed by a signal. On Linux that is "
                   "often the out-of-memory killer. Try a lighter "
                   "--x264-preset, no --fps motion, or a lower --height.")
    if "cannot allocate memory" in t or "out of memory" in t:
        out.append("ffmpeg ran out of memory.")
    if "unknown encoder" in t or "encoder 'libx26" in t:
        out.append("This ffmpeg build lacks the x264/x265 encoder.")
    if "no such filter" in t or "filter not found" in t:
        out.append("This ffmpeg build lacks a filter. Update ffmpeg.")
    if "invalid argument" in t and "preset" in t:
        out.append("The --x264-preset value is not valid.")
    if "permission denied" in t:
        out.append("No permission to write the output file.")
    if "no space left" in t:
        out.append("The disk is full.")
    if s and info and s.interp == "motion" and s.fps:
        out.append("Motion interpolation is very heavy; try blend.")
    if info and s and max(s.height, 0) >= 2160:
        out.append("4K output needs a lot of memory.")
    return out or ["No known pattern matched. Send this file to the "
                   "developer."]


def write_crash_report(kind: str, message: str, *, cmd: list[str] | None = None,
                       src: Path | None = None, dst: Path | None = None,
                       info: dict | None = None,
                       settings: Settings | None = None,
                       code: int | None = None, tail: str = "",
                       exc: BaseException | None = None) -> Path | None:
    """Write CRASHREPORT.txt. File names are removed from the text."""
    secrets = []
    for p in (src, dst):
        if p:
            secrets += [str(p), p.name]
    secrets = sorted({x for x in secrets if x}, key=len, reverse=True)

    def clean(text: str) -> str:
        for x in secrets:
            text = text.replace(x, "<file>")
        home = str(Path.home())
        return text.replace(home, "~") if home else text

    def put(lines: list[str], key: str, val: object) -> None:
        wrapped = textwrap.wrap(str(val), W - 14) or [""]
        lines.append(f"{key:<13} {wrapped[0]}")
        lines += [" " * 14 + w for w in wrapped[1:]]

    rule = "-" * W
    L: list[str] = ["CLEARCUT CRASH REPORT", "=" * W]
    put(L, "Time", time.strftime("%Y-%m-%d %H:%M:%S"))
    put(L, "Kind", kind)
    put(L, "Message", clean(message))
    put(L, "Exit code", code if code is not None else "n/a")
    L += [rule, "SYSTEM"]
    put(L, "Clearcut", __version__)
    put(L, "Python", platform.python_version())
    put(L, "OS", platform.platform())
    put(L, "RAM", _ram_gb())
    try:
        put(L, "Disk free", f"{shutil.disk_usage('.').free / 2**30:.1f} GB")
    except OSError:
        put(L, "Disk free", "unknown")
    put(L, "ffmpeg", _tool_version("ffmpeg"))
    put(L, "ffprobe", _tool_version("ffprobe"))
    if info:
        L += [rule, "INPUT"]
        put(L, "Size", f"{info.get('width')}x{info.get('height')}")
        put(L, "Duration", f"{info.get('duration', 0):.1f} s")
        put(L, "Audio", info.get("audio_codec") or "none")
        if src:
            try:
                put(L, "File size", f"{src.stat().st_size / 2**20:.1f} MB")
                put(L, "Extension", src.suffix.lower() or "none")
            except OSError:
                pass
    if settings:
        L += [rule, "SETTINGS"]
        for k, v in asdict(settings).items():
            put(L, k, v)
    if cmd:
        L += [rule, "COMMAND"]
        L += textwrap.wrap(clean(" ".join(cmd)), W,
                           break_long_words=False, break_on_hyphens=False)
    L += [rule, "HINTS"]
    for h in _hints(code, tail, info, settings):
        L += textwrap.wrap(h, W - 2, initial_indent="- ",
                           subsequent_indent="  ")
    if tail.strip():
        L += [rule, "FFMPEG OUTPUT (last lines)"]
        for ln in clean(tail).splitlines()[-25:]:
            L += textwrap.wrap(ln, W, break_long_words=True) or [""]
    if exc is not None:
        L += [rule, "TRACEBACK"]
        tb = clean("".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__)))
        for ln in tb.splitlines():
            L += textwrap.wrap(ln, W, break_long_words=True,
                               replace_whitespace=False) or [""]
    L += [rule, "Nothing here was sent anywhere. File names removed.", ""]
    text = "\n".join(L)

    for folder in (Path.cwd(), Path(tempfile.gettempdir())):
        target = folder / "CRASHREPORT.txt"
        try:
            target.write_text(text, encoding="utf-8")
            return target
        except OSError:
            continue
    return None


def _announce(path: Path | None) -> None:
    if path:
        print(f"Crash report saved: {path}", file=sys.stderr)
        print("Send that file to the developer.", file=sys.stderr)
    else:
        print("Could not write CRASHREPORT.txt.", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="clearcut",
        description="Clean up and enhance video with one ffmpeg pass.",
    )
    p.add_argument("inputs", nargs="*", type=Path, help="video file(s)")
    p.add_argument("-o", "--output", type=Path,
                   help="output file (single input only)")
    p.add_argument("--preset", choices=sorted(PRESETS), default="neutral")
    p.add_argument("--list-presets", action="store_true")

    g = p.add_argument_group("size and speed")
    g.add_argument("--height", type=int, help="target height, e.g. 1080")
    g.add_argument("--scale", type=float, help="size multiplier, e.g. 2")
    g.add_argument("--fps", type=float, help="target frame rate, e.g. 60")
    g.add_argument("--interp", choices=["blend", "motion"],
                   help="frame interpolation style")

    g = p.add_argument_group("clean-up")
    g.add_argument("--denoise", type=float, help="0..10")
    g.add_argument("--deflicker", action=argparse.BooleanOptionalAction)
    g.add_argument("--deband", action=argparse.BooleanOptionalAction)
    g.add_argument("--sharpen", type=float, help="0..2")

    g = p.add_argument_group("colour and look")
    g.add_argument("--contrast", type=float, help="-100..100")
    g.add_argument("--brightness", type=float, help="-100..100")
    g.add_argument("--saturation", type=float, help="-100..100")
    g.add_argument("--vibrance", type=float, help="-100..100")
    g.add_argument("--warmth", type=float, help="-100..100")
    g.add_argument("--grain", type=float, help="0..40")

    g = p.add_argument_group("output")
    g.add_argument("--crf", type=int, help="quality, 14 (best) to 28")
    g.add_argument("--codec", choices=["h264", "h265"], default="h264")
    g.add_argument("--x264-preset", default="medium",
                   help="encoder speed preset (default: medium)")
    g.add_argument("--dry-run", action="store_true",
                   help="print the ffmpeg command and stop")
    return p.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> Settings:
    values = asdict(Settings())
    values.update(PRESETS[args.preset])
    for f in fields(Settings):
        given = getattr(args, f.name, None)
        if given is not None:
            values[f.name] = given
    return Settings(**values)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except BrokenPipeError:  # e.g. output piped into `head`
        return 0
    except Exception as exc:  # last resort: never show a bare traceback
        print(f"Unexpected error: {exc}", file=sys.stderr)
        _announce(write_crash_report("unexpected error", str(exc), exc=exc))
        return 1


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_presets:
        for name, values in PRESETS.items():
            print(f"{name:10s} {values or '(no changes)'}")
        return 0

    if not args.inputs:
        print("No input files. Try: python clearcut.py clip.mp4",
              file=sys.stderr)
        return 2
    if args.output and len(args.inputs) > 1:
        print("-o only works with a single input.", file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not found on the PATH.", file=sys.stderr)
            return 1

    settings = settings_from_args(args)
    failures = 0

    for src in args.inputs:
        if not src.is_file():
            print(f"{src}: not found", file=sys.stderr)
            failures += 1
            continue
        dst = args.output or src.with_name(f"{src.stem}_enhanced.mp4")
        try:
            info = probe(src)
        except ProbeError as exc:
            print(f"{src.name}: {exc}", file=sys.stderr)
            _announce(write_crash_report(
                "probe failed", str(exc), src=src, dst=dst,
                settings=settings, tail=exc.detail))
            failures += 1
            continue
        cmd = build_command(src, dst, settings, info, args.codec,
                            args.x264_preset)
        print(f"{src.name} ({info['width']}x{info['height']}) -> {dst.name}")
        if args.dry_run:
            print(" ".join(cmd))
            continue
        code, tail = run_with_progress(cmd, info["duration"])
        if code != 0:
            _announce(write_crash_report(
                "ffmpeg failed", f"ffmpeg exited with code {code}",
                cmd=cmd, src=src, dst=dst, info=info, settings=settings,
                code=code, tail=tail))
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
