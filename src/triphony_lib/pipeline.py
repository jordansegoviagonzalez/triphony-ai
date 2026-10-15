"""
The Core ML Pipeline.
This module contains the logic for generating assets. It knows NOTHING about
Databases, Celery, or HTTP Requests. It strictly follows the Input -> Output contract.
"""
import math
import json
import pathlib
import struct
import subprocess
import shutil
import time
import wave

from triphony_lib.contracts import GenerationRequest, GenerationResult


class Pipeline:
    def __init__(self):
        pass

    def run(self, request: GenerationRequest) -> GenerationResult:
        start_time = time.time()
        
        try:
            if request.provider_mode not in {"fake", "mock"}:
                return GenerationResult(
                    success=False,
                    asset_type=request.asset_type,
                    error_message=(
                        "Real provider mode is not connected to the Phase 1 artifact pipeline; "
                        "use the Phase 3 provider factory or set PROVIDER_MODE=fake."
                    ),
                    duration_seconds=time.time() - start_time,
                )

            # Ensure output directory exists
            out_dir = pathlib.Path(request.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            if request.asset_type == "narrative":
                result = self._generate_narrative(request)
            
            elif request.asset_type == "visual":
                result = self._generate_visual(request, out_dir)
                
            elif request.asset_type == "soundtrack":
                result = self._generate_soundtrack(request, out_dir)
                
            else:
                raise ValueError(f"Unknown asset type: {request.asset_type}")

            duration = time.time() - start_time
            # Return a new result with the duration attached (preserving immutability pattern if we were strict, 
            # but here we just return the result which is a GenerationResult)
            # Since dataclass is frozen, we must instantiate correctly inside the helpers or here.
            # Actually, the helpers returned GenerationResult, let's just create a new one with duration if needed
            # or better yet, pass start_time to helpers? 
            # Let's simple create a new one to be clean.
            return GenerationResult(
                success=result.success,
                asset_type=result.asset_type,
                content_text=result.content_text,
                artifact_path=result.artifact_path,
                mime_type=result.mime_type,
                error_message=result.error_message,
                duration_seconds=duration
            )

        except Exception as e:
            return GenerationResult(
                success=False,
                asset_type=request.asset_type,
                error_message=str(e),
                duration_seconds=time.time() - start_time
            )

    def _generate_narrative(self, request: GenerationRequest) -> GenerationResult:
        # Mock logic
        base = [
            "Rain-soaked streets, aglow in neon light.",
            "Tokyo dreams shimmer in the night.",
            "Umbrella silhouettes passing by,",
            "Reflections dance as raindrops sigh.",
        ]
        if request.prompt:
            base.insert(0, f"Prompt: {request.prompt.strip()}")
        
        text = "\n".join(base)
        return GenerationResult(
            success=True,
            asset_type="narrative",
            content_text=text,
            mime_type="text/plain",
        )

    def _generate_visual(self, request: GenerationRequest, out_dir: pathlib.Path) -> GenerationResult:
        filename = "mock-visual.mp4"
        filepath = out_dir / filename
        self._render_mock_visual(filepath, request.prompt)
        return GenerationResult(
            success=True,
            asset_type="visual",
            artifact_path=filename,
            mime_type="video/mp4",
        )

    def _generate_soundtrack(self, request: GenerationRequest, out_dir: pathlib.Path) -> GenerationResult:
        del request
        filename = "mock-soundtrack.wav"
        filepath = out_dir / filename
        self._render_mock_wav(filepath)
        return GenerationResult(
            success=True,
            asset_type="soundtrack",
            artifact_path=filename,
            mime_type="audio/wav",
        )

    # --- Internal Mock Generators ---
    
    def _render_mock_visual(self, out_path: pathlib.Path, prompt: str) -> None:
        del prompt
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to generate mock video assets")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24",
            "-t",
            "3",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg mock video generation failed: {completed.stderr.strip()}")

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise RuntimeError("ffprobe is required to validate mock video assets")
        validation = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,width,height",
                "-of",
                "json",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if validation.returncode != 0 or not validation.stdout.strip():
            raise RuntimeError("ffprobe could not validate the generated mock video")
        stream = json.loads(validation.stdout).get("streams", [{}])[0]
        if (
            stream.get("codec_name") != "h264"
            or stream.get("pix_fmt") != "yuv420p"
            or stream.get("width") != 640
            or stream.get("height") != 360
        ):
            raise RuntimeError("Generated mock video does not match the supported delivery profile")

    def _render_mock_wav(self, out_path: pathlib.Path, seconds: float = 3.2, sr: int = 44100) -> None:
        n = int(seconds * sr)
        freq = 240.0
        amp = 0.2

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)

            for i in range(n):
                t = i / sr
                sample = amp * math.sin(2 * math.pi * freq * t)
                s = int(max(-1, min(1, sample)) * 32767)
                wf.writeframes(struct.pack("<h", s))

        with wave.open(str(out_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != sr:
                raise RuntimeError("Generated mock audio does not match the supported delivery profile")
