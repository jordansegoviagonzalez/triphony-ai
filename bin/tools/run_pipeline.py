#!/usr/bin/env python3
import argparse
import sys
import os
import json

# Add project root to path so we can import triphony_lib
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
sys.path.append(project_root)

from triphony_lib.contracts import GenerationRequest
from triphony_lib.pipeline import Pipeline

def main():
    parser = argparse.ArgumentParser(description="Run the Triphony Generation Pipeline in isolation.")
    parser.add_argument("--prompt", type=str, required=True, help="The concept prompt.")
    parser.add_argument("--type", type=str, required=True, choices=["narrative", "visual", "soundtrack"], help="Asset type to generate.")
    parser.add_argument("--out-dir", type=str, default="./artifacts", help="Directory to save artifacts.")
    parser.add_argument("--mode", type=str, default="mock", choices=["mock", "real"], help="Provider mode.")
    parser.add_argument("--api-key", type=str, default=None, help="API Key for real provider.")

    args = parser.parse_args()

    print(f"--- 🚀 Starting Pipeline Run ---")
    print(f"Prompt: {args.prompt}")
    print(f"Type:   {args.type}")
    print(f"Mode:   {args.mode}")

    req = GenerationRequest(
        job_id="cli-run",
        prompt=args.prompt,
        asset_type=args.type,
        provider_mode=args.mode,
        api_key=args.api_key,
        output_dir=args.out_dir
    )

    pipeline = Pipeline()
    result = pipeline.run(req)

    print(f"\n--- 🏁 Result ---")
    print(f"Success: {result.success}")
    print(f"Duration: {result.duration_seconds:.2f}s")
    
    if result.success:
        if result.content_text:
            print(f"Content:\n{result.content_text}")
        if result.artifact_path:
            print(f"Artifact: {os.path.join(args.out_dir, result.artifact_path)}")
    else:
        print(f"Error: {result.error_message}")
        sys.exit(1)

if __name__ == "__main__":
    main()
