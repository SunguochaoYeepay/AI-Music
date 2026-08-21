from __future__ import annotations

import json
import mimetypes
import time
import uuid
from urllib.error import HTTPError, URLError
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: int = 30, retries: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, retryable: bool = False) -> Any:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        attempts = self.retries + 1 if retryable else 1
        for attempt in range(attempts):
            request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                if attempt == attempts - 1:
                    raise
                time.sleep(min(2 ** attempt, 8))

    def submit(self, workflow: dict[str, Any], client_id: str) -> str:
        result = self._request("POST", "/prompt", {"client_id": client_id, "prompt": workflow})
        if result.get("node_errors"):
            raise ComfyUIError(f"ComfyUI node errors: {result['node_errors']}")
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"Missing prompt_id in response: {result}")
        return prompt_id

    def is_available(self) -> bool:
        try:
            result = self._request("GET", "/queue")
            return isinstance(result, dict)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def upload_input(
        self,
        source: Path,
        *,
        filename: str | None = None,
        subfolder: str = "ai_music_pipeline",
        overwrite: bool = True,
    ) -> str:
        """Upload an input asset and return the LoadImage-compatible name."""
        if not source.is_file():
            raise FileNotFoundError(source)
        remote_name = filename or source.name
        if Path(remote_name).name != remote_name or ".." in Path(subfolder).parts:
            raise ValueError("Unsafe ComfyUI upload path")

        boundary = f"----ai-music-{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(remote_name)[0] or "application/octet-stream"
        chunks: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode(),
                    b"\r\n",
                ]
            )

        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="image"; filename="{remote_name}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode(),
                source.read_bytes(),
                b"\r\n",
            ]
        )
        add_field("type", "input")
        add_field("subfolder", subfolder)
        add_field("overwrite", "true" if overwrite else "false")
        chunks.append(f"--{boundary}--\r\n".encode())
        request = Request(
            f"{self.base_url}/upload/image",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        name = str(result.get("name") or remote_name)
        folder = str(result.get("subfolder") or subfolder).strip("/\\")
        return f"{folder}/{name}" if folder else name

    def wait_for_success(self, prompt_id: str, poll_seconds: int = 5, timeout_seconds: int = 1800) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = self._request("GET", f"/history/{prompt_id}", retryable=True)
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
        partial = destination.with_name(f".{destination.name}.part")
        try:
            for attempt in range(self.retries + 1):
                try:
                    with urlopen(request, timeout=self.timeout) as response, partial.open("wb") as output:
                        for chunk in iter(lambda: response.read(1024 * 1024), b""):
                            output.write(chunk)
                    break
                except (HTTPError, URLError, TimeoutError):
                    partial.unlink(missing_ok=True)
                    if attempt == self.retries:
                        raise
                    time.sleep(min(2 ** attempt, 8))
            if partial.stat().st_size == 0:
                raise ComfyUIError(f"Downloaded empty output: {filename}")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
        return destination
