"""Turn a session's screenshots into a watchable recording.

Priority order:

1. ``ffmpeg`` on PATH  → H.264 MP4 (best quality / smallest file)
2. Pillow installed    → optimised animated GIF
3. neither             → no video, but the PNG frames stay available

The harness itself stays standard-library only; the two video backends are
optional accelerators, and the UI tells you which one was used.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

try:  # optional
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the environment
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]
    PIL_AVAILABLE = False

HUD_BG = (9, 12, 18)
HUD_FG = (230, 237, 243)
HUD_ACCENT = (88, 166, 255)
HUD_BAD = (248, 81, 73)


@dataclass
class Frame:
    step: int
    path: str
    action: str = ""
    finding: bool = False


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def available() -> Tuple[bool, str]:
    """(can_build_video, backend_name) for the UI to display."""
    if ffmpeg_path():
        return True, "ffmpeg/mp4"
    if PIL_AVAILABLE:
        return True, "pillow/gif"
    return False, "unavailable"


def _font(size: int):
    if not PIL_AVAILABLE:
        return None
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


def auto_scale(path: str, max_width: int = 520) -> float:
    """Pick a scale so a recording stays a sensible size for both sim and phone."""
    try:
        with Image.open(path) as probe:
            width = probe.size[0] or 1
    except Exception:  # pragma: no cover - unreadable frame
        return 1.0
    return max(0.25, min(3.0, max_width / width))


def _render(frame: Frame, scale: float, fps: int) -> "Image.Image":
    """Scale one screenshot and burn a small HUD into it."""
    image = Image.open(frame.path).convert("RGB")
    width, height = image.size
    target_w = max(1, int(width * scale))
    target_h = max(1, int(height * scale))
    if (target_w, target_h) != (width, height):
        resample = Image.NEAREST if target_w >= width else Image.LANCZOS
        image = image.resize((target_w, target_h), resample)

    hud = max(18, int(target_h * 0.075))
    canvas = Image.new("RGB", (target_w, target_h + hud * 2), HUD_BG)
    canvas.paste(image, (0, hud))

    draw = ImageDraw.Draw(canvas)
    font = _font(max(10, int(hud * 0.62)))
    small = _font(max(9, int(hud * 0.52)))

    draw.text((6, max(2, hud // 2 - hud // 3)), f"STEP {frame.step:03d}", font=font, fill=HUD_ACCENT)
    label = (frame.action or "").split(" [")[0][:34]
    if label:
        draw.text((6 + int(hud * 3.1), max(2, hud // 2 - hud // 3)), label, font=small, fill=HUD_FG)

    footer = f"{fps} fps  |  apkharness"
    draw.text((6, target_h + hud + max(2, hud // 4)), footer, font=small, fill=(139, 148, 158))
    if frame.finding:
        badge = "FINDING"
        draw.text((target_w - int(hud * 3.6), target_h + hud + max(2, hud // 4)), badge,
                  font=small, fill=HUD_BAD)
        draw.rectangle([0, hud - 3, target_w, hud], fill=HUD_BAD)
    return canvas


def build_gif(frames: Sequence[Frame], out_path: str, fps: int = 6, scale: float = 3,
              max_frames: int = 400) -> str:
    """Animated GIF; requires Pillow."""
    if not PIL_AVAILABLE:
        raise RuntimeError("GIF output needs Pillow (pip install pillow) or ffmpeg")
    chosen = list(frames)[:max_frames]
    if not chosen:
        raise RuntimeError("no frames to record")
    images = [_render(frame, scale, fps) for frame in chosen]
    duration = max(40, int(1000 / max(1, fps)))
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out_path


def build_mp4(frames: Sequence[Frame], out_path: str, fps: int = 6, scale: float = 3,
              max_frames: int = 400) -> str:
    """H.264 MP4 through ffmpeg; falls back to raising RuntimeError."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed")
    chosen = list(frames)[:max_frames]
    if not chosen:
        raise RuntimeError("no frames to record")

    staging = tempfile.mkdtemp(prefix="apkharness_frames_", dir=os.path.dirname(out_path) or ".")
    try:
        if PIL_AVAILABLE:
            for index, frame in enumerate(chosen):
                _render(frame, scale, fps).save(os.path.join(staging, f"{index:05d}.png"))
            pattern = "*.png"
        else:
            for index, frame in enumerate(chosen):
                shutil.copyfile(frame.path, os.path.join(staging, f"{index:05d}.png"))
            pattern = "*.png"
        width, height = Image.open(chosen[0].path).size if PIL_AVAILABLE else (0, 0)
        command = [
            ffmpeg, "-y", "-loglevel", "error",
            "-framerate", str(max(1, fps)),
            "-pattern_type", "glob", "-i", os.path.join(staging, pattern),
        ]
        if PIL_AVAILABLE and width and height:
            command += ["-vf", f"scale={width * scale}:{height * scale}:flags=neighbor"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
        subprocess.run(command, check=True, capture_output=True, timeout=300)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return out_path


def build(frames: Sequence[Frame], out_dir: str, fps: int = 6,
          scale: Optional[float] = None) -> Dict[str, object]:
    """Build the best available recording; returns metadata for the UI."""
    frames = [frame for frame in frames if frame.path and os.path.exists(frame.path)]
    meta: Dict[str, object] = {
        "available": bool(frames),
        "backend": available()[1],
        "frames": len(frames),
        "path": "",
        "kind": "",
        "error": "",
    }
    if not frames:
        meta["error"] = "this session saved no screenshots"
        return meta
    if not available()[0]:
        meta["error"] = "install ffmpeg or Pillow to generate a recording"
        return meta

    os.makedirs(out_dir, exist_ok=True)
    if scale is None:
        scale = auto_scale(frames[0].path)
    gif_path = os.path.join(out_dir, "session.gif")
    mp4_path = os.path.join(out_dir, "session.mp4")

    if ffmpeg_path():
        try:
            build_mp4(frames, mp4_path, fps=fps, scale=scale)
            meta.update(path=mp4_path, kind="video/mp4")
            return meta
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            meta["error"] = f"mp4 failed ({exc}); trying gif"
    if PIL_AVAILABLE:
        try:
            build_gif(frames, gif_path, fps=fps, scale=scale)
            meta.update(path=gif_path, kind="image/gif")
            return meta
        except (RuntimeError, OSError) as exc:
            meta["error"] = f"gif failed ({exc})"
    return meta


def frames_from_timeline(timeline: Sequence[Dict[str, object]], screenshots_dir: str) -> List[Frame]:
    """Map a session timeline to the screenshots that were saved for it."""
    frames: List[Frame] = []
    for entry in timeline:
        shot = str(entry.get("shot") or "")
        if not shot:
            continue
        relative = shot.replace("/", os.sep)
        path = os.path.join(screenshots_dir, os.path.basename(relative)) if not os.path.isabs(relative) else relative
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(screenshots_dir), relative)
        if not os.path.exists(path):
            continue
        frames.append(
            Frame(
                step=int(entry.get("step") or 0),
                path=path,
                action=str(entry.get("action") or ""),
                finding=bool(entry.get("crashes")),
            )
        )
    return frames
