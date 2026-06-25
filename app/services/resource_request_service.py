"""Resource request use cases."""

from app.models.resource_request import ResourceRequest


class ResourceRequestService:
    def create(self, data):
        data = data or {}
        request_doc = ResourceRequest(
            startup_name=data.get("startupName"),
            contact_person=data.get("contactPerson"),
            email=data.get("email"),
            phone=data.get("phone"),
            resource=data.get("resource"),
            requested_date=data.get("requestedDate"),
            requested_time=data.get("requestedTime", ""),
            details=data.get("details"),
            accept_terms=data.get("acceptTerms", False),
        )
        request_doc.save()
        return request_doc

    @staticmethod
    def list_all():
        return [
            item.to_dict()
            for item in ResourceRequest.objects().order_by("-created_at")
        ]
