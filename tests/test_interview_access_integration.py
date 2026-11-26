from collections import Counter
"""Optional real-Mongo checks: TEST_LOCAL_MONGO=1, isolated disposable database."""

import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from bson import ObjectId
from flask import Flask
from mongoengine import connect, disconnect

from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation, InterviewSlot
from app.models.user import User
from app.routes.interview_routes import interview_bp
from app.routes.admin_routes import admin_bp
from app.services.interviews.evaluation_service import InterviewEvaluationService
from app.services.interviews.questionnaire import generate_questions
from app.services.interviews.query_service import InterviewQueryService
from app.services.interviews.referential_service import InterviewInvitationOutbox, ValidatorScheduleOutbox


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class InterviewAccessIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_interview_access_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        host = os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017")
        cls.connection = connect(cls.db_name, host=host, serverSelectionTimeoutMS=3000)
        cls.connection.admin.command("ping")
        cls.addClassCleanup(cls.connection.drop_database, cls.db_name)

    def setUp(self):
        InterviewEvaluation.drop_collection()
        InterviewSlot.drop_collection()
        InterviewCampaign.drop_collection()
        self.now = datetime(2026, 10, 19, 12)
        self.admin = SimpleNamespace(
            id=ObjectId(), admin_type="competences", is_admin=True, is_active=True,
            email="jury@example.com",
            profile_data={"admin_scope": "interview_member", "interview_role": "filter"},
            first_name="Awa", last_name="Diop",
        )
        self.query = InterviewQueryService(now=lambda: self.now)
        self.evaluations = InterviewEvaluationService(query_service=self.query, now=lambda: self.now)
        self.campaign = InterviewCampaign(name="Access test", formation="data").save()
        self.slots = {}
        self.records = {}
        for name, start, end in (
            ("past", -2, -1), ("current", -1, 1), ("future", 1, 2),
        ):
            slot = InterviewSlot(
                campaign_id=str(self.campaign.id), label=name, formation="data",
                start_at=self.now + timedelta(hours=start), end_at=self.now + timedelta(hours=end),
                assigned_filter_ids=[str(self.admin.id)],
            ).save()
            self.slots[name] = slot
            self.records[name] = InterviewEvaluation(
                campaign_id=str(self.campaign.id), slot_id=str(slot.id),
                candidature_id=str(ObjectId()), candidate_snapshot={"email": name + "@example.com"},
            ).save()
        app = Flask(__name__)
        app.register_blueprint(interview_bp, url_prefix="/api/admin")
        app.register_blueprint(admin_bp, url_prefix="/api/admin")
        self.client = app.test_client()
        self.auth = patch("app.utils.auth_decorators.AuthService.verify_token", return_value=self.admin)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        for name, service in (("query_service", self.query), ("evaluation_service", self.evaluations)):
            patched = patch("app.routes.interview_routes." + name, service)
            patched.start()
            self.addCleanup(patched.stop)
        self.headers = {"Authorization": "Bearer access-test"}

    def get(self, path):
        return self.client.get("/api/admin/interviews/" + path, headers=self.headers)

    def test_validator_can_change_password_and_rotate_sessions(self):
        self.auth.stop()
        self.client.application.config["JWT_SECRET_KEY"] = "interview-access-integration-secret"
        validator = User(
            email="password-validator@example.com", profile_type="student",
            is_admin=True, admin_type="competences",
            profile_data={"admin_scope": "interview_member", "interview_role": "validator"},
        )
        initial = "initial-test-password"
        replacement = "replacement-test-password"
        validator.set_password(initial)

        login_path = "/api/admin/login"
        login = self.client.post(login_path, json={"email": validator.email, "password": initial})
        self.assertEqual(200, login.status_code)
        headers = {"Authorization": "Bearer " + login.json["token"]}
        path = "/api/admin/me/password"
        change = {"current_password": initial, "new_password": replacement}

        self.assertEqual(401, self.client.patch(path, json=change).status_code)
        self.assertEqual(400, self.client.patch(path, headers=headers, json={
            **change, "current_password": "incorrect-password",
        }).status_code)
        self.assertEqual(400, self.client.patch(path, headers=headers, json={
            **change, "new_password": "short",
        }).status_code)
        response = self.client.patch(path, headers=headers, json=change)
        self.assertEqual(200, response.status_code)
        self.assertEqual(401, self.client.patch(path, headers=headers, json=change).status_code)
        self.assertEqual(401, self.client.post(login_path, json={
            "email": validator.email, "password": initial,
        }).status_code)
        self.assertEqual(200, self.client.post(login_path, json={
            "email": validator.email, "password": replacement,
        }).status_code)
        new_headers = {"Authorization": "Bearer " + response.json["token"]}
        self.assertEqual(200, self.client.get(
            "/api/admin/interviews/capabilities", headers=new_headers,
        ).status_code)

    def test_direct_campaign_only_uses_linked_or_unambiguous_historical_candidatures(self):
        start = self.now - timedelta(days=2)
        source = CandidatureCampaign(
            title="Source", formation="data", status="published", start_at=start, end_at=self.now,
        ).save()
        overlap = CandidatureCampaign(
            title="Overlap", formation="all", status="archived",
            start_at=self.now - timedelta(days=1), end_at=self.now,
        ).save()
        self.campaign.candidature_campaign_id = str(source.id)
        self.campaign.status = "active"
        self.campaign.save()

        for name, formation, campaign_id, created_at in (
            ("linked", "data", str(source.id), self.now),
            ("other", "data", str(overlap.id), start),
            ("historical", "data", None, start),
            ("ambiguous", "data", None, self.now),
            ("outside", "data", None, start - timedelta(days=1)),
            ("wrong-training", "hackeuses", str(source.id), start),
        ):
            Candidature(
                first_name=name, last_name="Diop", email=f"{name}@example.com", phone="+221771234567",
                date_of_birth=datetime(2000, 10, 19).date(), place_of_birth="Dakar", gender="male",
                cni_or_passport_number=name, nationality="Sénégal", region_of_residence="Dakar",
                computer_skills=True, available_for_10_months=True, desired_training=formation,
                accept_conditions=True, candidature_campaign_id=campaign_id, created_at=created_at,
            ).save()

        candidates = self.evaluations._planning_candidates(self.campaign)
        self.assertEqual(["historical", "linked"], [candidate.first_name for candidate in candidates])
        source.update(set__formation="dev-data", set__status="published")
        overlap.update(set__status="draft")
        Candidature.objects(first_name__in=["historical", "ambiguous", "outside"]).update(
            set__candidature_campaign_id=str(source.id),
        )
        Candidature.objects(first_name="other").update(set__candidature_campaign_id=str(source.id))

        self.assertEqual(403, self.get("overview").status_code)
        administrator = SimpleNamespace(id=ObjectId(), admin_type="super_admin", is_admin=True, is_active=True, profile_data={})
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=administrator):
            overview = self.get("overview")
            scoped = self.get("bootstrap?formation=dev-data")
            chosen = self.get(f"overview?campaign_id={source.id}")
            unknown = self.get(f"overview?campaign_id={ObjectId()}")

        self.assertEqual(200, chosen.status_code, chosen.json)
        self.assertEqual(["dev-data"], [row["formation"] for row in chosen.json["data"]])
        self.assertEqual(str(source.id), chosen.json["data"][0]["candidature_campaign"]["id"])
        self.assertIn(str(source.id), {item["id"] for item in overview.json["campaigns"]})
        self.assertEqual(400, unknown.status_code)

        self.assertEqual(200, overview.status_code, overview.json)
        data = next(row for row in overview.json["data"] if row["formation"] == "dev-data")
        self.assertEqual((5, 0, 0, 5, 0), tuple(data[key] for key in ("eligible", "assigned", "completed", "remaining", "validators")))
        self.assertEqual(200, scoped.status_code, scoped.json)
        self.assertEqual({"past", "current", "future"}, {slot["label"] for slot in scoped.json["data"]["slots"]})

        path = "/api/admin/interviews/referentials/dev-data"
        transport = Mock(is_configured=True)
        transport.send_html.return_value = {"sent": True}
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=administrator):
            members_path = "/api/admin/interview-members"
            ids = []
            with patch("app.routes.admin_routes._send_member_credentials", return_value={"sent": False}):
                for index, role, formation_code in (
                    (1, "validator", "dev-data"), (2, "validator", "dev-data"),
                    (3, "validator", "dev-web-mobile"), (4, "coach", "dev-data"),
                ):
                    created = self.client.post(members_path, headers=self.headers, json={
                        "email": f"referential-validator-{index}@example.com", "first_name": "Membre",
                        "last_name": str(index), "role": role, "formations": [formation_code],
                    })
                    self.assertEqual(201, created.status_code)
                    ids.append(created.json["data"]["id"])
            validators = ids[:2]
            state = self.client.get(path, headers=self.headers).json["data"]
            self.assertEqual((0, 5), (state["assigned"], state["eligible"]))
            self.assertEqual(set(validators), {row["id"] for row in state["available_validators"]})

            def action(name, **values):
                return self.client.post(path, headers=self.headers, json={"action": name, **values})

            links = [f"https://teams.microsoft.com/l/meetup-join/example-{index}" for index in (1, 2, 3)]
            self.assertEqual(400, action("settings", revision=0, validators=validators).status_code)
            self.assertEqual(400, action("links", revision=0, links=[links[0], links[0]]).status_code)
            self.assertEqual(200, action("links", revision=0, links=links).status_code)
            self.assertEqual(400, action("settings", revision=1, validators=ids).status_code)
            self.assertEqual(200, action("settings", revision=1, validators=validators).status_code)
            schedule = {
                "start_date": "2035-12-03", "day_start": "09:00", "day_end": "10:00", "duration": 20,
                "breaks": [{"start": "09:20", "end": "09:40"}], "skip_weekends": True,
            }
            self.assertEqual(400, action("dispatch", revision=2, per_validator=2, schedule=schedule, preview=True).status_code)
            self.assertEqual(200, action("assign_links", revision=2).status_code)
            self.assertEqual(400, action("dispatch", revision=3, per_validator=2, schedule=schedule).status_code)
            preview = action("dispatch", revision=3, per_validator=2, schedule=schedule, preview=True)
            self.assertEqual(200, preview.status_code, preview.json)
            planned = preview.json["data"]
            self.assertEqual((True, 4, 1), (planned["preview"], planned["new_assignments"], planned["unassigned"]))
            self.assertEqual([["2035-12-03T09:00", "2035-12-03T09:40"]] * 2,
                             [[row["at"] for row in item["candidates"]] for item in planned["validators"]])
            self.assertEqual(0, self.client.get(path, headers=self.headers).json["data"]["assigned"])
            dispatch = action("dispatch", revision=3, per_validator=2, schedule=schedule, seed=planned["seed"])
            self.assertEqual(200, dispatch.status_code, dispatch.json)
            self.assertEqual((False, 4, 1), (dispatch.json["data"]["preview"], dispatch.json["data"]["new_assignments"], dispatch.json["data"]["unassigned"]))
            self.assertEqual(
                [(item["first"], item["last"]) for item in planned["validators"]],
                [(item["first"], item["last"]) for item in dispatch.json["data"]["validators"]],
            )
            self.assertEqual(409, action("dispatch", revision=3, per_validator=2, schedule=schedule, seed=planned["seed"]).status_code)
            before = self.get("referentials/dev-data").json["data"]
            current = {row["id"]: row["teams_url"] for row in before["validators"]}
            spare = next(link for link in links if link not in current.values())
            self.assertEqual(400, action("set_link", revision=4, validator_id=validators[0], teams_url=current[validators[1]]).status_code)
            self.assertEqual(400, action("set_link", revision=4, validator_id=validators[0], teams_url="https://example.com/meet").status_code)
            changed = action("set_link", revision=4, validator_id=validators[0], teams_url=spare)
            self.assertEqual(200, changed.status_code, changed.json)
            self.assertEqual(spare, InterviewSlot.objects(assigned_validator_ids=validators[0]).get().teams_url)
            self.assertEqual(
                {(datetime(2035, 12, 3, 9), 20): 2, (datetime(2035, 12, 3, 9, 40), 20): 2},
                Counter((row.scheduled_at, row.scheduled_minutes) for row in InterviewEvaluation.objects(scheduled_at__ne=None)),
            )
            state = self.client.get(path, headers=self.headers).json["data"]
            self.assertEqual(schedule, state["schedule"])
            self.assertEqual({"assigned"}, {row["status"] for row in state["candidates"] if row["validator"]})
            self.assertEqual({"unassigned"}, {row["status"] for row in state["candidates"] if not row["validator"]})
            self.assertEqual(0, state["available_links"])
            self.assertEqual(4, state["remaining_to_notify"])
            self.assertEqual([2, 2], [row["assigned"] for row in state["validators"]])
            used_links = {row["teams_url"] for row in state["validators"]}
            self.assertEqual(2, len(used_links))
            self.assertTrue(used_links < set(links))
            self.assertEqual(4, sum(bool(row["evaluation_id"]) for row in state["candidates"]))
            self.assertTrue(all(row["candidate_snapshot"]["computer_skills"] for row in state["candidates"]))

            groups = self.get("referentials/dev-data?groups_only=true").json["data"]
            self.assertEqual([], groups["candidates"])
            self.assertEqual({validators[0]: 2, validators[1]: 2, "unassigned": 1}, {
                row["id"]: row["count"] for row in groups["candidate_groups"]
            })
            first_group = self.get(f"referentials/dev-data?group={validators[0]}&page=99").json["data"]
            self.assertEqual((2, 1, 25), (first_group["total"], first_group["page"], first_group["page_size"]))
            self.assertEqual({"Membre 1"}, {row["validator"] for row in first_group["candidates"]})
            unassigned = self.get("referentials/dev-data?group=unassigned").json["data"]["candidates"]
            self.assertEqual([None], [row["validator"] for row in unassigned])
            search = first_group["candidates"][0]["candidate_snapshot"]["email"]
            filtered = self.client.get(path, query_string={"groups_only": "true", "search": search}, headers=self.headers).json["data"]
            self.assertEqual([{"id": validators[0], "name": "Membre 1", "count": 1}], filtered["candidate_groups"])

            with patch("app.services.email_outbox.EmailTransport", return_value=transport):
                self.assertEqual(400, action("notify", revision=5, confirmed=False).status_code)
                for _ in range(2):
                    queued = action("notify", revision=5, confirmed=True)
                    self.assertEqual(200, queued.status_code, queued.json)
                    self.assertEqual(4, queued.json["data"]["queued"])
                self.assertEqual(4, EmailJob.objects(batch_key=state["workspace_id"]).count())
                self.assertTrue(InterviewInvitationOutbox().run_once())
                sent = EmailJob.objects(batch_key=state["workspace_id"], status="sent").get()
                person = next(row for row in state["candidates"] if row["id"] == sent.candidate_id)
                validator = next(row for row in state["validators"] if row["name"] == person["validator"])
                recipients, _, message = transport.send_html.call_args.args
                self.assertEqual([person["candidate_snapshot"]["email"]], recipients)
                self.assertIn(validator["teams_url"], message)
                self.assertIn(datetime.fromisoformat(person["scheduled_at"]).strftime("%d/%m/%Y à %Hh%M"), message)
                self.assertIn("Durée prévue : 20 minutes", message)
                convened = self.get(f"referentials/dev-data?group={validators[validators.index(next(row['id'] for row in state['validators'] if row['name'] == person['validator']))]}").json["data"]["candidates"]
                self.assertEqual("convened", next(row["status"] for row in convened if row["id"] == sent.candidate_id))
                self.assertNotIn(next(link for link in links if link != validator["teams_url"]), message)

            locked = action("set_link", revision=5, validator_id=validators[0], teams_url=current[validators[0]])
            self.assertEqual(409, locked.status_code, locked.json)
            self.assertEqual(400, action("notify_validators", revision=5).status_code)
            with patch("app.services.email_outbox.EmailTransport", return_value=transport):
                planning = action("notify_validators", confirmed=True).json["data"]
                self.assertEqual((2, 0), (planning["queued_now"], planning["unchanged"]))
                again = action("notify_validators", confirmed=True).json["data"]
                self.assertEqual((0, 2), (again["queued_now"], again["unchanged"]))
            job = EmailJob.objects(kind="interview_validator_schedule", candidate_id=validators[0]).get()
            recipients, subject, html = ValidatorScheduleOutbox.prepare(job, datetime.utcnow())
            self.assertEqual(["referential-validator-1@example.com"], recipients)
            self.assertIn("planning", subject)
            self.assertIn(spare, html)
            self.assertIn("03/12/2035 09h00", html)
            self.assertIn("03/12/2035 09h40", html)
            pending = self.get("referentials/dev-data?group=unassigned").json["data"]["candidates"][0]["id"]
            revision = self.get("referentials/dev-data").json["data"]["revision"]
            moved = action("reassign", revision=revision, candidate_id=sent.candidate_id, validator_id=validators[1])
            self.assertEqual(409, moved.status_code, moved.json)
            overlap = action("reassign", revision=revision, candidate_id=pending, validator_id=validators[0], at="2035-12-03T09:10")
            self.assertEqual(409, overlap.status_code, overlap.json)
            manual = action("reassign", revision=revision, candidate_id=pending, validator_id=validators[0], at="2035-12-03T10:30")
            self.assertEqual(200, manual.status_code, manual.json)
            evaluation = InterviewEvaluation.objects(candidature_id=pending, scheduled_at__ne=None).get()
            self.assertEqual((datetime(2035, 12, 3, 10, 30), 20), (evaluation.scheduled_at, evaluation.scheduled_minutes))
            automatic = action("reassign", revision=revision + 1, candidate_id=pending, validator_id=validators[1])
            self.assertEqual(200, automatic.status_code, automatic.json)
            self.assertEqual("2035-12-04T09:00", automatic.json["data"]["at"])
            self.assertEqual(evaluation.reload().slot_id, InterviewSlot.objects(assigned_validator_ids=validators[1]).get().id.__str__())
            self.assertEqual(200, action("reassign", revision=revision + 2, candidate_id=pending, validator_id=None).status_code)
            self.assertEqual(0, InterviewEvaluation.objects(candidature_id=pending).count())
            self.assertEqual([None], [row["validator"] for row in self.get("referentials/dev-data?group=unassigned").json["data"]["candidates"]])

            now = datetime.utcnow()
            newer = CandidatureCampaign(
                title="Nouvelle promotion", formation="all", status="published",
                start_at=now + timedelta(days=1), end_at=now + timedelta(days=20),
            ).save()
            self.assertEqual(str(source.id), self.get("referentials/dev-data").json["data"]["candidature_campaign"]["id"])
            newer.update(set__start_at=now - timedelta(days=1))
            fresh = self.get("referentials/dev-data").json["data"]
            self.assertEqual(str(newer.id), fresh["candidature_campaign"]["id"])
            self.assertEqual((0, 0, ""), (fresh["eligible"], fresh["assigned"], fresh["workspace_id"]))
            self.assertEqual(200, action("links", revision=0, campaign_id=str(newer.id), links=[links[0]]).status_code)
            fresh = self.get("referentials/dev-data").json["data"]
            previous = self.get(f"referentials/dev-data?campaign_id={source.id}").json["data"]
            self.assertNotEqual(previous["workspace_id"], fresh["workspace_id"])
            self.assertEqual((5, 4), (previous["eligible"], previous["assigned"]))
            newer.update(set__start_at=now - timedelta(days=2), set__end_at=now - timedelta(days=1))
            self.assertEqual(str(newer.id), self.get("referentials/dev-data").json["data"]["candidature_campaign"]["id"])

            rows = [
                {"first_name": "Nouveau", "last_name": "Validateur", "email": "Nouveau.Validateur@example.com"},
                {"first_name": "Membre", "last_name": "3", "email": "referential-validator-3@example.com"},
                {"first_name": "Membre", "last_name": "1", "email": "referential-validator-1@example.com"},
                {"first_name": "Membre", "last_name": "4", "email": "referential-validator-4@example.com"},
                {"first_name": "Doublon", "last_name": "X", "email": "nouveau.validateur@example.com"},
                {"first_name": "Sans", "last_name": "Mail", "email": "pas-un-email"},
            ]
            import_path = "/api/admin/interview-members/import"
            preview = self.client.post(import_path, headers=self.headers, json={"formation": "dev-data", "rows": rows})
            self.assertEqual(200, preview.status_code, preview.json)
            self.assertEqual(["create", "attach", "unchanged", "attach", "error", "error"], [row["action"] for row in preview.json["data"]["rows"]])
            self.assertFalse(User.objects(email="nouveau.validateur@example.com").first())
            with patch("app.routes.admin_routes._send_member_credentials", return_value={"sent": False}):
                imported = self.client.post(import_path, headers=self.headers, json={"formation": "dev-data", "rows": rows, "preview": False})
            self.assertEqual(200, imported.status_code, imported.json)
            created = User.objects(email="nouveau.validateur@example.com").get()
            self.assertEqual(("validator", ["dev-data"]), (created.profile_data["interview_role"], created.profile_data["interview_formations"]))
            self.assertIn("e-mail d’identifiants", imported.json["data"]["rows"][0]["message"])
            self.assertEqual(["dev-web-mobile", "dev-data"], User.objects(id=ids[2]).get().profile_data["interview_formations"])
            coach = User.objects(id=ids[3]).get().profile_data
            self.assertEqual(("coach", ["coach", "validator"]), (coach["interview_role"], coach["interview_roles"]))
            self.assertIn(ids[3], {row["id"] for row in self.get("referentials/dev-data").json["data"]["available_validators"]})
            members = self.client.get("/api/admin/interview-members?role=validator", headers=self.headers).json["data"]
            self.assertEqual(["coach", "validator"], next(row["roles"] for row in members if row["id"] == ids[3]))
            self.assertEqual(400, self.client.post(import_path, headers=self.headers, json={"formation": "inconnu", "rows": rows}).status_code)
            mixed = [
                {"first_name": "Nouveau", "last_name": "Coach", "email": "nouveau.coach@example.com", "role": "Coach"},
                {"first_name": "Double", "last_name": "Rôle", "email": "double@example.com", "role": "validateur et coach"},
                {"first_name": "Sans", "last_name": "Rôle", "email": "defaut@example.com"},
                {"first_name": "Rôle", "last_name": "Faux", "email": "faux@example.com", "role": "directeur"},
            ]
            with patch("app.routes.admin_routes._send_member_credentials", return_value={"sent": True}):
                imported = self.client.post(import_path, headers=self.headers, json={
                    "formation": "dev-data", "rows": mixed, "preview": False, "default_role": "coach",
                }).json["data"]["rows"]
            self.assertEqual(["create", "create", "create", "error"], [row["action"] for row in imported])
            profiles = {email: User.objects(email=email).get().profile_data for email in ("nouveau.coach@example.com", "double@example.com", "defaut@example.com")}
            self.assertEqual(["coach"], profiles["nouveau.coach@example.com"]["interview_roles"])
            self.assertEqual(["validator", "coach"], profiles["double@example.com"]["interview_roles"])
            self.assertEqual("coach", profiles["defaut@example.com"]["interview_role"])

        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=User.objects(id=validators[0]).get()):
            scoped_data = self.get("bootstrap").json["data"]
            evaluations = self.get(f"evaluations?campaignId={state['workspace_id']}").json["data"]
            listing = self.get(f"evaluations?campaignId={state['workspace_id']}&directSummary=1&sort=schedule&pageSize=1").json
            planned_only = self.get(f"evaluations?campaignId={state['workspace_id']}&directStatus=planned").json
        direct = listing["summary"]["direct"]
        self.assertEqual(2, direct["planned"] + direct["convened"])
        self.assertEqual((0, 0, 0), (direct["draft"], direct["validated"], direct["absent"]))
        self.assertEqual((1, 2), (len(listing["data"]), listing["pagination"]["total"]))
        self.assertEqual("2035-12-03T09:00:00", listing["data"][0]["scheduled_at"])
        self.assertEqual(direct["planned"], planned_only["pagination"]["total"])
        self.assertEqual(direct["convened"] == 1 and listing["data"][0]["candidature_id"] == sent.candidate_id,
                         listing["data"][0]["invitation_sent"])
        self.assertEqual(1, len(scoped_data["slots"]))
        visible_slot = scoped_data["slots"][0]
        self.assertTrue(visible_slot["teams_url"] in links)
        self.assertEqual(2, len(evaluations))
        self.assertEqual({visible_slot["id"]}, {row["slot_id"] for row in evaluations})

    def test_questionnaire_routes_preserve_questions_and_lock_weighted_score(self):
        self.campaign.update(set__candidature_campaign_id=str(ObjectId()))
        self.slots["current"].update(set__assigned_validator_ids=[str(self.admin.id)])
        evaluation = self.records["current"]
        admin = SimpleNamespace(id=ObjectId(), admin_type="super_admin", is_admin=True, is_active=True, profile_data={})
        bank_path = "/api/admin/interviews/campaigns/" + str(self.campaign.id) + "/question-bank"
        evaluation_path = "/api/admin/interviews/evaluations/" + str(evaluation.id) + "/questionnaire"
        rows = []
        for section, profiles, number in (
            ("technique", ("avec", "sans"), 5), ("motivation", ("tous",), 3), ("social", ("tous",), 2),
        ):
            for profile in profiles:
                for topic in range(number):
                    rows.append({
                        "section": section, "profile": profile, "topic": f"Thème {topic}", "points": 2,
                        "prompt": f"Question {section} {profile} {topic}",
                        "options": ["Oui", "Non", "Peut-être"] if section == "technique" else [],
                        "correct": "A" if section == "technique" else "",
                    })

        self.assertEqual(403, self.client.get(bank_path, headers=self.headers).status_code)
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=admin):
            response = self.client.put(bank_path, headers=self.headers, json={"questions": rows, "revision": 0})
            self.assertEqual(200, response.status_code, response.json)
            self.assertEqual(1, response.json["data"]["revision"])
            stale = self.client.put(bank_path, headers=self.headers, json={"questions": rows, "revision": 0})
            self.assertEqual(409, stale.status_code)
        response = self.client.post(evaluation_path, headers=self.headers, json={"profile": "sans"})
        self.assertEqual(200, response.status_code, response.json)
        form = response.json["data"]
        self.assertEqual(10, len(form["questions"]))
        self.assertTrue(all("correct" not in question for question in form["questions"]))
        self.assertEqual("sans", form["profile"])
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=admin):
            added = {**rows[5], "prompt": "Variante technique"}
            response = self.client.patch(bank_path, headers=self.headers, json={"action": "add", "question": added, "revision": 1})
            self.assertEqual(200, response.status_code, response.json)
            response = self.client.patch(bank_path, headers=self.headers, json={
                "action": "edit", "index": len(rows), "question": {**added, "points": 3}, "revision": 2,
            })
            self.assertEqual(3, response.json["data"]["questions"][-1]["points"])
            toggle = {"action": "set_active", "index": 5, "active": False}
            self.assertEqual(409, self.client.patch(bank_path, headers=self.headers, json={**toggle, "revision": 2}).status_code)
            response = self.client.patch(bank_path, headers=self.headers, json={**toggle, "revision": 3})
            stored = response.json["data"]["questions"]
            self.assertIs(stored[5]["active"], False)
            self.assertIn(added["prompt"], {question["prompt"] for question in generate_questions(stored, "sans")})
            response = self.client.put(bank_path, headers=self.headers, json={
                "questions": [{**rows[-1], "prompt": "Variante sociale"}], "mode": "append", "revision": 4,
            })
            self.assertEqual(len(rows) + 2, len(response.json["data"]["questions"]))
            self.assertIs(response.json["data"]["questions"][5]["active"], False)
            response = self.client.patch(bank_path, headers=self.headers, json={**toggle, "active": True, "revision": 5})
            self.assertTrue(response.json["data"]["questions"][5].get("active", True))
            config_path = bank_path.replace("question-bank", "questionnaire-config")
            invalid = {"technique": {"count": 5, "weight": 60}, "motivation": {"count": 3, "weight": 20}, "social": {"count": 2, "weight": 19}}
            self.assertEqual(400, self.client.put(config_path, headers=self.headers, json={"config": invalid}).status_code)
            larger = {**invalid, "social": {"count": 4, "weight": 20}}
            response = self.client.put(config_path, headers=self.headers, json={"config": larger})
            self.assertEqual(200, response.status_code, response.json)
            self.assertEqual(larger, response.json["data"]["config"])
            self.assertIn("au moins 4", response.json["data"]["coverage_error"])
            response = self.client.put(config_path, headers=self.headers, json={"config": {**larger, "social": {"count": 2, "weight": 20}}})
            self.assertIsNone(response.json["data"]["coverage_error"])
            replacement = [{**row, "prompt": "Nouveau " + row["prompt"]} for row in rows]
            response = self.client.put(bank_path, headers=self.headers, json={"questions": replacement, "revision": 6})
            self.assertEqual(200, response.status_code, response.json)

        regenerated = self.client.post(evaluation_path, headers=self.headers, json={"profile": "avec"})
        self.assertEqual(form, regenerated.json["data"])
        check = self.client.post(evaluation_path + "/check", headers=self.headers, json={
            "question_id": "1", "answer": "B", "revision": 1,
        })
        self.assertEqual(200, check.status_code, check.json)
        self.assertEqual({"outcome": "incorrect", "expected_option": "A", "points": 0, "answer": "B"}, check.json["data"])
        outside = evaluation_path.replace(str(evaluation.id), str(self.records["past"].id)) + "/check"
        self.assertEqual(403, self.client.post(outside, headers=self.headers, json={}).status_code)
        self.assertEqual({}, evaluation.reload().questionnaire["answers"])
        answers = {
            question["id"]: "A" if question["section"] == "technique" else {"points": 1}
            for question in form["questions"]
        }
        draft_answers = {"1": "A", "2": "B", "3": "aucune", "6": {"points": 0, "comment": "Réponse à approfondir"}}
        session = str(uuid4())
        draft_data = {"action": "draft", "revision": 1, "answers": draft_answers, "draft_session": session, "draft_sequence": 2}
        draft = self.client.patch(evaluation_path, headers=self.headers, json=draft_data)
        self.assertEqual(200, draft.status_code, draft.json)
        self.assertEqual(2, draft.json["data"]["revision"])
        out_of_order = self.client.patch(evaluation_path, headers=self.headers, json={**draft_data, "draft_sequence": 1, "answers": {}})
        self.assertEqual(200, out_of_order.status_code)
        self.assertEqual(draft_answers, out_of_order.json["data"]["answers"])
        self.assertEqual(2, out_of_order.json["data"]["revision"])
        other_session = self.client.patch(evaluation_path, headers=self.headers, json={**draft_data, "draft_session": str(uuid4())})
        self.assertEqual(409, other_session.status_code)
        close_save = self.client.patch(evaluation_path, headers=self.headers, json={**draft_data, "draft_sequence": 3, "comment": "À reprendre"})
        self.assertEqual(200, close_save.status_code)
        self.assertEqual(3, close_save.json["data"]["revision"])
        self.assertEqual("À reprendre", close_save.json["data"]["comment"])
        validator_view = self.client.get(evaluation_path, headers=self.headers).json["data"]
        self.assertNotIn("review", validator_view)
        self.assertEqual({"1", "2", "3"}, set(validator_view["feedback"]))
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=admin):
            response = self.client.get(evaluation_path, headers=self.headers)
        self.assertEqual(200, response.status_code, response.json)
        details = response.json["data"]
        self.assertEqual("sans", details["profile"])
        self.assertEqual(draft_answers, details["answers"])
        self.assertTrue(details["review"]["saved_at"])
        marks = details["review"]["questions"]
        self.assertEqual({"outcome": "correct", "expected_option": "A", "points": 2}, marks["1"])
        self.assertEqual({"outcome": "incorrect", "expected_option": "A", "points": 0}, marks["2"])
        self.assertEqual("no_answer", marks["3"]["outcome"])
        self.assertEqual({"outcome": "unanswered", "expected_option": "A", "points": None}, marks["4"])
        self.assertEqual({"outcome": "graded", "points": 0}, marks["6"])
        self.assertIsNone(details["scores"])
        submit = {"action": "validate", "revision": 3, "answers": answers}
        validated = self.client.patch(evaluation_path, headers=self.headers, json=submit)
        self.assertEqual(200, validated.status_code, validated.json)
        # Generated before the 60/20/20 configuration: the questionnaire keeps its 50/30/20 snapshot.
        self.assertEqual({"technique": 50, "motivation": 15, "social": 10, "global": 75}, validated.json["data"]["scores"])
        self.assertTrue(evaluation.reload().is_locked)
        self.assertEqual(409, self.client.patch(evaluation_path, headers=self.headers, json={**submit, "revision": 4}).status_code)
        self.assertEqual(409, self.client.patch(evaluation_path, headers=self.headers, json={**draft_data, "draft_sequence": 4}).status_code)
        self.assertEqual(403, self.client.get(evaluation_path.replace(str(evaluation.id), str(self.records["past"].id)), headers=self.headers).status_code)
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=admin):
            reopened = self.client.patch(evaluation_path, headers=self.headers, json={"action": "reopen", "revision": 4})
        self.assertEqual(200, reopened.status_code, reopened.json)
        self.assertEqual("draft", reopened.json["data"]["status"])
        self.assertFalse(evaluation.reload().is_locked)
        self.assertFalse(self.client.get(evaluation_path, headers=self.headers).json["data"]["read_only"])

        archived = CandidatureCampaign(
            title="Promotion archivée", formation="all", status="archived",
            start_at=datetime(2026, 1, 1), end_at=datetime(2026, 2, 1),
        ).save()
        self.campaign.update(set__candidature_campaign_id=str(archived.id))
        revision = reopened.json["data"]["revision"]
        self.assertTrue(self.client.get(evaluation_path, headers=self.headers).json["data"]["read_only"])
        blocked = self.client.patch(evaluation_path, headers=self.headers, json={"action": "draft", "revision": revision, "answers": {}})
        self.assertEqual(403, blocked.status_code, blocked.json)
        self.assertEqual(403, self.client.post(evaluation_path + "/check", headers=self.headers, json={
            "question_id": "1", "answer": "A", "revision": revision,
        }).status_code)
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=admin):
            self.assertFalse(self.client.get(evaluation_path, headers=self.headers).json["data"]["read_only"])
            corrected = self.client.patch(evaluation_path, headers=self.headers, json={"action": "validate", "revision": revision, "answers": answers})
        self.assertEqual(200, corrected.status_code, corrected.json)
        self.assertEqual("validated", corrected.json["data"]["status"])
        self.assertEqual(str(admin.id), evaluation.reload().questionnaire["finalized_by"])

    def test_bootstrap_slots_and_evaluations_hide_past_and_future(self):
        bootstrap = self.get("bootstrap")
        self.assertEqual(200, bootstrap.status_code)
        data = bootstrap.json["data"]
        self.assertEqual(["current"], [slot["label"] for slot in data["slots"]])
        self.assertEqual(["filter"], data["slots"][0]["access"]["editable_roles"])
        self.assertTrue(data["server_now"].endswith("Z"))
        self.assertEqual(["current"], [slot["label"] for slot in self.get("slots").json["data"]])
        page = self.get("evaluations?pageSize=25")
        self.assertEqual([str(self.records["current"].id)], [item["id"] for item in page.json["data"]])

    def test_direct_slot_filter_and_csv_cannot_bypass_window(self):
        response = self.get("evaluations?slotId=" + str(self.slots["future"].id))
        self.assertEqual([], response.json["data"])
        csv = self.get("evaluations/export").get_data(as_text=True)
        self.assertIn("current@example.com", csv)
        self.assertNotIn("past@example.com", csv)
        self.assertNotIn("future@example.com", csv)

    def test_filter_patch_after_end_is_403_without_persisting(self):
        self.now = self.slots["current"].end_at
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["current"].id),
            headers=self.headers, json={"filter_review": {}},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual({}, self.records["current"].reload().filter_review)
        self.assertNotIn("current", [slot["label"] for slot in self.get("slots").json["data"]])

    def test_validator_can_read_and_save_own_section_after_end(self):
        slot = self.slots["past"]
        slot.assigned_validator_ids = [str(self.admin.id)]
        slot.save()
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["past"].id),
            headers=self.headers, json={"validator_review": {}},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(str(self.admin.id), self.records["past"].reload().validator_review["_owner_admin_id"])
        slots = self.get("slots").json["data"]
        past = next(item for item in slots if item["label"] == "past")
        self.assertEqual(["validator"], past["access"]["editable_roles"])

    def test_validator_elsewhere_does_not_unlock_filter_slot(self):
        self.slots["past"].assigned_validator_ids = [str(self.admin.id)]
        self.slots["past"].save()
        self.now = self.slots["current"].end_at
        visible_ids = self.query._get_assigned_slot_ids(self.admin)
        self.assertIn(str(self.slots["past"].id), visible_ids)
        self.assertNotIn(str(self.slots["current"].id), visible_ids)

    def test_filter_cannot_save_a_future_slot_even_with_direct_url(self):
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["future"].id),
            headers=self.headers, json={"filter_review": {}},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual({}, self.records["future"].reload().filter_review)

    def test_mixed_payload_cannot_write_expired_filter_review(self):
        self.slots["past"].assigned_validator_ids = [str(self.admin.id)]
        self.slots["past"].save()
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["past"].id),
            headers=self.headers, json={"filter_review": {}, "validator_review": {}},
        )
        self.assertEqual(403, response.status_code)
        evaluation = self.records["past"].reload()
        self.assertEqual({}, evaluation.filter_review)
        self.assertEqual({}, evaluation.validator_review)

    def test_members_cannot_reschedule_slots_or_create_campaigns(self):
        for method, path, data in (
            ("patch", "slots/" + str(self.slots["past"].id), {"end_at": "2030-01-01T12:00"}),
            ("post", "slots", {}), ("post", "campaigns", {}),
            ("patch", "campaigns/" + str(self.campaign.id), {"status": "active"}),
            ("post", "evaluations/seed", {}),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    "/api/admin/interviews/" + path, headers=self.headers, json=data,
                )
                self.assertEqual(403, response.status_code)

    def test_planning_admin_keeps_all_slots(self):
        self.admin.profile_data = {}
        self.assertEqual(3, len(self.get("slots").json["data"]))


if __name__ == "__main__":
    unittest.main()
