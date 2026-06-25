#!/usr/bin/env python3
"""Migrate interview campaigns to campaign-owned scorecards."""

import os
from copy import deepcopy

from dotenv import load_dotenv
from pymongo import MongoClient

from app.services.interviews.scorecard_service import (
    DWM_SCORECARD_CONFIG,
    get_default_scorecard_config,
    is_evaluation_complete,
)


def main():
    load_dotenv()
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/odcdb")
    client = MongoClient(mongo_uri)
    database = client.get_default_database(default="odcdb")

    campaigns_updated = 0
    evaluations_updated = 0
    for campaign in database.interview_campaigns.find():
        scorecard_config = campaign.get("scorecard_config")
        if not scorecard_config:
            scorecard_config = (
                deepcopy(DWM_SCORECARD_CONFIG)
                if campaign.get("formation") == "dev-web-mobile"
                else get_default_scorecard_config(campaign.get("formation"))
            )

        database.interview_campaigns.update_one(
            {"_id": campaign["_id"]},
            {
                "$set": {"scorecard_config": scorecard_config},
                "$unset": {"role_configs": ""},
            },
        )
        campaigns_updated += 1

        for evaluation in database.interview_evaluations.find({"campaign_id": str(campaign["_id"])}):
            database.interview_evaluations.update_one(
                {"_id": evaluation["_id"]},
                {
                    "$set": {
                        "is_complete": is_evaluation_complete(
                            evaluation,
                            scorecard_config,
                        ),
                    },
                },
            )
            evaluations_updated += 1

    print(f"Campagnes migrées: {campaigns_updated}")
    print(f"Fiches recalculées: {evaluations_updated}")


if __name__ == "__main__":
    main()
