"""Export candidates assigned to an online test group for load tests."""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models.candidature import Candidature
from app.models.test_group import TestGroup


def export_candidates(test_id, output_path):
    app = create_app()
    with app.app_context():
        group = TestGroup.objects(test_id=test_id, status__ne="cancelled").first()
        if not group:
            raise RuntimeError(f"Aucun groupe actif trouvé pour le test {test_id}")

        candidates = list(Candidature.objects(id__in=group.candidate_ids or []))
        if not candidates:
            raise RuntimeError(f"Aucun candidat affecté au groupe {group.name}")

        with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["name", "email", "phone"])
            writer.writeheader()
            for candidate in candidates:
                writer.writerow({
                    "name": f"{candidate.first_name} {candidate.last_name}".strip(),
                    "email": candidate.email,
                    "phone": candidate.phone,
                })

        return group, len(candidates)


def main():
    parser = argparse.ArgumentParser(
        description="Exporter les candidats d'un test pour Locust/k6.",
    )
    parser.add_argument("test_id", help="ID du test en ligne")
    parser.add_argument(
        "--output",
        default="load_tests/candidats-test.csv",
        help="Chemin CSV de sortie",
    )
    args = parser.parse_args()

    group, total = export_candidates(args.test_id, args.output)
    print(f"CSV généré: {args.output}")
    print(f"Groupe: {group.name}")
    print(f"Candidats: {total}")


if __name__ == "__main__":
    main()
