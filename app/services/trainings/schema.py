"""Validation of editable training information, without database access."""

import re
import unicodedata


class TrainingCatalogError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def token(value):
    text = unicodedata.normalize("NFD", str(value or "").strip().casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).replace("_", " ").split())


def training_code(title):
    code = re.sub(r"[^a-z0-9]+", "-", token(title)).strip("-")[:80].rstrip("-")
    if not code:
        raise TrainingCatalogError("Le nom doit contenir des lettres ou des chiffres.")
    return code


TEXT_FIELDS = {"title": 200, "description": 10000, "level": 500, "careers": 3000,
               "location": 300, "startDate": 100, "endDate": 100, "imageUrl": 1000}
EDITABLE_FIELDS = {*TEXT_FIELDS, "skills", "durationMonths", "femaleOnly", "status", "displayOrder",
                   "applicationRegionMode", "applicationRegions"}


def validate_training(payload, previous=None):
    if not isinstance(payload, dict):
        raise TrainingCatalogError("Les informations du référentiel sont invalides.")
    if "applicationRegions" in payload and "applicationRegionMode" not in payload:
        raise TrainingCatalogError("Actualisez la page avant de modifier les régions / localités de résidence.")
    unknown = set(payload) - EDITABLE_FIELDS - {"version"}
    if unknown:
        raise TrainingCatalogError("Champ non modifiable : " + ", ".join(sorted(unknown)))
    data = {**(previous or {}), **{key: value for key, value in payload.items() if key in EDITABLE_FIELDS}}
    for field, limit in TEXT_FIELDS.items():
        value = data.get(field, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise TrainingCatalogError(f"Le champ {field} est invalide (maximum {limit} caractères).")
        data[field] = value.strip()
    if not data["title"]:
        raise TrainingCatalogError("Le nom du référentiel est obligatoire.")
    for field, default, minimum, maximum in (("durationMonths", None, 1, 36), ("displayOrder", 0, 0, 10000)):
        value = data.get(field, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise TrainingCatalogError(f"Le champ {field} doit être compris entre {minimum} et {maximum}.")
        data[field] = value
    if type(data.get("femaleOnly", False)) is not bool:
        raise TrainingCatalogError("Le champ femaleOnly doit être un booléen.")
    data["femaleOnly"] = data.get("femaleOnly", False)
    if not isinstance(data.get("status", "draft"), str) or data.get("status", "draft") not in {"draft", "published", "archived"}:
        raise TrainingCatalogError("Le statut du référentiel est invalide.")
    data["status"] = data.get("status", "draft")
    skills = data.get("skills", [])
    if not isinstance(skills, list) or len(skills) > 40 or any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > 500 for item in skills
    ):
        raise TrainingCatalogError("Les objectifs doivent contenir au maximum 40 lignes de 500 caractères.")
    data["skills"] = list(dict.fromkeys(item.strip() for item in skills))
    if data["imageUrl"] and not re.fullmatch(r"/static/uploads/trainings/[A-Za-z0-9_.-]+", data["imageUrl"]):
        raise TrainingCatalogError("Veuillez importer une image depuis le formulaire.")
    data["duration"] = f"{data['durationMonths']} mois"
    from app.services.trainings.regional_eligibility import validate_residence_policy
    data.update(validate_residence_policy(data))
    return data
