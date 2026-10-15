"""Bounded, path-safe FFmpeg/FFprobe media infrastructure for Phase 4."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import Any

from triphony_lib.observability import span


class MediaValidationError(RuntimeError):
    """Raised when an input or output does not satisfy the delivery profile."""


def _safe_path(root: pathlib.Path, relative: str) -> pathlib.Path:
    base = root.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise MediaValidationError("media path escaped the artifact root")
    return target


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise MediaValidationError("media command timed out") from error
    if result.returncode != 0:
        raise MediaValidationError("media command failed")
    return result


def _probe(path: pathlib.Path, timeout: float = 20.0) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
        ],
        timeout,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MediaValidationError("ffprobe returned malformed metadata") from error


def validate_media(relative: str, root: pathlib.Path, expected: str) -> dict[str, Any]:
    path = _safe_path(root, relative)
    if not path.is_file() or path.stat().st_size == 0:
        raise MediaValidationError("media file is missing or empty")
    metadata = _probe(path)
    streams = metadata.get("streams", [])
    stream_types = {stream.get("codec_type") for stream in streams}
    if expected == "video" and "video" not in stream_types:
        raise MediaValidationError("media file has no video stream")
    if expected == "audio" and "audio" not in stream_types:
        raise MediaValidationError("media file has no audio stream")
    if expected == "final" and not {"video", "audio"}.issubset(stream_types):
        raise MediaValidationError("final render must contain video and audio")
    return metadata


def _ensure_parent(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_fake_video(root: pathlib.Path, relative: str, duration_ms: int, seed: str) -> dict[str, Any]:
    path = _safe_path(root, relative)
    _ensure_parent(path)
    duration = max(1.0, duration_ms / 1000)
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc2=size=640x360:rate=24,drawtext=text='{seed[:12]}':x=10:y=10:fontsize=18:fontcolor=white",
            "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(path),
        ],
        timeout=max(30.0, duration * 10),
    )
    return validate_media(relative, root, "video")


def write_fake_audio(root: pathlib.Path, relative: str, duration_ms: int, frequency: int) -> dict[str, Any]:
    path = _safe_path(root, relative)
    _ensure_parent(path)
    duration = max(1.0, duration_ms / 1000)
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:duration={duration:.3f}", "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(path),
        ],
        timeout=max(30.0, duration * 10),
    )
    return validate_media(relative, root, "audio")


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assemble_mp4(
    root: pathlib.Path,
    *,
    scene_id: str,
    version: int,
    video_paths: list[str],
    audio_paths: list[str],
    expected_duration_ms: int,
    configuration_version: str = "phase4-v1",
) -> tuple[str, dict[str, Any]]:
    if not video_paths or len(audio_paths) != 4:
        raise MediaValidationError("assembly requires ordered video and four logical audio inputs")
    for path in video_paths:
        validate_media(path, root, "video")
    for path in audio_paths:
        validate_media(path, root, "audio")
    final_relative = f"{scene_id}/final/v{version}/render.mp4"
    final_path = _safe_path(root, final_relative)
    _ensure_parent(final_path)
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="assembly-", dir=str(root.resolve())))
    try:
        concat_file = temp_dir / "videos.txt"
        with concat_file.open("w", encoding="utf-8") as handle:
            for relative in video_paths:
                path = _safe_path(root, relative)
                handle.write(f"file '{path.as_posix()}'\n")
        concatenated = temp_dir / "video.mp4"
        _run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_file), "-c", "copy", str(concatenated)],
            timeout=90.0,
        )
        audio_args: list[str] = []
        for relative in audio_paths:
            audio_args.extend(["-i", str(_safe_path(root, relative))])
        output_temp = temp_dir / "render.mp4"
        _run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(concatenated), *audio_args,
                "-filter_complex", "[1:a][2:a][3:a][4:a]amix=inputs=4:duration=longest:dropout_transition=0,volume=0.25[a]",
                "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart",
                str(output_temp),
            ],
            timeout=120.0,
        )
        os.replace(output_temp, final_path)
        metadata = validate_media(final_relative, root, "final")
        streams = metadata.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
        manifest = {
            "scene_plan_version": configuration_version,
            "input_asset_paths": video_paths + audio_paths,
            "output_checksum": _sha256(final_path),
            "expected_duration_ms": expected_duration_ms,
            "measured_duration_ms": round(float(metadata.get("format", {}).get("duration", 0)) * 1000),
            "resolution": f"{video.get('width')}x{video.get('height')}",
            "frame_rate": video.get("r_frame_rate"),
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "ffmpeg_version": _run(["ffmpeg", "-version"], 10.0).stdout.splitlines()[0],
            "configuration_version": configuration_version,
        }
        return final_relative, manifest
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def assemble_mp4(
    root: pathlib.Path,
    *,
    scene_id: str,
    version: int,
    video_paths: list[str],
    audio_paths: list[str],
    expected_duration_ms: int,
    configuration_version: str = "phase4-v1",
) -> tuple[str, dict[str, Any]]:
    with span("media.assembly", scene_id=scene_id, version=version, video_count=len(video_paths), audio_count=len(audio_paths)):
        return _assemble_mp4(
            root,
            scene_id=scene_id,
            version=version,
            video_paths=video_paths,
            audio_paths=audio_paths,
            expected_duration_ms=expected_duration_ms,
            configuration_version=configuration_version,
        )
