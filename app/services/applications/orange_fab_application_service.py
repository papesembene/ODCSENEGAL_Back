"""Orange Fab application business rules."""

from app.models.orangefab import OrangeFab
from app.services.applications.base_application_service import (
    BaseApplicationService,
)


class OrangeFabApplicationService(BaseApplicationService):
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

    def __init__(self, upload_folder):
        super().__init__(OrangeFab, upload_folder)
