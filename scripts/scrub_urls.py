#!/usr/bin/env python3
"""
One-time retroactive URL redaction script.

Scans all JSON files in data/raw/ and data/analyzed/, applies the same
_strip_pii_url logic used at collection time, and overwrites the files
in place.  Only URL-bearing fields are modified; everything else is
preserved exactly.

Target fields: url, source_url, link, permalink
"""

import json
import glob
import os
import urllib.parse
from pathlib import Path


# ── Reimplementation of collector._strip_pii_url ──────────────────────
def _strip_pii_url(url: str) -> str:
    """Remove identifiable URLs from posts for GDPR compliance.

    Keeps the domain for source-attribution but strips the path that could
    identify specific users or posts.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        # Keep scheme + netloc (e.g. "https://reddit.com") for source context
        return f"{parsed.scheme}://{parsed.netloc}/[redacted]"
    except Exception:
        return "[redacted]"


# Fields that should be scrubbed
URL_FIELDS = {"url", "source_url", "link", "permalink"}


def _is_already_redacted(value: str) -> bool:
    """Return True if the value has already been redacted."""
    return "[redacted]" in value


def scrub_obj(obj, stats, depth=0):
    """Recursively walk a JSON structure and redact URL fields in-place.

    Works with dicts, lists, and nested combinations thereof.
    Returns the number of URLs redacted in this subtree.
    """
    if depth > 50:
        return
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            value = obj[key]
            if key in URL_FIELDS and isinstance(value, str) and value:
                if not _is_already_redacted(value):
                    obj[key] = _strip_pii_url(value)
                    stats["urls_scrubbed"] += 1
                else:
                    stats["already_redacted"] += 1
            else:
                scrub_obj(value, stats, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            scrub_obj(item, stats, depth + 1)


def main():
    project_root = Path(__file__).resolve().parent.parent
    data_dirs = [
        project_root / "data" / "raw",
        project_root / "data" / "analyzed",
    ]

    total_files = 0
    total_files_modified = 0
    total_urls_scrubbed = 0
    total_already_redacted = 0

    for data_dir in data_dirs:
        if not data_dir.is_dir():
            print(f"  Skipping {data_dir} (does not exist)")
            continue

        json_files = sorted(data_dir.glob("*.json"))
        print(f"\nScanning {data_dir}  ({len(json_files)} JSON files)")

        for json_path in json_files:
            total_files += 1
            stats = {"urls_scrubbed": 0, "already_redacted": 0}

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  WARNING: could not read {json_path.name}: {exc}")
                continue

            scrub_obj(data, stats)

            if stats["urls_scrubbed"] > 0:
                # Write back with same formatting (2-space indent, ensure_ascii off)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")  # trailing newline
                total_files_modified += 1
                total_urls_scrubbed += stats["urls_scrubbed"]
                print(f"  {json_path.name}: scrubbed {stats['urls_scrubbed']} URL(s)")
            else:
                reason = (
                    f"(all {stats['already_redacted']} already redacted)"
                    if stats["already_redacted"]
                    else "(no URL fields found)"
                )
                print(f"  {json_path.name}: no changes needed {reason}")

            total_already_redacted += stats["already_redacted"]

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("URL Redaction Summary")
    print("=" * 60)
    print(f"  Files scanned:        {total_files}")
    print(f"  Files modified:       {total_files_modified}")
    print(f"  URLs scrubbed:        {total_urls_scrubbed}")
    print(f"  Already redacted:     {total_already_redacted}")
    print("=" * 60)


if __name__ == "__main__":
    main()
