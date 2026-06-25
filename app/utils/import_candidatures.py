"""CLI utility to import legacy candidature CSV exports."""

import argparse
import csv
from datetime import datetime
import os

import pymongo


def parse_boolean(value):
    return str(value or "").strip().lower() in {
        "1",
        "oui",
        "yes",
        "true",
    }


def build_document(row):
    return {
        "last_name": row.get("Nom", "").strip(),
        "first_name": row.get("Prénom", "").strip(),
        "date_of_birth": datetime.strptime(
            row.get("Date de Naissance ", "").strip(),
            "%Y-%m-%d",
        ),
        "place_of_birth": row.get("Lieu de naissance ", "").strip(),
        "gender": row.get("Genre", "").strip(),
        "nationality": row.get("Nationalité", "").strip(),
        "cni_or_passport_number": row.get(
            "N° CNI ou Passeport",
            "",
        ).strip(),
        "region_of_residence": row.get(
            "Region de Residence",
            "",
        ).strip(),
        "email": row.get("Email", "").strip().lower(),
        "phone": row.get("Téléphone", "").strip(),
        "education_level": row.get("Niveau d’étude ", "").strip(),
        "current_structure": row.get(
            "Structure actuelle (université, lycée, école de formation) ?",
            "",
        ).strip(),
        "speciality": row.get(
            "Spécialité (faculté, ufr, série…) ?",
            "",
        ).strip(),
        "computer_skills": parse_boolean(
            row.get("As-tu des notions en informatique ?")
        ),
        "is_working": parse_boolean(
            row.get(
                "Travailles-tu dans une entreprise actuellement ?"
            )
        ),
        "contract_type": _first_matching_value(
            row,
            "Si oui,quel type de contrat ?",
        ),
        "available_for_10_months": parse_boolean(
            _first_matching_value(
                row,
                "Es-tu dispo pour te consacrer exclusivement",
            )
        ),
        "created_at": datetime.strptime(
            row.get("Created At", "").strip(),
            "%Y-%m-%d %H:%M:%S",
        ),
    }


def import_csv(csv_path, mongo_uri, database_name, dry_run=False):
    documents = []
    with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
        for line_number, row in enumerate(
            csv.DictReader(csv_file),
            start=2,
        ):
            try:
                documents.append(build_document(row))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Ligne CSV invalide {line_number}: {error}"
                ) from error
    if dry_run or not documents:
        return len(documents)
    client = pymongo.MongoClient(mongo_uri)
    try:
        result = client[database_name]["candidatures"].insert_many(
            documents,
            ordered=False,
        )
        return len(result.inserted_ids)
    finally:
        client.close()


def _first_matching_value(row, prefix):
    for key, value in row.items():
        if key.strip().startswith(prefix):
            return str(value or "").strip()
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("MONGO_URI", "mongodb://localhost:27017/odcdb"),
    )
    parser.add_argument(
        "--database",
        default=os.getenv("MONGO_DBNAME", "odcdb"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = import_csv(
        args.csv_path,
        args.mongo_uri,
        args.database,
        dry_run=args.dry_run,
    )
    action = "validées" if args.dry_run else "importées"
    print(f"{count} candidature(s) {action}.")


if __name__ == "__main__":
    main()
