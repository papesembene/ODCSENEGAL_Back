"""Read models used by administration application lists."""

from app.models.candidature import Candidature
from app.models.startup import Startup


def _iso(value):
    return value.isoformat() if value else None


class AdminApplicationReadService:
    def competence_applications(self):
        data = [
            {
                "id": str(item.id),
                "firstName": item.first_name,
                "lastName": item.last_name,
                "email": item.email,
                "phone": item.phone,
                "gender": item.gender,
                "age": None,
                "education": item.education_level,
                "address": item.region_of_residence,
                "formation": item.desired_training,
                "status": item.status or "pending",
                "applicationDate": _iso(item.created_at),
                "cv": None,
            }
            for item in Candidature.objects()
        ]
        return {"success": True, "candidatures": data, "total": len(data)}

    def startup_applications(self):
        data = [self._serialize_startup(item) for item in Startup.objects()]
        return {"success": True, "data": data, "total": len(data)}

    @staticmethod
    def _serialize_startup(item):
        program = getattr(item, "program", None) or "startup_lab"
        return {
            "id": str(item.id),
            "startup_name": getattr(item, "startup_name", None)
            or getattr(item, "companyName", None),
            "website": getattr(item, "website", None),
            "founding_date": getattr(item, "creationDate", None),
            "sector": getattr(item, "sector", None),
            "stage": getattr(item, "businessModel", None),
            "team_size": getattr(item, "employees", None),
            "program": program,
            "status": getattr(item, "status", None) or "pending",
            "founder_first_name": getattr(item, "firstName", None),
            "founder_last_name": getattr(item, "lastName", None),
            "founder_email": getattr(item, "founder_email", None)
            or getattr(item, "email", None),
            "founder_phone": getattr(item, "fullPhone", None)
            or getattr(item, "phone", None),
            "founder_role": getattr(item, "role", None),
            "description": getattr(item, "activityDescription", None),
            "applicationDate": _iso(getattr(item, "createdAt", None)),
            "createdAt": _iso(getattr(item, "createdAt", None)),
            "cv_filename": getattr(item, "cv", None),
            "pitchdeck_filename": getattr(item, "pitchDeck", None),
        }
