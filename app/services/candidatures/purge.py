"""Remove every interview and Bootcamp trace of a deleted candidature.

Without this, a deleted candidate would stay counted in a validator's assignments, keep an evaluation,
a place in the pre-selection or a Bootcamp, and could still receive a queued e-mail.
"""

from app.models.bootcamp import BootcampParticipant
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation


def purge_candidate_traces(candidate_id):
    candidate_id = str(candidate_id)
    removed = {"evaluations": InterviewEvaluation.objects(candidature_id=candidate_id).delete()}
    removed["bootcamps"] = BootcampParticipant.objects(candidate_id=candidate_id).delete()
    # Sent e-mails stay as history; anything not yet delivered is cancelled.
    removed["emails"] = EmailJob.objects(candidate_id=candidate_id, status__in=["pending", "sending", "failed"]).update(
        set__status="cancelled", unset__payload=1,
    )
    workspaces = InterviewCampaign.objects(__raw__={"$or": [
        {"distribution.validators": {"$exists": True}}, {"preselection.selected": candidate_id},
    ]})
    for workspace in workspaces:
        distribution = workspace.distribution or {}
        changed = False
        for item in (distribution.get("validators") or {}).values():
            if candidate_id in item.get("candidates", []):
                item["candidates"].remove(candidate_id)
                (item.get("slots") or {}).pop(candidate_id, None)
                changed = True
        selection = workspace.preselection or {}
        if candidate_id in selection.get("selected", []):
            selection["selected"] = [value for value in selection["selected"] if value != candidate_id]
            tie = selection.get("tie")
            if tie:
                tie["candidates"] = [value for value in tie["candidates"] if value != candidate_id]
                tie["selected"] = [value for value in tie["selected"] if value != candidate_id]
            selection.pop("fingerprint", None)
        else:
            selection = None
        updates = {}
        if changed:
            distribution["revision"] = distribution.get("revision", 0) + 1
            updates["set__distribution"] = distribution
        if selection is not None:
            selection["revision"] = selection.get("revision", 0) + 1
            updates["set__preselection"] = selection
        if updates:
            InterviewCampaign.objects(id=workspace.id).update_one(**updates)
    return removed
