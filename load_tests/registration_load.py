"""Bounded registration bursts against API/MongoDB processes created by this script.

Never accepts a remote target or an existing MongoDB URI. No email worker runs.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import hashlib
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import psutil
from pymongo import MongoClient
import requests

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def child_environment(run_id, mongo_port, api_port, directory, threads, pool):
    # Do not inherit credentials, APM, proxy, Redis or production app settings.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    database = "odc_registration_load_" + run_id
    empty_env = directory / "empty.env"
    empty_env.write_text("# Deliberately empty; no production configuration.\n", encoding="utf-8")
    env.update({
        "ODC_ENV_FILE": str(empty_env), "ODC_LOAD_RUN_ID": run_id,
        "FLASK_ENV": "production", "HOST": "127.0.0.1", "PORT": str(api_port),
        "MONGO_URI": f"mongodb://127.0.0.1:{mongo_port}/{database}",
        "MONGO_DBNAME": database, "CANDIDATURE_COLLECTION": "candidatures_load",
        "SECRET_KEY": uuid4().hex + uuid4().hex, "JWT_SECRET_KEY": uuid4().hex + uuid4().hex,
        "FRONTEND_URL": "https://load.invalid", "CORS_ALLOWED_ORIGINS": "https://load.invalid",
        "ODC_CAMPAIGN_YEAR": "2026", "EMAIL_DELIVERY_MODE": "queued",
        "SESSION_TYPE": "filesystem", "RUN_INDEX_MAINTENANCE": "false",
        "RUN_PREPROD_SEED": "false", "APP_VERSION": "load-" + run_id,
        "WAITRESS_THREADS": str(threads), "MONGO_MAX_POOL_SIZE": str(pool),
        "MONGO_MIN_POOL_SIZE": "0", "LOG_DIR": str(directory / "logs"),
        "PYTHONWARNINGS": "ignore", "PYTHONUNBUFFERED": "1",
    })
    return env


def serve_child():
    # Validate the private launcher contract before importing app (which loads env).
    run_id = os.environ.get("ODC_LOAD_RUN_ID", "")
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise RuntimeError("This entrypoint requires the isolated load-test launcher")
    database = "odc_registration_load_" + run_id
    if os.environ.get("MONGO_DBNAME") != database or not os.environ.get("MONGO_URI", "").startswith(
        "mongodb://127.0.0.1:"
    ):
        raise RuntimeError("Nonlocal or unexpected test database")
    sys.path.insert(0, str(ROOT))
    from run import run_server
    run_server()


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2) if values else None


def summarize(samples):
    return {
        "requests": len(samples), "errors": sum(not sample[2] for sample in samples),
        "statuses": dict(Counter(str(sample[1]) for sample in samples)),
        "p50_ms": percentile([s[0] for s in samples], .50),
        "p95_ms": percentile([s[0] for s in samples], .95),
        "p99_ms": percentile([s[0] for s in samples], .99),
    }


def candidate(run_id, index, training_site="dakar"):
    return {
        "first_name": "Charge", "last_name": "Synthetique",
        "email": f"load-{run_id}-{index}@example.org", "phone": "770000000",
        "date_of_birth": "2000-01-01", "place_of_birth": "Dakar", "gender": "male",
        "cni_or_passport_number": f"LOAD-{run_id}-{index}", "nationality": "Senegalaise",
        "region_of_residence": "Dakar", "computer_skills": True,
        "available_for_10_months": True, "desired_training": "Dev Web", "accept_conditions": True,
        "training_site": training_site,
    }


def journey(base_url, payload, gate):
    gate.wait()
    samples = {}
    with requests.Session() as session:
        session.trust_env = False
        calls = (
            ("status", "GET", "/api/candidature/status", {"params": {"formation": payload["desired_training"]}}, 200),
            ("unique", "GET", "/api/candidature/check-unique", {"params": {"field": "email", "value": payload["email"]}}, 200),
            ("apply", "POST", "/api/candidature/apply", {"json": payload}, 201),
        )
        for name, method, path, kwargs, expected in calls:
            started = time.perf_counter()
            try:
                response = session.request(method, base_url + path, timeout=20, allow_redirects=False, **kwargs)
                body = response.json()
                ok = response.status_code == expected
                if name == "apply":
                    ok = ok and bool(body.get("candidature_id")) and body.get("email_status") == "queued"
                elif name == "status":
                    ok = ok and body.get("data", {}).get("isOpen") is True
                else:
                    ok = ok and body.get("exists") is False
                samples[name] = ((time.perf_counter() - started) * 1000, response.status_code, ok)
            except (requests.RequestException, ValueError):
                samples[name] = ((time.perf_counter() - started) * 1000, "exception", False)
    return samples


def sample_resources(processes, stop, measurements):
    known = {}
    while not stop.is_set():
        sample = {"system_cpu_percent": psutil.cpu_percent()}
        for label, process in processes.items():
            cpu, rss = 0., 0
            try:
                parent = psutil.Process(process.pid)
                for item in [parent, *parent.children(recursive=True)]:
                    identity = (item.pid, item.create_time())
                    observed = known.setdefault(identity, item)
                    cpu += observed.cpu_percent()
                    rss += observed.memory_info().rss
            except psutil.Error:
                pass
            sample[label + "_cpu_percent"] = cpu
            sample[label + "_rss_mb"] = round(rss / 1024**2, 2)
        measurements.append(sample)
        stop.wait(.25)


def stop_process(process):
    if process and process.poll() is None:
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        # Windows venv launchers may have a base-interpreter child.
        for child in descendants:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(descendants, timeout=5)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass


def execute(args):
    run_id = uuid4().hex
    report = {
        "run_id": run_id, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "local API + disposable MongoDB; no IIS/TLS/frontend/Redis/email delivery",
        "logical_cpus": psutil.cpu_count(), "waitress_threads": args.threads,
        "mongo_pool": args.pool, "stages": [], "cleanup_complete": False,
        "training_site": args.site,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    report["commit"] = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    api = mongo = client = None
    stop = threading.Event()
    monitor = None
    failed = False
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="odc-registration-load-") as scratch:
        directory = Path(scratch)
        with (directory / "processes.log").open("wb") as logs:
            try:
                mongo_port, api_port = free_port(), free_port()
                while mongo_port == api_port:
                    api_port = free_port()
                env = child_environment(run_id, mongo_port, api_port, directory, args.threads, args.pool)
                database = env["MONGO_DBNAME"]
                data = directory / "mongo"
                data.mkdir()
                flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                mongo = subprocess.Popen([
                    str(args.mongod.resolve()), "--bind_ip", "127.0.0.1", "--port", str(mongo_port),
                    "--dbpath", str(data), "--wiredTigerCacheSizeGB", "0.25",
                ], stdout=logs, stderr=logs, **flags)
                client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=500)
                for attempt in range(60):
                    if mongo.poll() is not None:
                        raise RuntimeError("Disposable MongoDB stopped during startup")
                    try:
                        client.admin.command("ping")
                        break
                    except Exception:
                        if attempt == 59:
                            raise
                        time.sleep(.5)
                db = client[database]
                now = datetime.now(timezone.utc)
                db.candidature_campaigns.insert_one({
                    "title": "[LOAD] Inscriptions synthetiques", "formation": "all", "status": "published",
                    "start_at": now - timedelta(days=1), "end_at": now + timedelta(days=1),
                })
                report["mongo_version"] = client.server_info()["version"]
                api = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                    cwd=directory, env=env, stdout=logs, stderr=logs, **flags)
                base_url = f"http://127.0.0.1:{api_port}"
                with requests.Session() as session:
                    session.trust_env = False
                    for attempt in range(60):
                        if api.poll() is not None:
                            raise RuntimeError("Isolated API stopped during startup")
                        try:
                            health = session.get(base_url + "/health", timeout=2).json()
                            if health.get("status") == "healthy" and health.get("version") == "load-" + run_id:
                                break
                        except (requests.RequestException, ValueError):
                            pass
                        if attempt == 59:
                            raise RuntimeError("Isolated API did not become healthy")
                        time.sleep(.5)
                # Warm indexes using an actual application before measuring.
                gate = threading.Event()
                gate.set()
                warmup = journey(base_url, candidate(run_id, "warmup", args.site), gate)
                if not all(value[2] for value in warmup.values()):
                    raise RuntimeError(f"Warmup failed: {warmup}")
                measurements = []
                monitor = threading.Thread(target=sample_resources, args=({"api": api, "mongo": mongo}, stop, measurements), daemon=True)
                monitor.start()
                expected_documents = 1
                for level in args.levels:
                    start_sample = len(measurements)
                    gate = threading.Event()
                    with ThreadPoolExecutor(max_workers=level) as pool:
                        futures = [pool.submit(journey, base_url, candidate(run_id, f"{level}-{index}", args.site), gate)
                                   for index in range(args.count)]
                        started = time.perf_counter()
                        gate.set()
                        results = [future.result() for future in futures]
                    elapsed = time.perf_counter() - started
                    stage = {"concurrency": level, "candidates": args.count, "duration_s": round(elapsed, 3),
                             "journeys_per_second": round(args.count / elapsed, 2),
                             "endpoints": {name: summarize([row[name] for row in results]) for name in ("status", "unique", "apply")}}
                    successful = sum(row["apply"][2] for row in results)
                    expected_documents += successful
                    stage["stored_candidates"] = db.candidatures_load.count_documents({})
                    stage["queued_emails"] = db.email_jobs.count_documents({"kind": "candidature_confirmation", "status": "pending"})
                    stage["integrity_ok"] = stage["stored_candidates"] == stage["queued_emails"] == expected_documents
                    readings = measurements[start_sample:]
                    stage["peak_resources"] = {key: max(row[key] for row in readings) for key in readings[0]} if readings else {}
                    stage["passed"] = stage["integrity_ok"] and all(item["errors"] == 0 for item in stage["endpoints"].values()) and stage["endpoints"]["apply"]["p95_ms"] <= args.max_p95_ms
                    report["stages"].append(stage)
                    print(json.dumps(stage), flush=True)
                    if not stage["passed"] or stage["peak_resources"].get("system_cpu_percent", 0) > 85:
                        report["stop_reason"] = "threshold, integrity, request error or system CPU >85%; no higher stage attempted"
                        failed = True
                        break
            except Exception as error:
                report["error"] = str(error)
                failed = True
            finally:
                stop.set()
                if monitor:
                    monitor.join(timeout=5)
                stop_process(api)
                if client:
                    client.close()
                stop_process(mongo)
                report["cleanup_complete"] = True
        if failed:
            output.with_suffix(".log").write_bytes((directory / "processes.log").read_bytes())
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {output}", flush=True)
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--serve"]:
        serve_child()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongod", type=Path, required=True, help="Existing mongod executable; a new isolated process is started")
    parser.add_argument("--levels", default="10,25,50", help="Increasing concurrency levels (max 100)")
    parser.add_argument("--count", type=int, default=100, help="Candidate journeys per level (max 2000)")
    parser.add_argument("--site", default="dakar", help="Training-site code for synthetic candidates (default: dakar)")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--pool", type=int, default=50)
    parser.add_argument("--max-p95-ms", type=float, default=1500)
    parser.add_argument("--output", type=Path, default=ROOT / "load_tests" / "reports" / ("registration-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"))
    args = parser.parse_args()
    try:
        args.levels = [int(value) for value in args.levels.split(",")]
    except ValueError:
        parser.error("levels must be comma-separated integers")
    if not args.levels or args.levels != sorted(set(args.levels)) or not 1 <= min(args.levels) <= max(args.levels) <= 100:
        parser.error("levels must be distinct, increasing, between 1 and 100")
    if not max(args.levels) <= args.count <= 2000 or not 1 <= args.threads <= 32 or not 1 <= args.pool <= 100 or not args.max_p95_ms > 0:
        parser.error("invalid count, thread, pool or latency bounds")
    if len(args.site) > 80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.site):
        parser.error("site must be a valid training-site code (for example dakar)")
    if not args.mongod.is_file():
        parser.error("mongod executable not found")
    return execute(args)


if __name__ == "__main__":
    sys.exit(main())
