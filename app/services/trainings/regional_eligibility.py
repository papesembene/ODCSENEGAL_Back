"""Residence-based admissions, independent from a training's physical location."""

from app.services.trainings.schema import TrainingCatalogError, token

APPLICATION_REGIONS = (
    "Dakar", "Diamniadio", "Diourbel", "Fatick", "Kaffrine", "Kaolack", "Kédougou",
    "Kolda", "Louga", "Matam", "Saint-Louis", "Sédhiou", "Tambacounda", "Thiès", "Ziguinchor",
)
# Read compatibility only: convert old partial exceptions to a complete policy.
LEGACY_RESTRICTED_REGIONS = ("Thiès", "Diamniadio", "Tambacounda")
LEGACY_ASSIGNMENTS = {
    "dev-data": ["Thiès", "Diamniadio"],
    "referent-digital": ["Tambacounda"],
    "fibre": ["Tambacounda"],
    "fibre-optique": ["Tambacounda"],
}
REGION_ALIASES = {token(region): region for region in APPLICATION_REGIONS}
REGION_ALIASES["tamba"] = "Tambacounda"


def canonical_region(value):
    return REGION_ALIASES.get(token(value)) if isinstance(value, str) else None


def validate_application_regions(values):
    if not isinstance(values, list) or len(values) > len(APPLICATION_REGIONS):
        raise TrainingCatalogError("Les régions / localités de résidence sont invalides.")
    regions = [canonical_region(value) for value in values]
    if any(region is None for region in regions):
        raise TrainingCatalogError("Choisissez des régions / localités de résidence dans la liste proposée.")
    return list(dict.fromkeys(regions))


def validate_residence_policy(training):
    regions = validate_application_regions(training.get("applicationRegions", []))
    mode = training.get("applicationRegionMode", "selected" if regions else "all")
    if not isinstance(mode, str) or mode not in {"all", "selected"}:
        raise TrainingCatalogError("Le mode de sélection des lieux de résidence est invalide.")
    if mode == "selected" and not regions:
        raise TrainingCatalogError("Sélectionnez au moins une région / localité de résidence.")
    return {"applicationRegionMode": mode, "applicationRegions": regions if mode == "selected" else []}


def with_regional_eligibility(training):
    if "applicationRegionMode" in training:
        return {**training, **validate_residence_policy(training)}
    assignments = training.get("applicationRegions", LEGACY_ASSIGNMENTS.get(training["code"], []))
    regions = [region for region in APPLICATION_REGIONS
               if region not in LEGACY_RESTRICTED_REGIONS or region in assignments]
    return {**training, "applicationRegionMode": "selected", "applicationRegions": regions}


def is_training_allowed(training, region):
    canonical = canonical_region(region)
    if not canonical:
        return False
    policy = with_regional_eligibility(training)
    return policy["applicationRegionMode"] == "all" or canonical in policy["applicationRegions"]


def regional_rules():
    return {"regions": list(APPLICATION_REGIONS), "residenceRegions": list(APPLICATION_REGIONS),
            "defaultMode": "all", "defaults": {}}
