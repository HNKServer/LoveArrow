#!/usr/bin/env python3
"""Mirror an NPPS4-DLAPI archive into NPPS4's internal archive layout.

Default server is the public archive used in the LL Hax NPPS4 docs.
The generated directory can be used as:

    [download]
    backend = "internal"
    [download.internal]
    archive_root = "/path/to/output"

This script intentionally uses only Python stdlib.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

DEFAULT_SERVER = "https://ll.sif.moe/npps4_dlapi"
DEFAULT_PACKAGE_TYPES = [0, 1, 2, 3, 4, 5, 6]
DEFAULT_PLATFORMS = ["Android"]
# These are the DB names NPPS4 currently opens via download.get_db_path(...).
DEFAULT_DB_NAMES = [
    "achievement",
    "effort",
    "exchange",
    "game_mater",
    "item",
    "live",
    "museum",
    "scenario",
    "subscenario",
    "unit",
]
PLATFORM_IDS = {"iOS": 1, "Android": 2}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def parse_csv_ints(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def parse_csv_strs(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def join_api(base: str, endpoint: str) -> str:
    if not base.endswith("/"):
        base += "/"
    return urllib.parse.urljoin(base, endpoint.lstrip("/"))


class DlApi:
    def __init__(self, server: str, shared_key: str = "", timeout: int = 60, retries: int = 5):
        self.server = server.rstrip("/") + "/"
        self.shared_key = shared_key
        self.timeout = timeout
        self.retries = retries

    def request(self, endpoint: str, payload: Any | None = None, *, raw: bool = False) -> Any:
        url = join_api(self.server, endpoint)
        headers = {"User-Agent": "NPPS4-DLAPI-mirror/1.0"}
        data = None
        if self.shared_key:
            headers["DLAPI-Shared-Key"] = urllib.parse.quote(self.shared_key)
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                if raw:
                    return body
                return json.loads(body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - command-line retry wrapper
                last_exc = exc
                if attempt == self.retries:
                    break
                wait = min(30, 2 ** (attempt - 1))
                eprint(f"[retry {attempt}/{self.retries}] {endpoint}: {exc}; sleeping {wait}s")
                time.sleep(wait)
        assert last_exc is not None
        raise last_exc


def file_name_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        name = f"download-{digest}.bin"
    # Avoid path traversal / Windows separator confusion.
    return name.replace("/", "_").replace("\\", "_")


def checksum(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_existing_ok(path: Path, size: int | None, md5: str | None, sha256: str | None) -> bool:
    if not path.is_file():
        return False
    if size is not None and path.stat().st_size != size:
        return False
    if md5 and checksum(path, "md5").lower() != md5.lower():
        return False
    if sha256 and checksum(path, "sha256").lower() != sha256.lower():
        return False
    return True


def normalize_link(item: dict[str, Any]) -> dict[str, Any]:
    checksums = item.get("checksums") or {}
    return {
        "url": str(item["url"]),
        "size": int(item.get("size") or 0),
        "md5": str(checksums.get("md5") or ""),
        "sha256": str(checksums.get("sha256") or ""),
        "version": str(item.get("version") or ""),
        "packageId": item.get("packageId", item.get("package_id")),
    }


def download_one(link: dict[str, Any], dest: Path, timeout: int, retries: int, dry_run: bool = False) -> tuple[Path, str]:
    url = link["url"]
    size = int(link.get("size") or 0) or None
    md5 = link.get("md5") or None
    sha256 = link.get("sha256") or None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_existing_ok(dest, size, md5, sha256):
        return dest, "skip"
    if dry_run:
        return dest, "dry-run"

    tmp = dest.with_suffix(dest.suffix + ".part")
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NPPS4-DLAPI-mirror/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            if not is_existing_ok(tmp, size, md5, sha256):
                raise RuntimeError(f"checksum/size mismatch for {url}")
            os.replace(tmp, dest)
            return dest, "download"
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
            # Android may receive http links from NPPS4, but the source may only serve https, or vice versa.
            if attempt == 1 and url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            elif attempt == 1 and url.startswith("https://"):
                url = "http://" + url[len("https://"):]
            if attempt < retries:
                time.sleep(min(30, 2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def infov2_item(link: dict[str, Any], name: str) -> dict[str, Any]:
    return {
        "name": name,
        "size": int(link.get("size") or 0),
        "md5": link.get("md5") or "",
        "sha256": link.get("sha256") or "",
    }


def run_downloads(tasks: list[tuple[dict[str, Any], Path]], workers: int, timeout: int, retries: int, dry_run: bool) -> None:
    total = len(tasks)
    if total == 0:
        return
    done = 0
    stats = {"skip": 0, "download": 0, "dry-run": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(download_one, link, dest, timeout, retries, dry_run) for link, dest in tasks]
        for fut in concurrent.futures.as_completed(futs):
            path, status = fut.result()
            stats[status] = stats.get(status, 0) + 1
            done += 1
            if done % 25 == 0 or done == total:
                eprint(f"[files] {done}/{total} done; {stats}")


def mirror(args: argparse.Namespace) -> None:
    api = DlApi(args.server, args.shared_key, timeout=args.timeout, retries=args.retries)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    public = api.request("api/publicinfo")
    game_version = str(public.get("gameVersion") or public.get("game_version") or "")
    if not game_version:
        raise RuntimeError(f"api/publicinfo did not contain gameVersion: {public!r}")
    eprint(f"DLAPI publicinfo gameVersion={game_version} server={args.server}")
    write_json(out / "generation.json", {"major": 1, "minor": 1})
    write_json(out / "dlapi_publicinfo.json", public)
    write_json(out / "release_info.json", api.request("api/v1/release_info"))

    platforms = parse_csv_strs(args.platforms)
    package_types = parse_csv_ints(args.package_types)
    db_names = parse_csv_strs(args.db_names)
    tasks: list[tuple[dict[str, Any], Path]] = []

    # Databases. NPPS4 internal backend accepts DBs under either iOS or Android platform path;
    # writing them for every selected platform makes the archive self-contained.
    if not args.no_db:
        for platform_name in platforms:
            db_dir = out / platform_name / "package" / game_version / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            for db_name in db_names:
                try:
                    raw = api.request(f"api/v1/getdb/{db_name}", raw=True)
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        eprint(f"[db] skip missing {db_name}")
                        continue
                    raise
                target = db_dir / f"{db_name}.db_"
                if not target.exists() or target.read_bytes() != raw:
                    if not args.dry_run:
                        target.write_bytes(raw)
                eprint(f"[db] {platform_name}/{db_name}.db_ {len(raw)} bytes")

    for platform_name in platforms:
        if platform_name not in PLATFORM_IDS:
            raise ValueError(f"unknown platform {platform_name!r}; choose from {', '.join(PLATFORM_IDS)}")
        platform_id = PLATFORM_IDS[platform_name]

        # Update packages from a low version to current.
        update_resp = api.request("api/v1/update", {"version": args.from_version, "platform": platform_id})
        update_links = [normalize_link(x) for x in update_resp]
        versions: set[str] = set()
        grouped_updates: dict[str, list[dict[str, Any]]] = {}
        for link in update_links:
            ver = link.get("version") or game_version
            versions.add(ver)
            name = file_name_from_url(link["url"])
            dest = out / platform_name / "update" / ver / name
            grouped_updates.setdefault(ver, []).append(infov2_item(link, name))
            tasks.append((link, dest))
        if versions:
            write_json(out / platform_name / "update" / "infov2.json", sorted(versions, key=lambda s: tuple(int(p) for p in s.split(".") if p.isdigit())))
            for ver, items in grouped_updates.items():
                write_json(out / platform_name / "update" / ver / "infov2.json", items)
        else:
            write_json(out / platform_name / "update" / "infov2.json", [game_version])
            write_json(out / platform_name / "update" / game_version / "infov2.json", [])

        # Batch/package archives.
        for ptype in package_types:
            try:
                batch_resp = api.request("api/v1/batch", {"package_type": ptype, "platform": platform_id, "exclude": []})
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    eprint(f"[batch] skip missing platform={platform_name} package_type={ptype}")
                    continue
                raise
            links = [normalize_link(x) for x in batch_resp]
            ids: set[int] = set()
            grouped: dict[int, list[dict[str, Any]]] = {}
            for link in links:
                if link.get("packageId") is None:
                    eprint(f"[batch] warning: no packageId in {link['url']}")
                    continue
                pid = int(link["packageId"])
                ids.add(pid)
                name = file_name_from_url(link["url"])
                dest = out / platform_name / "package" / game_version / str(ptype) / str(pid) / name
                grouped.setdefault(pid, []).append(infov2_item(link, name))
                tasks.append((link, dest))
            ptype_root = out / platform_name / "package" / game_version / str(ptype)
            if ids:
                write_json(ptype_root / "info.json", sorted(ids))
                for pid, items in grouped.items():
                    write_json(ptype_root / str(pid) / "infov2.json", items)
            else:
                write_json(ptype_root / "info.json", [])
            eprint(f"[batch] {platform_name} type={ptype} packages={len(ids)} files={len(links)}")

    write_json(out / "mirror_manifest.json", {
        "source_server": args.server,
        "gameVersion": game_version,
        "platforms": platforms,
        "package_types": package_types,
        "db_names": db_names if not args.no_db else [],
        "file_tasks": len(tasks),
        "created_by": "fetch_npps4_dlapi_archive.py",
    })

    if not args.metadata_only:
        run_downloads(tasks, workers=args.workers, timeout=args.timeout, retries=args.retries, dry_run=args.dry_run)
    else:
        eprint("metadata-only: skipped package file downloads")

    eprint("Done. Configure NPPS4:")
    eprint('[download]\nbackend = "internal"')
    eprint('[download.internal]')
    eprint(f'archive_root = "{out.as_posix()}"')


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--server", default=DEFAULT_SERVER, help="NPPS4-DLAPI base URL")
    p.add_argument("--shared-key", default="", help="optional DLAPI shared key")
    p.add_argument("--out", default="sif_gl_archive", help="output archive root")
    p.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS), help="comma-separated platforms: Android,iOS")
    p.add_argument("--package-types", default=",".join(map(str, DEFAULT_PACKAGE_TYPES)), help="comma-separated package types")
    p.add_argument("--from-version", default="0.0", help="version to request updates from")
    p.add_argument("--db-names", default=",".join(DEFAULT_DB_NAMES), help="comma-separated DB names to fetch")
    p.add_argument("--no-db", action="store_true", help="skip DB downloads")
    p.add_argument("--metadata-only", action="store_true", help="write info.json/infov2.json but don't fetch package binaries")
    p.add_argument("--dry-run", action="store_true", help="don't write downloaded package binaries")
    p.add_argument("--workers", type=int, default=8, help="parallel package download workers")
    p.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    p.add_argument("--retries", type=int, default=5, help="HTTP retry count")
    args = p.parse_args(argv)
    mirror(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
