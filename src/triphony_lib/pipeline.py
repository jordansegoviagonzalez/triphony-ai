"""
The Core ML Pipeline.
This module contains the logic for generating assets. It knows NOTHING about
Databases, Celery, or HTTP Requests. It strictly follows the Input -> Output contract.
"""
import math
import pathlib
import random
import struct
import time
import uuid
import wave
import requests
from typing import Optional

from PIL import Image, ImageDraw

from triphony_lib.contracts import GenerationRequest, GenerationResult


class Pipeline:
    def __init__(self):
        pass

    def run(self, request: GenerationRequest) -> GenerationResult:
        start_time = time.time()
        
        try:
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
        return GenerationResult(success=True, asset_type="narrative", content_text=text)

    def _generate_visual(self, request: GenerationRequest, out_dir: pathlib.Path) -> GenerationResult:
        filename = f"{uuid.uuid4()}.png"
        filepath = out_dir / filename

        if request.provider_mode == "real" and request.api_key:
            # Hugging Face Inference
            try:
                # Switching extension to mp4 if it's video, but let's stick to the current logic
                # The original code did mp4 for real, png for mock.
                filename = f"{uuid.uuid4()}.mp4"
                filepath = out_dir / filename
                
                model_id = "damo-vilab/text-to-video-ms-1.7b"
                api_endpoint = f"https://api-inference.huggingface.co/models/{model_id}"
                headers = {
                    "Authorization": f"Bearer {request.api_key}",
                    "Content-Type": "application/json",
                }
                payload = {"inputs": request.prompt}
                
                response = requests.post(api_endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                
                with open(filepath, "wb") as f:
                    f.write(response.content)
                    
                return GenerationResult(
                    success=True, 
                    asset_type="visual", 
                    artifact_path=filename # Return filename relative to out_dir
                )
            except Exception as e:
                # Fallback or fail? The original code failed.
                raise e
        else:
            # Mock Generation
            self._render_mock_visual(filepath, request.prompt)
            return GenerationResult(
                success=True, 
                asset_type="visual", 
                artifact_path=filename
            )

    def _generate_soundtrack(self, request: GenerationRequest, out_dir: pathlib.Path) -> GenerationResult:
        filename = f"{uuid.uuid4()}.wav"
        filepath = out_dir / filename
        self._render_mock_wav(filepath)
        return GenerationResult(
            success=True,
            asset_type="soundtrack",
            artifact_path=filename
        )

    # --- Internal Mock Generators ---
    
    def _render_mock_visual(self, out_path: pathlib.Path, prompt: str) -> None:
        W, H = 768, 1024
        img = Image.new("RGB", (W, H), (12, 14, 20))
        d = ImageDraw.Draw(img)

        # Neon gradient bars
        for i in range(0, H, 16):
            r = int(30 + 40 * math.sin(i / 60))
            g = int(20 + 35 * math.sin(i / 80 + 1))
            b = int(40 + 60 * math.sin(i / 90 + 2))
            d.rectangle([0, i, W, i + 16], fill=(r, g, b))

        # Center “frame”
        margin = 90
        d.rounded_rectangle([margin, 140, W - margin, H - 170], radius=28, outline=(255, 255, 255, 60), width=2)

        # Caption
        caption = (prompt[:72] + "…") if len(prompt) > 72 else prompt
        caption = caption or "Neon rain, cinematic mood"
        d.text((margin, H - 140), f"Concept Frame", fill=(230, 230, 230))
        d.text((margin, H - 110), caption, fill=(180, 180, 190))

        img.save(out_path)

    def _render_mock_wav(self, out_path: pathlib.Path, seconds: float = 3.2, sr: int = 44100) -> None:
        n = int(seconds * sr)
        freq = 220.0 + random.random() * 40
        amp = 0.2

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)

            for i in range(n):
                t = i / sr
                sample = amp * math.sin(2 * math.pi * freq * t) + 0.02 * (random.random() * 2 - 1)
                s = int(max(-1, min(1, sample)) * 32767)
                wf.writeframes(struct.pack("<h", s))
