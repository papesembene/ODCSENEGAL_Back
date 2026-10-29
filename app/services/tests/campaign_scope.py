"""Campaign-year scoping shared by test and result queries."""

from datetime import datetime

from flask import current_app

from app.models.test import Test


def current_campaign_year():
    configured = current_app.config.get("ODC_CAMPAIGN_YEAR")
    return int(configured) if configured else datetime.utcnow().year


def normalize_campaign_year(value=None):
    """Return an integer year, or None when the caller explicitly asks for all."""
    if value in (None, "", "current"):
        return current_campaign_year()
    if str(value).lower() == "all":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Année de campagne invalide") from error
    if year < 2000 or year > 2100:
        raise ValueError("Année de campagne invalide")
    return year


def tests_for_campaign(year=None):
    """Include legacy tests without campaignYear using their creation date."""
    year = normalize_campaign_year(year)
    if year is None:
        return Test.objects
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    raw_query = {
        "$or": [
            {"campaignYear": year},
            {
                "$and": [
                    {"campaignYear": {"$exists": False}},
                    {"createdAt": {"$gte": start, "$lt": end}},
                ]
            },
        ]
    }
    return Test.objects(__raw__=raw_query)


def test_ids_for_campaign(year=None):
    """Return string IDs used by TestResult.testId for the selected campaign."""
    query = tests_for_campaign(year)._query
    collection = Test._get_collection()
    return [str(row["_id"]) for row in collection.find(query, {"_id": 1})]
