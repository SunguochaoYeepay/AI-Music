#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert one record through the Feishu CLI")
    parser.add_argument("--record", type=Path, required=True, help="JSON object containing field names and values")
    parser.add_argument("--base-token", default=os.getenv("FEISHU_BASE_TOKEN"), required=False)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--record-id")
    args = parser.parse_args()
    if not args.base_token:
        raise SystemExit("FEISHU_BASE_TOKEN is required")

    command = [
        "lark-cli", "base", "+record-upsert", "--as", "user",
        "--base-token", args.base_token, "--table-id", args.table_id,
        "--json", json.dumps(json.loads(args.record.read_text(encoding="utf-8")), ensure_ascii=False),
    ]
    if args.record_id:
        command.extend(["--record-id", args.record_id])
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()

