"""Slot-scoped jury access, with server-side UTC interview windows."""

from datetime import datetime, timezone


ROLE_FIELDS = {
    "filter": ("assigned_filter_ids", "assigned_jury_ids"),
    "validator": ("assigned_validator_ids",),
    "motivation": ("assigned_motivation_ids",),
}


def is_interview_member(admin):
    return bool(
        admin
        and admin.admin_type != "super_admin"
        and (admin.profile_data or {}).get("admin_scope") == "interview_member"
    )


def utc_naive(value):
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def utc_iso(value):
    return utc_naive(value).isoformat() + "Z" if value else None


def slot_roles(slot, admin):
    if not slot or not admin:
        return []
    admin_id = str(admin.id)
    assignments = (getattr(slot, "assignments", None) or {}).get(admin_id) or []
    return [
        role for role, fields in ROLE_FIELDS.items()
        if role in assignments or any(
            admin_id in (getattr(slot, field, None) or []) for field in fields
        )
    ]


def filter_window_open(slot, now):
    start = getattr(slot, "start_at", None)
    end = getattr(slot, "end_at", None)
    return bool(
        start and end
        and getattr(slot, "status", None) in {"scheduled", "in_progress"}
        and utc_naive(start) <= utc_naive(now) < utc_naive(end)
    )


def editable_roles(slot, admin, now):
    return [
        role for role in slot_roles(slot, admin)
        if role != "filter" or filter_window_open(slot, now)
    ]


def slot_access(slot, admin, now):
    return {
        "roles": slot_roles(slot, admin),
        "editable_roles": editable_roles(slot, admin, now),
        "filter_opens_at": utc_iso(slot.start_at),
        "filter_closes_at": utc_iso(slot.end_at),
    }


def visible_slots_condition(admin, now=None):
    """Keep unrestricted assigned roles; restrict only the filter assignment."""
    admin_id = str(admin.id)
    now = utc_naive(now or datetime.utcnow())
    assigned = {
        role: {"$or": [
            *({field: admin_id} for field in fields),
            {f"assignments.{admin_id}": role},
        ]}
        for role, fields in ROLE_FIELDS.items()
    }
    return {"$or": [
        assigned["validator"],
        assigned["motivation"],
        {"$and": [
            assigned["filter"],
            {"status": {"$in": ["scheduled", "in_progress"]}},
            {"start_at": {"$lte": now}},
            {"end_at": {"$gt": now}},
        ]},
    ]}
