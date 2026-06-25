"""MongoEngine persistence adapter for interviews."""

from app.models.interview import (
    InterviewCampaign,
    InterviewEvaluation,
    InterviewSlot,
)


class InterviewRepository:
    def create_campaign(self, **values):
        return InterviewCampaign(**values)

    def get_campaign(self, campaign_id):
        return InterviewCampaign.objects(id=campaign_id).first()

    def campaign_has_evaluations(self, campaign_id):
        return bool(
            InterviewEvaluation.objects(
                campaign_id=campaign_id,
            ).only("id").first()
        )

    @staticmethod
    def save_campaign(campaign):
        campaign.save()
        return campaign

    def create_slot(self, **values):
        return InterviewSlot(**values)

    def get_slot(self, slot_id):
        return InterviewSlot.objects(id=slot_id).first()

    @staticmethod
    def save_slot(slot):
        slot.save()
        return slot
