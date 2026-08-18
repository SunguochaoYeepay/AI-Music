#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

from ai_music_pipeline.comfyui import ComfyUIClient
from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.manifest import load_manifest, save_manifest


def _workflow_hash(workflow: dict[str, object]) -> str:
    payload = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_output_path(download_dir: Path, subfolder: str, filename: str) -> Path:
    relative = Path(subfolder) / filename
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"ComfyUI output path escapes download directory: {relative}")
    return download_dir / relative


def _output_items(history: dict[str, object]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    outputs = history.get("outputs", {})
    if not isinstance(outputs, dict):
        return items
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for key in ("audio", "images"):
            values = node.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                items.append(
                    {
                        "filename": str(item["filename"]),
                        "subfolder": str(item.get("subfolder", "")),
                        "type": str(item.get("type", "output")),
                    }
                )
    return items


def _download_items(client: ComfyUIClient, items: list[dict[str, str]], download_dir: Path) -> list[str]:
    downloaded: list[str] = []
    for item in items:
        destination = _safe_output_path(download_dir, item["subfolder"], item["filename"])
        if not destination.is_file() or destination.stat().st_size == 0:
            client.download(item["filename"], destination, item["subfolder"], item["type"])
        downloaded.append(str(destination.relative_to(download_dir)))
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit and optionally wait for a ComfyUI workflow")
    parser.add_argument("--workflow", type=Path, required=True, help="Expanded ComfyUI API workflow JSON")
    parser.add_argument("--base-url", default=os.getenv("COMFYUI_URL", "http://127.0.0.1:8188"))
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--state-file", type=Path, help="Persist prompt state for resumable, idempotent retries")
    parser.add_argument("--lock-file", type=Path, default=Path(".ai_music_pipeline.lock"))
    parser.add_argument("--no-lock", action="store_true")
    parser.add_argument("--force", action="store_true", help="Submit a new prompt even when state matches")
    args = parser.parse_args()

    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    state_file = args.state_file or (args.download_dir / "comfy_state.json" if args.download_dir else None)

    def run() -> None:
        state: dict[str, object] = {}
        if state_file and state_file.is_file() and not args.force:
            state = load_manifest(state_file)
        workflow_hash = _workflow_hash(workflow)
        prompt_id = state.get("prompt_id") if state.get("workflow_hash") == workflow_hash else None
        client = ComfyUIClient(args.base_url)

        if not prompt_id:
            prompt_id = client.submit(workflow, f"ai-music-{uuid.uuid4()}")
            state = {"workflow_hash": workflow_hash, "prompt_id": prompt_id, "status": "submitted"}
            if state_file:
                save_manifest(state_file, state)
        print(json.dumps({"prompt_id": prompt_id}, ensure_ascii=False))
        if not args.wait:
            return

        if state.get("status") != "success":
            history = client.wait_for_success(str(prompt_id))
            items = _output_items(history)
            state.update({"status": "success", "output_items": items})
            if state_file:
                save_manifest(state_file, state)
        else:
            items = state.get("output_items", [])
            if not isinstance(items, list):
                items = []

        if args.download_dir:
            downloaded = _download_items(client, items, args.download_dir)
            state["downloaded"] = downloaded
            if state_file:
                save_manifest(state_file, state)
        print(json.dumps({"prompt_id": prompt_id, "status": state.get("status"), "outputs": items}, ensure_ascii=False))

    if args.no_lock:
        run()
    else:
        with PipelineLock(args.lock_file):
            run()


if __name__ == "__main__":
    main()
