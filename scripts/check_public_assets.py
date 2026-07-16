#!/usr/bin/env python3
"""Fail when web/public contains unreferenced or oversized runtime assets."""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PUBLIC = WEB / "public"
SOURCE_ROOTS = [WEB / "app", WEB / "components", WEB / "lib"]
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".css", ".json", ".md"}
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".woff", ".woff2"}
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 3 * 1024 * 1024

source = "\n".join(
    path.read_text(errors="replace")
    for root in SOURCE_ROOTS
    if root.exists()
    for path in root.rglob("*")
    if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
)

assets = [path for path in PUBLIC.rglob("*") if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES]
unreferenced: list[Path] = []
for path in assets:
    public_path = "/" + path.relative_to(PUBLIC).as_posix()
    if public_path not in source and path.name not in source:
        unreferenced.append(path)

oversized = [path for path in assets if path.stat().st_size > MAX_ASSET_BYTES]
total = sum(path.stat().st_size for path in assets)

if unreferenced or oversized or total > MAX_TOTAL_BYTES:
    if unreferenced:
        print("Unreferenced public assets:", file=sys.stderr)
        for path in unreferenced:
            print(f"  {path.relative_to(WEB)} ({path.stat().st_size} bytes)", file=sys.stderr)
    if oversized:
        print("Oversized public assets:", file=sys.stderr)
        for path in oversized:
            print(f"  {path.relative_to(WEB)} ({path.stat().st_size} bytes)", file=sys.stderr)
    if total > MAX_TOTAL_BYTES:
        print(f"Public asset budget exceeded: {total} > {MAX_TOTAL_BYTES} bytes", file=sys.stderr)
    raise SystemExit(1)

print(f"public assets ok: {len(assets)} files, {total} bytes")
