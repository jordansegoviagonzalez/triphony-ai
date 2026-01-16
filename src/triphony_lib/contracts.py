from dataclasses import dataclass
from typing import Optional, Literal

# These pure Python contracts decouple our ML logic from the database (SQLAlchemy)
# and the task queue (Celery). This allows the pipeline to be run in isolation
# (e.g. inside a Jupyter notebook or a CLI tool) without spinning up the full stack.

AssetType = Literal["narrative", "visual", "soundtrack"]

@dataclass(frozen=True)
class GenerationRequest:
    job_id: str
    prompt: str
    asset_type: AssetType
    # Configuration for the specific run (e.g., model version, seed)
    # ensuring reproducibility.
    provider_mode: str = "mock"  # "mock" or "real"
    api_key: Optional[str] = None
    output_dir: str = "/tmp/artifacts"

@dataclass(frozen=True)
class GenerationResult:
    success: bool
    asset_type: AssetType
    # If successful:
    content_text: Optional[str] = None
    artifact_path: Optional[str] = None # Relative path
    # If failed:
    error_message: Optional[str] = None
    # Meta info for calibration/logging
    duration_seconds: float = 0.0
