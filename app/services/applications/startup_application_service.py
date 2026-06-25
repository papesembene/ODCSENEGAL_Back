"""Startup Lab application business rules."""

from datetime import datetime
import uuid

from app.models.startup import Startup
from app.services.applications.base_application_service import (
    BaseApplicationService,
)


class StartupApplicationService(BaseApplicationService):
    required_fields = (
        "firstName",
        "lastName",
        "role",
        "email",
        "phone",
        "phoneCountry",
        "region",
        "department",
        "diploma",
        "companyName",
        "ninea",
        "sector",
        "businessModel",
        "creationDate",
        "legalForm",
        "employees",
        "raisedFunds",
        "productName",
        "productDescription",
        "activityDescription",
        "hasWorkingProduct",
    )
    pitch_field = "pitchDeck"
    validate_company_creation_date = True

    def __init__(self, upload_folder):
        super().__init__(Startup, upload_folder)

    def prepare_model_data(self, data):
        data["program"] = "startup_lab"
        data["founder_email"] = data["email"]
        timestamp = datetime.now().strftime("%y%m%d%H%M")
        unique_id = str(uuid.uuid4())[:8]
        data["startup_name"] = (
            f"{data['companyName']}-{timestamp}-{unique_id}"
        )

    def build_email_data(self, application):
        data = super().build_email_data(application)
        data["program"] = "Startup Lab"
        return data

    def list_summaries(self):
        return [
            {
                "id": str(startup.id),
                "companyName": startup.companyName,
                "startup_name": startup.startup_name,
                "firstName": startup.firstName,
                "lastName": startup.lastName,
                "email": startup.email,
                "createdAt": (
                    startup.createdAt.strftime("%d/%m/%Y %H:%M")
                    if startup.createdAt
                    else None
                ),
            }
            for startup in Startup.objects.all()
        ]

    def get(self, startup_id):
        return Startup.objects.get(id=startup_id)
