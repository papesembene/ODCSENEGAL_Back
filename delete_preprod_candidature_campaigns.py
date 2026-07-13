#!/usr/bin/env python3
"""Delete only preproduction public candidature campaigns."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.models.candidature_campaign import CandidatureCampaign


TARGET_TITLES = [
    "Appel à Candidature - Préprod Data",
    "Appel à Candidature - Préprod Dev Web Mobile",
]


def main():
    app = create_app()
    with app.app_context():
        deleted = CandidatureCampaign.objects(
            title__in=TARGET_TITLES,
        ).delete()
    print(f"Campagnes de candidature préprod supprimées: {deleted}")


if __name__ == "__main__":
    main()
