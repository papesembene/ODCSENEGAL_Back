"""Local daily MongoDB/uploads backup. Invoked by the protected PowerShell task."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import zipfile

from dotenv import dotenv_values


def remove_backup(path, root):
    if path.is_symlink() or path.is_junction() or path.parent.resolve() != root.resolve():
        raise RuntimeError("Unexpected backup path; deletion refused")
    # Python 3.12 rmtree does not follow Windows directory junction targets.
    shutil.rmtree(path)


def prune(root, keep=7):
    completed = []
    partial = []
    for directory in root.iterdir():
        if not re.fullmatch(r"daily-\d{8}T\d{6}-[0-9a-f]{8}", directory.name):
            continue
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise RuntimeError("Unexpected backup link")
        try:
            valid = json.loads((directory / "complete.json").read_text(encoding="utf-8")).get("schema") == 1
        except (FileNotFoundError, ValueError):
            valid = False
        (completed if valid else partial).append(directory)
    for directory in sorted(completed, key=lambda p: p.name, reverse=True)[keep:]:
        remove_backup(directory, root)
    for directory in sorted(partial, key=lambda p: p.name, reverse=True)[2:]:
        remove_backup(directory, root)


def zip_uploads(source, target):
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in ("uploads", "app/uploads", "app/static/uploads"):
            directory = source / relative
            if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
                raise RuntimeError("Canonical uploads directory missing or linked")
            for current, directories, files in os.walk(directory, followlinks=False):
                for name in directories + files:
                    path = Path(current) / name
                    if path.is_symlink() or path.is_junction():
                        raise RuntimeError("Linked uploads entry; backup refused")
                for name in files:
                    path = Path(current) / name
                    archive.write(path, path.relative_to(source).as_posix())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Uploads ZIP verification failed")


def backup(env_file, source, tools, destination):
    values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
    uri, database = values.get("MONGO_URI", ""), values.get("MONGO_DBNAME", "")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.netloc or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", database):
        raise RuntimeError("Explicit MongoDB configuration required")
    uri_database = unquote(parsed.path.strip("/"))
    if uri_database and uri_database != database:
        raise RuntimeError("MongoDB URI and database do not match")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.is_junction():
        raise RuntimeError("Backup root cannot be linked")
    output = destination / ("daily-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    output.mkdir()
    private = output / "mongodump-private.yml"
    try:
        # JSON is valid YAML; credentials are never passed on the command line.
        private.write_text(json.dumps({"uri": uri}), encoding="utf-8")
        dump = output / "mongodb.archive.gz"
        with (output / "mongodump.log").open("wb") as log:
            result = subprocess.run([
                str(tools / "mongodump.exe"), "--config", str(private), "--db", database,
                "--archive=" + str(dump), "--gzip", "--numParallelCollections=1",
            ], stdout=log, stderr=log, timeout=3600,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode or not dump.is_file() or not dump.stat().st_size:
            raise RuntimeError("MongoDB export failed; see protected backup log")
        with gzip.open(dump, "rb") as stream:
            while stream.read(1024 * 1024):
                pass  # Verify the complete compressed stream, including its CRC.
        zip_uploads(source, output / "uploads.zip")
        shutil.copyfile(env_file, output / "api.env.production")
        files = {}
        for name in ("mongodb.archive.gz", "uploads.zip", "api.env.production"):
            digest = hashlib.sha256()
            with (output / name).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files[name] = {"bytes": (output / name).stat().st_size, "sha256": digest.hexdigest()}
        manifest = {"schema": 1, "completed_utc": datetime.now(timezone.utc).isoformat(),
                    "database": database, "files": files,
                    "consistency": "online logical dump without oplog; not a point-in-time snapshot",
                    "off_server_copy": False}
        marker = output / ".complete.tmp"
        marker.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        marker.replace(output / "complete.json")
        return output
    finally:
        private.unlink(missing_ok=True)
        prune(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = backup(args.env_file, args.source, args.tools, args.destination)
    except Exception:
        # Avoid leaking connection strings via exception messages or tool output.
        raise SystemExit("Backup failed. Previous successful backups retained; consult protected logs.") from None
    print("Sauvegarde quotidienne terminee: " + str(output))


if __name__ == "__main__":
    main()
