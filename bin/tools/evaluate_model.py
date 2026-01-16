#!/usr/bin/env python3
import argparse
import sys
import os
import random

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
sys.path.append(project_root)

from triphony_lib.contracts import GenerationRequest
from triphony_lib.pipeline import Pipeline

def main():
    parser = argparse.ArgumentParser(description="Evaluate the Pipeline's 'Selectivity' (Mock Implementation).")
    parser.add_argument("--samples", type=int, default=5, help="Number of samples to run.")
    args = parser.parse_args()

    print(f"--- 📊 Running Evaluation (N={args.samples}) ---")
    
    # Mock dataset of prompts
    prompts = [
        "Cyberpunk city rain",
        "Medieval castle in mist",
        "Abstract geometric shapes",
        "Portrait of a robot",
        "Underwater coral reef"
    ]

    results = []
    pipeline = Pipeline()

    for i in range(args.samples):
        prompt = random.choice(prompts)
        print(f"[{i+1}/{args.samples}] Testing: '{prompt}'...")
        
        req = GenerationRequest(
            job_id=f"eval-{i}",
            prompt=prompt,
            asset_type="visual",
            provider_mode="mock",
            output_dir="/tmp/eval_artifacts"
        )
        
        res = pipeline.run(req)
        results.append(res)

    success_count = sum(1 for r in results if r.success)
    avg_duration = sum(r.duration_seconds for r in results) / len(results) if results else 0

    print(f"\n--- 📈 Evaluation Report ---")
    print(f"Accuracy (Success Rate): {success_count}/{args.samples} ({(success_count/args.samples)*100:.1f}%)")
    print(f"Avg Latency: {avg_duration:.4f}s")
    print("Calibration: N/A (Mock Mode)")

if __name__ == "__main__":
    main()
