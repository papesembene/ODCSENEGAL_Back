"""Seed disposable online-test data for local/preprod load tests."""

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models.candidature import Candidature
from app.models.test import Question, Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_session import TestSession


LOAD_PREFIX = "loadtest"
LOAD_DOMAIN = "load.odc.local"


def reset_load_data():
    emails = [candidate.email for candidate in Candidature.objects(email__endswith=f"@{LOAD_DOMAIN}").only("email")]
    if emails:
        TestResult.objects(candidate__email__in=emails).delete()
        TestSession.objects(candidateEmail__in=emails).delete()
    TestGroup.objects(name__startswith="[LOAD]").delete()
    Test.objects(title__startswith="[LOAD]").delete()
    Candidature.objects(email__endswith=f"@{LOAD_DOMAIN}").delete()


def seed_load_data(count, formation, output_path):
    now = datetime.now()
    scheduled_at = now - timedelta(minutes=2)
    test = Test(
        title=f"[LOAD] Test en ligne {formation}",
        referentiel=formation,
        duration=60,
        scheduledDate=scheduled_at.strftime("%Y-%m-%d"),
        scheduledTime=scheduled_at.strftime("%H:%M"),
        totalQuestions=3,
        passingScore=70,
        description="Test jetable pour validation de charge.",
        status="active",
        questions=[
            Question(
                question="Quel mot-clé permet de déclarer une constante en JavaScript ?",
                type="qcm_simple",
                options=["let", "var", "const", "define"],
                correctAnswer=2,
                score=5,
            ),
            Question(
                question="Quels éléments sont des types primitifs JavaScript ?",
                type="qcm_multiple",
                options=["string", "number", "array", "boolean"],
                correctAnswers=[0, 1, 3],
                score=5,
            ),
            Question(
                question="Expliquez brièvement le rôle d'une API.",
                type="texte_libre",
                score=5,
            ),
        ],
        createdBy="load-test",
    )
    test.save()

    candidates = []
    for index in range(1, count + 1):
      candidate = Candidature(
          first_name="Load",
          last_name=f"Candidate {index:05d}",
          email=f"{LOAD_PREFIX}+{index:05d}@{LOAD_DOMAIN}",
          phone=f"77{index:07d}"[-9:],
          date_of_birth=date(2000, 1, 1),
          place_of_birth="Dakar",
          gender="Autre",
          cni_or_passport_number=f"LOAD{index:08d}",
          nationality="Sénégalaise",
          region_of_residence="Dakar",
          current_structure="",
          education_level="Licence",
          computer_skills=True,
          available_for_10_months=True,
          desired_training=formation,
          accept_conditions=True,
          status="accepted",
      )
      candidate.save()
      candidates.append(candidate)

    group = TestGroup(
        name=f"[LOAD] Groupe {formation} {now.strftime('%Y%m%d%H%M%S')}",
        formation=formation,
        test_id=str(test.id),
        test_date=scheduled_at,
        duration=60,
        candidate_ids=[str(candidate.id) for candidate in candidates],
        location="En ligne",
        instructions="Groupe jetable pour test de charge.",
        status="scheduled",
        created_by="load-test",
    )
    group.save()

    test.candidatesGroup = str(group.id)
    test.save()
    write_candidates_csv(candidates, output_path)
    return test, group, len(candidates)


def write_candidates_csv(candidates, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["name", "email", "phone"])
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({
                "name": f"{candidate.first_name} {candidate.last_name}".strip(),
                "email": candidate.email,
                "phone": candidate.phone,
            })


def main():
    parser = argparse.ArgumentParser(
        description="Créer des données jetables pour tester la charge du parcours test en ligne.",
    )
    parser.add_argument("--count", type=int, default=100, help="Nombre de candidats jetables")
    parser.add_argument("--formation", default="Dev Web", help="Référentiel cible")
    parser.add_argument("--reset", action="store_true", help="Supprimer les anciennes données [LOAD] avant création")
    parser.add_argument("--reset-only", action="store_true", help="Supprimer les données [LOAD] puis quitter")
    parser.add_argument(
        "--output",
        default="load_tests/candidats-load.csv",
        help="Chemin CSV généré",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.reset or args.reset_only:
            reset_load_data()
            print("Anciennes données [LOAD] supprimées")

        if args.reset_only:
            return

        test, group, total = seed_load_data(args.count, args.formation, args.output)
        print(f"Test ID: {test.id}")
        print(f"Groupe: {group.name}")
        print(f"Référentiel: {formation_label(args.formation)}")
        print(f"Candidats: {total}")
        print(f"CSV: {args.output}")


def formation_label(formation):
    return formation or "Non renseigné"


if __name__ == "__main__":
    main()
