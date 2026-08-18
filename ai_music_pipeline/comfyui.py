from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def submit(self, workflow: dict[str, Any], client_id: str) -> str:
        result = self._request("POST", "/prompt", {"client_id": client_id, "prompt": workflow})
        if result.get("node_errors"):
            raise ComfyUIError(f"ComfyUI node errors: {result['node_errors']}")
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"Missing prompt_id in response: {result}")
        return prompt_id

    def wait_for_success(self, prompt_id: str, poll_seconds: int = 5, timeout_seconds: int = 1800) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = self._request("GET", f"/history/{prompt_id}")
            item = history.get(prompt_id)
            if item:
                status = item.get("status", {}).get("status_str")
                if status == "success":
                    return item
                if status == "error":
                    raise ComfyUIError(json.dumps(item.get("status", {}), ensure_ascii=False))
            time.sleep(poll_seconds)
        raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

    def download(self, filename: str, destination: Path, subfolder: str = "", output_type: str = "output") -> Path:
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": output_type})
        request = Request(f"{self.base_url}/view?{query}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=self.timeout) as response:
            destination.write_bytes(response.read())
        return destination

