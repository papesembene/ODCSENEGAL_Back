#!/usr/bin/env python3
"""Reset local candidature/test/interview data while preserving test definitions."""

import argparse
import os
import sys

from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models.candidature import Candidature
from app.models.interview import InterviewCampaign, InterviewEvaluation, InterviewSlot
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_violation import TestViolation
from app.models.user import User


JURY_ACCOUNTS = (
    {
        "first_name": "Aïssatou",
        "last_name": "Ndiaye",
        "email": "aissatou.ndiaye.jury@odc.sn",
        "role": "filter",
    },
    {
        "first_name": "Mamadou",
        "last_name": "Diop",
        "email": "mamadou.diop.jury@odc.sn",
        "role": "validator",
    },
    {
        "first_name": "Fatou",
        "last_name": "Sow",
        "email": "fatou.sow.jury@odc.sn",
        "role": "motivation",
    },
)

DEFAULT_PASSWORD = "Entretien2026!"


def get_counts():
    return {
        "candidatures": Candidature.objects.count(),
        "campagnes": InterviewCampaign.objects.count(),
        "creneaux": InterviewSlot.objects.count(),
        "fiches_entretien": InterviewEvaluation.objects.count(),
        "groupes_test": TestGroup.objects.count(),
        "resultats_test": TestResult.objects.count(),
        "infractions_test": TestViolation.objects.count(),
        "jurys_entretien": User.objects(
            is_admin=True,
            profile_data__admin_scope="interview_member",
        ).count(),
        "definitions_test_conservees": Test.objects.count(),
    }


def print_summary(title, counts):
    print(f"\n{title}")
    print("-" * len(title))
    for label, count in counts.items():
        print(f"{label}: {count}")


def reset_test_definitions():
    for test in Test.objects:
        test.connectionLogs = []
        test.totalConnections = 0
        test.totalCompleted = 0
        test.save()


def create_jury_accounts(password):
    for account in JURY_ACCOUNTS:
        user = User.objects(email=account["email"]).first() or User(email=account["email"])
        user.first_name = account["first_name"]
        user.last_name = account["last_name"]
        user.password_hash = generate_password_hash(password)
        user.is_admin = True
        user.admin_type = "competences"
        user.is_active = True
        user.email_verified = True
        user.profile_type = "student"
        user.profile_data = {
            "admin_scope": "interview_member",
            "interview_role": account["role"],
        }
        user.save()


def execute_reset(password):
    InterviewEvaluation.objects.delete()
    InterviewSlot.objects.delete()
    InterviewCampaign.objects.delete()
    TestViolation.objects.delete()
    TestResult.objects.delete()
    TestGroup.objects.delete()
    Candidature.objects.delete()
    User.objects(
        is_admin=True,
        profile_data__admin_scope="interview_member",
    ).delete()

    reset_test_definitions()
    create_jury_accounts(password)


def main():
    parser = argparse.ArgumentParser(
        description="Réinitialise le parcours local candidature -> test -> entretien.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Applique réellement le nettoyage. Sans cette option, affiche seulement un aperçu.",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Mot de passe commun des comptes jury créés.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print_summary("Données avant réinitialisation", get_counts())

        if not args.execute:
            print("\nAucune donnée modifiée. Relancez avec --execute pour appliquer.")
            return

        execute_reset(args.password)
        print_summary("Données après réinitialisation", get_counts())

        print("\nComptes jury créés")
        print("-------------------")
        for account in JURY_ACCOUNTS:
            print(
                f"{account['first_name']} {account['last_name']} "
                f"({account['role']}): {account['email']}"
            )
        print(f"Mot de passe commun: {args.password}")


if __name__ == "__main__":
    main()
