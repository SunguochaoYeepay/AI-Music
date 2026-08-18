#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from ai_music_pipeline.comfyui import ComfyUIClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit and optionally wait for a ComfyUI workflow")
    parser.add_argument("--workflow", type=Path, required=True, help="Expanded ComfyUI API workflow JSON")
    parser.add_argument("--base-url", default=os.getenv("COMFYUI_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--download-dir", type=Path)
    args = parser.parse_args()

    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    client = ComfyUIClient(args.base_url)
    prompt_id = client.submit(workflow, f"ai-music-{uuid.uuid4()}")
    print(json.dumps({"prompt_id": prompt_id}, ensure_ascii=False))
    if not args.wait:
        return

    history = client.wait_for_success(prompt_id)
    print(json.dumps({"prompt_id": prompt_id, "history": history}, ensure_ascii=False))
    if not args.download_dir:
        return

    for node in history.get("outputs", {}).values():
        for key in ("audio", "images"):
            for item in node.get(key, []):
                filename = item.get("filename")
                if filename:
                    client.download(filename, args.download_dir / filename, item.get("subfolder", ""), item.get("type", "output"))


if __name__ == "__main__":
    main()

