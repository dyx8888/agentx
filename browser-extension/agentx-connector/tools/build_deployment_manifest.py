"""Build a safe deployment manifest for the AgentX browser connector.

The local development manifest targets localhost. This helper creates a disposable deployment
manifest with exactly one backend transport permission, without broadening platform page matches
or committing private staging domains into the source manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = CONNECTOR_ROOT / "manifest.json"
BROAD_HOST_PERMISSIONS = {"https://*/*", "http://*/*", "<all_urls>"}
LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1"}


def backend_host_permission(backend_url: str, *, allow_http_local: bool = False) -> str:
    parsed = urlparse(backend_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("backend URL must include scheme and host")
    if parsed.username or parsed.password:
        raise ValueError("backend URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("backend URL must not include query strings or fragments")
    if parsed.scheme != "https":
        if not (allow_http_local and parsed.scheme == "http" and parsed.hostname in LOCAL_HTTP_HOSTS):
            raise ValueError("backend URL must use https, except localhost with --allow-http-local")

    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}/*"


def build_manifest(source_manifest: dict[str, Any], backend_url: str, *, allow_http_local: bool = False) -> dict[str, Any]:
    manifest = json.loads(json.dumps(source_manifest))
    permission = backend_host_permission(backend_url, allow_http_local=allow_http_local)
    if permission in BROAD_HOST_PERMISSIONS:
        raise ValueError("deployment backend permission must not be broad")
    manifest["host_permissions"] = [permission]
    _validate_manifest(manifest)
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(manifest: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_manifest(manifest: dict[str, Any]) -> None:
    host_permissions = {str(item) for item in manifest.get("host_permissions", [])}
    broad = host_permissions & BROAD_HOST_PERMISSIONS
    if broad:
        raise ValueError(f"deployment manifest contains broad host permissions: {sorted(broad)}")
    if len(host_permissions) != 1:
        raise ValueError("deployment manifest must contain exactly one backend host permission")

    content_matches: list[str] = []
    for item in manifest.get("content_scripts", []):
        if isinstance(item, dict):
            content_matches.extend(str(match) for match in item.get("matches", []))
    if not content_matches:
        raise ValueError("deployment manifest must keep platform content-script matches")
    if any(match in BROAD_HOST_PERMISSIONS for match in content_matches):
        raise ValueError("deployment manifest content scripts must not use broad matches")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, help="Exact AgentX backend origin, for example https://api.example.com")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source manifest path")
    parser.add_argument("--out", required=True, help="Output deployment manifest path")
    parser.add_argument("--allow-http-local", action="store_true", help="Allow http://localhost for local dry-runs only")
    args = parser.parse_args()

    try:
        source = load_manifest(Path(args.source))
        manifest = build_manifest(source, args.backend, allow_http_local=args.allow_http_local)
        write_manifest(manifest, Path(args.out))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"manifest build failed: {exc}", file=sys.stderr)
        return 1

    print(f"deployment manifest written: {args.out}")
    print(f"backend permission: {manifest['host_permissions'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
