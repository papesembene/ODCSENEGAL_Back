"""Ranking of validated interviews and pre-selection of the N best candidates of a referential campaign.

Ties at the selection threshold are settled by a recorded random draw; the administrator may then swap
a drawn candidate for another candidate with the same score. Every draw, swap and validation is kept
in the pre-selection history, and a validated pre-selection feeds the Bootcamps.
"""

from datetime import datetime
from random import Random
import secrets

from mongoengine import Q

from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.services.interviews.exceptions import InterviewConflictError, InterviewValidationError
from app.services.interviews.referential_service import ReferentialInterviews


def _score(value):
    return round(float(value), 2)


def _actor(admin):
    if admin is None:
        return {"id": None, "name": "Système"}
    name = " ".join(filter(None, (getattr(admin, "first_name", None), getattr(admin, "last_name", None))))
    return {"id": str(admin.id), "name": name or getattr(admin, "email", "") or "Administrateur"}


def select_best(ranked, count, seed):
    """Pick `count` candidates from (candidate_id, score) rows sorted by score; draw among ties at the threshold."""
    if count >= len(ranked):
        return [candidate for candidate, _ in ranked], None
    threshold = ranked[count - 1][1]
    above = [candidate for candidate, score in ranked if score > threshold]
    tied = sorted(candidate for candidate, score in ranked if score == threshold)
    places = count - len(above)
    if places == len(tied):
        return above + tied, None
    drawn = sorted(Random(seed).sample(tied, places))
    return above + drawn, {"score": threshold, "candidates": tied, "selected": drawn, "places": places, "seed": seed}


