"""Delete only synthetic registration records for one explicit load-test run."""

import argparse
from dotenv import dotenv_values
from pathlib import Path
from pymongo import MongoClient
import re


RUN_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
COLLECTION = "candidatures_2026"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--confirm-run-id")
    args = parser.parse_args()

    if not RUN_ID_RE.fullmatch(args.run_id):
        parser.error("run ID must contain 8-32 lowercase hexadecimal characters")
    if args.delete and args.confirm_run_id != args.run_id:
        parser.error("--confirm-run-id must exactly match --run-id")

    config = dotenv_values(args.env_file, encoding="utf-8-sig", interpolate=False)
    collection_name = (config.get("CANDIDATURE_COLLECTION") or "candidature").strip()
    if collection_name != COLLECTION:
        raise SystemExit(f"Refusing cleanup: configured collection is {collection_name!r}.")
    uri = config.get("MONGO_URI")
    database = config.get("MONGO_DBNAME")
    if not uri or not database:
        raise SystemExit("Production MongoDB configuration is incomplete.")

    marker = re.escape(args.run_id)
    candidate_filter = {
        "first_name": "TEST-CHARGE",
        "email": {"$regex": f"^load-{marker}-[1-9][0-9]*@example\\.invalid$"},
        "cni_or_passport_number": {"$regex": f"^LOADTEST-{marker}-[1-9][0-9]*$"},
    }

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        db = client[database]
        candidates = list(db[collection_name].find(candidate_filter, {"_id": 1, "email": 1}))
        candidate_ids = [str(row["_id"]) for row in candidates]
        emails = [row["email"] for row in candidates]
        jobs_filter = {
            "kind": "candidature_confirmation",
            "candidate_id": {"$in": candidate_ids},
            "payload.email": {"$in": emails},
        }
        jobs = db["email_jobs"].count_documents(jobs_filter) if candidates else 0
        print(f"Collection: {collection_name}")
        print(f"Synthetic candidates found: {len(candidates)}")
        print(f"Matching confirmation jobs found: {jobs}")
        if not args.delete:
            print("Dry run only. Add --delete --confirm-run-id <same-run-id> to remove these exact records.")
            return
        removed_jobs = db["email_jobs"].delete_many(jobs_filter).deleted_count if candidates else 0
        removed_candidates = db[collection_name].delete_many(candidate_filter).deleted_count
        print(f"Deleted synthetic candidates: {removed_candidates}")
        print(f"Deleted matching confirmation jobs: {removed_jobs}")
        remaining = db[collection_name].count_documents(candidate_filter)
        if remaining:
            raise SystemExit(f"Cleanup verification failed: {remaining} synthetic candidates remain.")
        print("Cleanup verified.")


if __name__ == "__main__":
    main()
