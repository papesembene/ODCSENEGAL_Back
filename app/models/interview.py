from datetime import datetime

from mongoengine import (
    BooleanField,
    DateTimeField,
    DictField,
    Document,
    IntField,
    ListField,
    StringField,
)


class InterviewCampaign(Document):
    name = StringField(required=True)
    formation = StringField(required=True)
    description = StringField()
    status = StringField(
        default="draft",
        choices=["draft", "active", "closed"],
    )
    scorecard_config = DictField(default=dict)
    created_by = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "interview_campaigns",
        "indexes": ["formation", "status", "created_at"],
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "formation": self.formation,
            "description": self.description,
            "status": self.status,
            "scorecard_config": self.scorecard_config or {},
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InterviewSlot(Document):
    campaign_id = StringField(required=True)
    label = StringField(required=True)
    formation = StringField(required=True)
    start_at = DateTimeField(required=True)
    end_at = DateTimeField(required=True)
    capacity = IntField(default=10)
    assigned_filter_ids = ListField(StringField(), default=list)
    assigned_jury_ids = ListField(StringField(), default=list)
    assigned_validator_ids = ListField(StringField(), default=list)
    assigned_motivation_ids = ListField(StringField(), default=list)
    status = StringField(
        default="scheduled",
        choices=["scheduled", "in_progress", "completed", "cancelled"],
    )
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "interview_slots",
        "indexes": ["campaign_id", "formation", "start_at", "status"],
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "campaign_id": self.campaign_id,
            "label": self.label,
            "formation": self.formation,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "capacity": self.capacity,
            "assigned_filter_ids": self.assigned_filter_ids or self.assigned_jury_ids or [],
            "assigned_jury_ids": self.assigned_jury_ids or self.assigned_filter_ids or [],
            "assigned_validator_ids": self.assigned_validator_ids or [],
            "assigned_motivation_ids": self.assigned_motivation_ids or [],
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InterviewEvaluation(Document):
    campaign_id = StringField(required=True)
    slot_id = StringField()
    candidature_id = StringField(required=True)
    candidate_snapshot = DictField(default=dict)
    filter_review = DictField(default=dict)
    validator_review = DictField(default=dict)
    motivation_review = DictField(default=dict)
    interview_progress_status = StringField(
        default="a_planifier",
        choices=[
            "a_planifier",
            "planifie",
            "passe",
            "absent",
        ],
    )
    final_status = StringField(
        default="en_attente",
        choices=[
            "en_attente",
            "retenu",
            "liste_attente",
            "rejete",
        ],
    )
    waiting_list_rank = IntField()
    is_complete = BooleanField(default=False)
    is_locked = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "interview_evaluations",
        "indexes": [
            {"fields": ["campaign_id", "candidature_id"], "unique": True},
            "campaign_id",
            "slot_id",
            "final_status",
            "interview_progress_status",
            "is_complete",
            "candidate_snapshot.email",
            "candidate_snapshot.desired_training",
            {
                "fields": [
                    "campaign_id",
                    "final_status",
                    "-updated_at",
                ],
            },
            {
                "fields": [
                    "campaign_id",
                    "interview_progress_status",
                    "-updated_at",
                ],
            },
        ],
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "campaign_id": self.campaign_id,
            "slot_id": self.slot_id,
            "candidature_id": self.candidature_id,
            "candidate_snapshot": self.candidate_snapshot or {},
            "filter_review": self.filter_review or {},
            "validator_review": self.validator_review or {},
            "motivation_review": self.motivation_review or {},
            "interview_progress_status": self.interview_progress_status,
            "final_status": self.final_status,
            "waiting_list_rank": self.waiting_list_rank,
            "is_complete": self.is_complete,
            "is_locked": self.is_locked,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