class InterviewRankingService:
    def __init__(self, referentials=None):
        self.referentials = referentials or ReferentialInterviews()

    def _workspace(self, formation, campaign_id):
        workspace, training, _ = self.referentials._workspace(formation, campaign_id=campaign_id)
        if not workspace:
            raise InterviewValidationError("Aucun entretien organisé pour ce référentiel et cette campagne.")
        return workspace, training

    @staticmethod
    def _rows(workspace):
        """Validated interviews sorted by global score, plus counts of the interviews still pending."""
        workspace_id = str(workspace.id)
        assigned = {candidate: user_id for user_id, item in workspace.distribution.get("validators", {}).items()
                    for candidate in item["candidates"]}
        names = ReferentialInterviews._validators(include_inactive=True)
        rows, pending, absent = [], 0, 0
        for evaluation in InterviewEvaluation.objects(campaign_id=workspace_id).only(
            "id", "candidature_id", "candidate_snapshot", "questionnaire", "updated_at",
        ):
            status = evaluation.questionnaire.get("status")
            scores = evaluation.questionnaire.get("scores") or {}
            if status == "absent":
                absent += 1
                continue
            if status != "validated" or scores.get("global") is None:
                pending += 1
                continue
            snapshot = evaluation.candidate_snapshot or {}
            validator_id = assigned.get(evaluation.candidature_id)
            rows.append({
                "candidate_id": evaluation.candidature_id, "evaluation_id": str(evaluation.id),
                "first_name": snapshot.get("first_name"), "last_name": snapshot.get("last_name"),
                "email": snapshot.get("email"), "phone": snapshot.get("phone"),
                "validator": names.get(validator_id, {}).get("name") if validator_id else None,
                "scores": {key: scores.get(key) for key in ("technique", "motivation", "social", "global")},
                "comment": evaluation.questionnaire.get("comment") or "",
                "validated_at": evaluation.questionnaire.get("finalized_at"),
            })
        rows.sort(key=lambda row: (-_score(row["scores"]["global"]), (row["last_name"] or "").casefold(),
                                   (row["first_name"] or "").casefold(), row["candidate_id"]))
        rank = 0
        for index, row in enumerate(rows):
            if index == 0 or _score(row["scores"]["global"]) != _score(rows[index - 1]["scores"]["global"]):
                rank = index + 1
            row["rank"] = rank
        return rows, pending, absent

    @staticmethod
    def _fingerprint(rows):
        return sorted((row["candidate_id"], _score(row["scores"]["global"])) for row in rows)

    def get(self, formation, campaign_id=None):
        workspace, training = self._workspace(formation, campaign_id)
        rows, pending, absent = self._rows(workspace)
        selection = workspace.preselection or {}
        selected = set(selection.get("selected", []))
        tie = selection.get("tie") or {}
        tied = set(tie.get("candidates", []))
        for row in rows:
            candidate = row["candidate_id"]
            if not selection.get("selected"):
                row["preselection"] = None
            elif candidate in tied:
                row["preselection"] = "tie_selected" if candidate in selected else "tie_not_selected"
            else:
                row["preselection"] = "selected" if candidate in selected else "not_selected"
        stale = bool(selection.get("selected")) and selection.get("fingerprint") != [list(item) for item in self._fingerprint(rows)]
        return {
            "formation": training["code"], "title": training["title"], "workspace_id": str(workspace.id),
            "rows": rows, "evaluated": len(rows), "pending": pending, "absent": absent,
            "preselection": {key: value for key, value in selection.items() if key != "fingerprint"},
            "stale": stale and selection.get("status") != "validated",
        }

    @staticmethod
    def _save(workspace, revision, selection):
        if type(revision) is not int or revision != (workspace.preselection or {}).get("revision", 0):
            raise InterviewConflictError("La présélection a changé. Actualisez avant de recommencer.")
        selection["revision"] = revision + 1
        condition = Q(preselection__revision=revision)
        if revision == 0:
            condition |= Q(preselection__revision__exists=False)
        if not InterviewCampaign.objects(condition, id=workspace.id).update_one(
            set__preselection=selection, set__updated_at=datetime.utcnow(),
        ):
            raise InterviewConflictError("La présélection a changé. Actualisez avant de recommencer.")

    @staticmethod
    def _editable(selection):
        if selection.get("status") == "validated":
            raise InterviewConflictError("La présélection est validée : elle ne peut plus être modifiée.")

    def preselect(self, formation, data, admin):
        """Select the N best validated interviews; a random draw settles ties at the threshold."""
        if not isinstance(data, dict):
            raise InterviewValidationError("Présélection invalide.")
        workspace, _ = self._workspace(formation, data.get("campaign_id"))
        current = workspace.preselection or {}
        self._editable(current)
        count = data.get("count")
        if type(count) is not int or not 1 <= count <= 5000:
            raise InterviewValidationError("Indiquez le nombre de candidats à présélectionner (entre 1 et 5 000).")
        rows, pending, _ = self._rows(workspace)
        if not rows:
            raise InterviewValidationError("Aucun entretien validé : le classement est vide.")
        ranked = [(row["candidate_id"], _score(row["scores"]["global"])) for row in rows]
        selected, tie = select_best(ranked, count, secrets.token_hex(8))
        now = datetime.utcnow().isoformat() + "Z"
        event = {"at": now, "by": _actor(admin), "action": "draw" if tie else "select",
                 "count": count, "selected": len(selected), "pending_interviews": pending}
        if tie:
            event.update(score=tie["score"], tied=tie["candidates"], drawn=tie["selected"], seed=tie["seed"])
        selection = {
            "status": "draft", "count": count, "selected": selected, "tie": tie, "computed_at": now,
            "fingerprint": [list(item) for item in self._fingerprint(rows)],
            "history": [*current.get("history", []), event],
        }
        self._save(workspace, data.get("revision"), selection)
        return self.get(formation, data.get("campaign_id"))

    def replace(self, formation, data, admin):
        """Swap a drawn tied candidate for a tied candidate who was not drawn."""
        if not isinstance(data, dict):
            raise InterviewValidationError("Remplacement invalide.")
        workspace, _ = self._workspace(formation, data.get("campaign_id"))
        selection = dict(workspace.preselection or {})
        self._editable(selection)
        tie = dict(selection.get("tie") or {})
        removed, added = data.get("remove"), data.get("add")
        if not tie or removed not in tie["selected"] or added not in tie["candidates"] or added in tie["selected"]:
            raise InterviewValidationError("Le remplacement doit se faire entre deux candidats ex æquo au seuil, l’un tiré, l’autre non.")
        tie["selected"] = sorted([*(candidate for candidate in tie["selected"] if candidate != removed), added])
        selection["tie"] = tie
        selection["selected"] = [added if candidate == removed else candidate for candidate in selection["selected"]]
        selection["history"] = [*selection.get("history", []), {
            "at": datetime.utcnow().isoformat() + "Z", "by": _actor(admin), "action": "replace",
            "removed": removed, "added": added, "score": tie["score"],
        }]
        self._save(workspace, data.get("revision"), selection)
        return self.get(formation, data.get("campaign_id"))

    def validate(self, formation, data, admin):
        """Freeze the pre-selection; the selected candidates become available for the Bootcamps."""
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            raise InterviewValidationError("Confirmez la validation de la présélection.")
        workspace, _ = self._workspace(formation, data.get("campaign_id"))
        selection = dict(workspace.preselection or {})
        self._editable(selection)
        if not selection.get("selected"):
            raise InterviewValidationError("Calculez d’abord la présélection.")
        rows, _, _ = self._rows(workspace)
        if selection.get("fingerprint") != [list(item) for item in self._fingerprint(rows)]:
            raise InterviewConflictError("Des entretiens ont été validés ou modifiés depuis le calcul : recalculez la présélection.")
        now = datetime.utcnow().isoformat() + "Z"
        actor = _actor(admin)
        selection.update(status="validated", validated_at=now, validated_by=actor)
        selection["history"] = [*selection.get("history", []), {
            "at": now, "by": actor, "action": "validate", "selected": len(selection["selected"]),
        }]
        self._save(workspace, data.get("revision"), selection)
        return self.get(formation, data.get("campaign_id"))

    @staticmethod
    def is_validated(campaign_id):
        workspace = InterviewCampaign.objects(id=campaign_id).only("preselection").first()
        return bool(workspace and (workspace.preselection or {}).get("status") == "validated")
