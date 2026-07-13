#!/usr/bin/env python3
"""Seed preproduction data for ODC Senegal.

Usage:
    MONGO_URI="mongodb+srv://..." MONGO_DBNAME="odcdb_preprod" \
    .venv/bin/python seed_preprod_demo.py --reset-demo

The script is idempotent and only resets demo data identified by its own
emails/titles when --reset-demo is provided.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.interview import (
    InterviewCampaign,
    InterviewEvaluation,
    InterviewSlot,
)
from app.models.test import Question, Test
from app.models.test_group import TestGroup
from app.models.test_result import Candidate, TestResult
from app.models.test_violation import TestViolation
from app.models.user import User
from app.services.interviews.scorecard_service import (
    get_default_scorecard_config,
)
from app.utils.fix_indexes import ensure_critical_indexes


PASSWORD = os.getenv("SEED_DEFAULT_PASSWORD", "Passer123!")
ADMIN_EMAILS = {
    "super_admin": "superadmin.preprod@odc.sn",
    "competences": "competences.preprod@odc.sn",
    "startups": "startups.preprod@odc.sn",
    "cm": "cm.preprod@odc.sn",
}
JURY_MEMBERS = [
    {
        "email": "filtreur.preprod@odc.sn",
        "first_name": "Awa",
        "last_name": "Diop",
        "role": "filter",
    },
    {
        "email": "coach.preprod@odc.sn",
        "first_name": "Karim",
        "last_name": "Ndiaye",
        "role": "validator",
    },
    {
        "email": "motivation.preprod@odc.sn",
        "first_name": "Mame",
        "last_name": "Fall",
        "role": "motivation",
    },
]
FORMATIONS = [
    {
        "key": "dev-web-mobile",
        "label": "Dev Web Mobile",
        "candidate_prefix": "dwm",
    },
    {
        "key": "data",
        "label": "Data",
        "candidate_prefix": "data",
    },
]


def upsert_user(email, first_name, last_name, admin_type, profile_data=None):
    user = User.objects(email=email).first() or User(email=email)
    user.first_name = first_name
    user.last_name = last_name
    user.password_hash = generate_password_hash(PASSWORD)
    user.is_admin = True
    user.admin_type = admin_type
    user.is_active = True
    user.email_verified = True
    user.profile_type = "student"
    user.profile_data = profile_data or {}
    user.save()
    return user


def upsert_candidature(index, formation, prefix, admitted=True):
    email = f"{prefix}.candidat{index}@preprod.odc.sn"
    candidate = Candidature.objects(email=email).first() or Candidature(
        email=email
    )
    candidate.first_name = ["Moussa", "Fatou", "Ibrahima", "Aminata"][
        (index - 1) % 4
    ]
    candidate.last_name = ["Ba", "Sarr", "Diouf", "Ndiaye"][
        (index - 1) % 4
    ]
    candidate.phone = f"77{index:07d}"
    candidate.date_of_birth = date(2000, min(index, 12), 10)
    candidate.place_of_birth = "Dakar"
    candidate.gender = "Homme" if index % 2 else "Femme"
    candidate.cni_or_passport_number = f"PREPROD-{prefix.upper()}-{index:03d}"
    candidate.nationality = "Sénégalaise"
    candidate.region_of_residence = "Dakar"
    candidate.current_structure = "ODC Preprod"
    candidate.education_level = "Licence"
    candidate.computer_skills = True
    candidate.available_for_10_months = True
    candidate.desired_training = formation
    candidate.accept_conditions = True
    candidate.speciality = "Développement" if formation == "dev-web-mobile" else "Data"
    candidate.is_working = False
    candidate.status = "accepted" if admitted else "pending"
    candidate.created_at = datetime.utcnow() - timedelta(days=10 - index)
    candidate.save()
    return candidate


def upsert_test(formation, label):
    test = Test.objects(title=f"Préprod - Test {label}").first() or Test(
        title=f"Préprod - Test {label}"
    )
    test.referentiel = formation
    test.duration = 60
    test.scheduledDate = (datetime.utcnow() + timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    test.scheduledTime = "09:00"
    test.totalQuestions = 3
    test.passingScore = 70
    test.candidatesGroup = f"Groupe préprod {label}"
    test.description = f"Test de validation préproduction pour {label}"
    test.status = "active"
    test.createdBy = ADMIN_EMAILS["competences"]
    test.questions = [
        Question(
            question="Que signifie HTML ?",
            type="qcm_simple",
            options=[
                "HyperText Markup Language",
                "Home Tool Markup Language",
                "Hyperlink Text Manager",
            ],
            correctAnswer=0,
            score=5,
        ),
        Question(
            question="Quels éléments sont des structures de contrôle ?",
            type="qcm_multiple",
            options=["if", "for", "while", "console.log"],
            correctAnswers=[0, 1, 2],
            score=5,
        ),
        Question(
            question="Expliquez brièvement le rôle d'une API.",
            type="texte_libre",
            score=5,
        ),
    ]
    test.updatedAt = datetime.utcnow()
    test.save()
    return test


def upsert_group(test, candidates, formation, label):
    group = TestGroup.objects(name=f"Préprod - Groupe {label}").first() or TestGroup(
        name=f"Préprod - Groupe {label}"
    )
    group.formation = formation
    group.test_id = str(test.id)
    group.test_date = datetime.utcnow() + timedelta(days=1, hours=9)
    group.duration = test.duration
    group.candidate_ids = [str(candidate.id) for candidate in candidates]
    group.location = "En ligne"
    group.instructions = "Vérifiez votre connexion avant le démarrage."
    group.status = "scheduled"
    group.created_by = ADMIN_EMAILS["competences"]
    group.updated_at = datetime.utcnow()
    group.save()
    return group


def upsert_result(test, candidate, score=100, admitted=True):
    result = TestResult.objects(
        testId=str(test.id),
        candidate__email=candidate.email,
    ).first() or TestResult(
        testId=str(test.id),
        candidate=Candidate(
            name=f"{candidate.first_name} {candidate.last_name}",
            email=candidate.email,
            phone=candidate.phone,
        ),
    )
    result.testTitle = test.title
    result.referentiel = test.referentiel
    result.answers = {
        "0": 0,
        "1": [0, 1, 2],
        "2": "Une API permet à deux applications d'échanger des données.",
    }
    result.score = score
    result.status = "admis" if admitted else "rejeté"
    result.completedAt = datetime.utcnow() - timedelta(hours=2)
    result.submittedDate = result.completedAt.strftime("%d/%m/%Y")
    result.submittedTime = result.completedAt.strftime("%H:%M")
    result.manualGrades = {"2": 5}
    result.save()
    return result


def upsert_interview_campaign(formation, label):
    name = f"Préprod - Entretiens {label}"
    campaign = InterviewCampaign.objects(name=name).first() or InterviewCampaign(
        name=name
    )
    campaign.formation = formation
    campaign.description = f"Campagne d'entretiens préproduction pour {label}"
    campaign.status = "active"
    campaign.scorecard_config = get_default_scorecard_config(formation)
    campaign.filter_questions = [
        {
            "question": "Présentez un projet technique dont vous êtes fier.",
            "expected_answer": (
                "Le candidat doit expliquer le contexte, son rôle, "
                "les difficultés et le résultat."
            ),
        },
        {
            "question": "Comment réagissez-vous face à un bug bloquant ?",
            "expected_answer": (
                "Le candidat doit parler de diagnostic, priorisation, "
                "communication et tests."
            ),
        },
    ]
    campaign.created_by = ADMIN_EMAILS["competences"]
    campaign.updated_at = datetime.utcnow()
    campaign.save()
    return campaign


def upsert_slot(campaign, formation, label, users):
    slot = InterviewSlot.objects(
        campaign_id=str(campaign.id),
        label=f"Préprod - Créneau {label} matin",
    ).first() or InterviewSlot(
        campaign_id=str(campaign.id),
        label=f"Préprod - Créneau {label} matin",
    )
    slot.formation = formation
    slot.start_at = datetime.utcnow() + timedelta(days=3, hours=9)
    slot.end_at = slot.start_at + timedelta(hours=2)
    slot.capacity = 0
    slot.waiting_capacity = 0
    slot.assigned_filter_ids = [str(users["filter"].id)]
    slot.assigned_jury_ids = [str(users["filter"].id)]
    slot.assigned_validator_ids = [str(users["validator"].id)]
    slot.assigned_motivation_ids = [str(users["motivation"].id)]
    slot.assignments = {
        "filter": [str(users["filter"].id)],
        "validator": [str(users["validator"].id)],
        "motivation": [str(users["motivation"].id)],
    }
    slot.status = "scheduled"
    slot.updated_at = datetime.utcnow()
    slot.save()
    return slot


def upsert_evaluation(campaign, slot, candidate):
    evaluation = InterviewEvaluation.objects(
        campaign_id=str(campaign.id),
        candidature_id=str(candidate.id),
    ).first() or InterviewEvaluation(
        campaign_id=str(campaign.id),
        candidature_id=str(candidate.id),
    )
    evaluation.slot_id = str(slot.id)
    evaluation.candidate_snapshot = {
        "id": str(candidate.id),
        "first_name": candidate.first_name,
        "last_name": candidate.last_name,
        "name": f"{candidate.first_name} {candidate.last_name}",
        "email": candidate.email,
        "phone": candidate.phone,
        "desired_training": candidate.desired_training,
    }
    evaluation.interview_progress_status = "planifie"
    evaluation.final_status = "en_attente"
    evaluation.is_complete = False
    evaluation.updated_at = datetime.utcnow()
    evaluation.save()
    return evaluation


def upsert_candidature_campaign(formation, label):
    campaign = CandidatureCampaign.objects(
        title=f"Appel à Candidature - Préprod {label}",
        formation=formation,
    ).first() or CandidatureCampaign(
        title=f"Appel à Candidature - Préprod {label}",
        formation=formation,
    )
    campaign.promotion = "Promotion Préprod 2026"
    campaign.start_at = datetime.utcnow() - timedelta(days=1)
    campaign.end_at = datetime.utcnow() + timedelta(days=30)
    campaign.status = "published"
    campaign.description = (
        f"Campagne de candidature préproduction pour {label}."
    )
    campaign.created_by = ADMIN_EMAILS["super_admin"]
    campaign.updated_by = ADMIN_EMAILS["super_admin"]
    campaign.updated_at = datetime.utcnow()
    campaign.save()
    return campaign


def reset_demo_data():
    demo_emails = list(ADMIN_EMAILS.values()) + [
        member["email"] for member in JURY_MEMBERS
    ]
    demo_candidate_emails = [
        f"{formation['candidate_prefix']}.candidat{index}@preprod.odc.sn"
        for formation in FORMATIONS
        for index in range(1, 5)
    ]
    demo_emails.extend(demo_candidate_emails)

    User.objects(email__in=demo_emails).delete()
    Candidature.objects(email__in=demo_candidate_emails).delete()
    Test.objects(title__startswith="Préprod -").delete()
    TestGroup.objects(name__startswith="Préprod -").delete()
    TestResult.objects(candidate__email__in=demo_candidate_emails).delete()
    TestViolation.objects(candidateEmail__in=demo_candidate_emails).delete()
    InterviewCampaign.objects(name__startswith="Préprod -").delete()
    InterviewSlot.objects(label__startswith="Préprod -").delete()
    CandidatureCampaign.objects(title__startswith="Appel à Candidature - Préprod").delete()
    InterviewEvaluation.objects(
        candidate_snapshot__email__in=demo_candidate_emails
    ).delete()


def seed():
    admins = {
        "super_admin": upsert_user(
            ADMIN_EMAILS["super_admin"],
            "Super",
            "Admin",
            "super_admin",
        ),
        "competences": upsert_user(
            ADMIN_EMAILS["competences"],
            "Admin",
            "Compétences",
            "competences",
        ),
        "startups": upsert_user(
            ADMIN_EMAILS["startups"],
            "Admin",
            "Startups",
            "startups",
        ),
        "cm": upsert_user(
            ADMIN_EMAILS["cm"],
            "Community",
            "Manager",
            "cm",
        ),
    }
    jury_users = {
        member["role"]: upsert_user(
            member["email"],
            member["first_name"],
            member["last_name"],
            "competences",
            {
                "admin_scope": "interview_member",
                "interview_role": member["role"],
            },
        )
        for member in JURY_MEMBERS
    }

    summary = {
        "admins": len(admins),
        "jury": len(jury_users),
        "formations": [],
    }
    for formation in FORMATIONS:
        formation_key = formation["key"]
        label = formation["label"]
        prefix = formation["candidate_prefix"]
        upsert_candidature_campaign(formation_key, label)
        candidates = [
            upsert_candidature(index, formation_key, prefix, admitted=index <= 3)
            for index in range(1, 5)
        ]
        test = upsert_test(formation_key, label)
        group = upsert_group(test, candidates[:3], formation_key, label)
        for index, candidate in enumerate(candidates, start=1):
            upsert_result(
                test,
                candidate,
                score=95 if index <= 3 else 45,
                admitted=index <= 3,
            )
        campaign = upsert_interview_campaign(formation_key, label)
        slot = upsert_slot(campaign, formation_key, label, jury_users)
        for candidate in candidates[:3]:
            upsert_evaluation(campaign, slot, candidate)
        summary["formations"].append(
            {
                "formation": formation_key,
                "candidatures": len(candidates),
                "test_id": str(test.id),
                "group_id": str(group.id),
                "interview_campaign_id": str(campaign.id),
                "slot_id": str(slot.id),
            }
        )
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="Supprime uniquement les données de démo préprod avant insertion.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.reset_demo:
            reset_demo_data()
        ensure_critical_indexes()
        summary = seed()

    print("Seed préprod terminé.")
    print(f"Mot de passe commun: {PASSWORD}")
    print("Comptes:")
    for role, email in ADMIN_EMAILS.items():
        print(f"- {role}: {email}")
    for member in JURY_MEMBERS:
        print(f"- jury {member['role']}: {member['email']}")
    print("Données:")
    for item in summary["formations"]:
        print(
            f"- {item['formation']}: test={item['test_id']} "
            f"groupe={item['group_id']} entretien={item['interview_campaign_id']}"
        )


if __name__ == "__main__":
    main()
