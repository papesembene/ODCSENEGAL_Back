"""Interview scorecard rules independent from Flask and MongoDB."""

from copy import deepcopy
import re


SCORECARD_SECTION_KEYS = ("filter", "validator", "motivation")
SCORECARD_CRITERION_TYPES = {
    "text",
    "textarea",
    "checkbox",
    "select",
    "number",
    "computed",
}
SCORECARD_BUSINESS_CRITERION_TYPES = {"checkbox", "number"}
SCORECARD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
SCORECARD_SYSTEM_CRITERIA = {
    "filter": {
        "interviewer": "text",
        "comment": "textarea",
        "decision": "select",
        "total_score": "computed",
    },
    "validator": {
        "interviewer": "text",
        "verdict": "select",
        "comment": "textarea",
    },
    "motivation": {
        "interviewer": "text",
        "comment": "textarea",
    },
}

DWM_SCORECARD_CONFIG = {
    "source": "excel",
    "source_label": "Grille alignée sur le fichier Excel DWM",
    "sections": {
        "filter": {
            "title": "Filtreur",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom du filtreur",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "comment",
                    "label": "Commentaire filtreur",
                    "type": "textarea",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "anti_cheat_score",
                    "label": "Anti-triche validé",
                    "type": "checkbox",
                    "required": False,
                },
                {
                    "key": "logic_score",
                    "label": "Logique validée",
                    "type": "checkbox",
                    "required": False,
                },
                {
                    "key": "total_score",
                    "label": "Total filtre",
                    "type": "computed",
                    "required": False,
                    "system": True,
                    "suffix": "/ 2",
                    "depends_on": ["anti_cheat_score", "logic_score"],
                },
                {
                    "key": "decision",
                    "label": "Décision filtreur",
                    "type": "select",
                    "required": True,
                    "system": True,
                    "options": [
                        {"value": "validateur", "label": "Validateur"},
                        {"value": "echec", "label": "Échec"},
                    ],
                },
            ],
        },
        "validator": {
            "title": "Validateur",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom du validateur",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "algorithm_logic_score",
                    "label": "Algo / Logique validé",
                    "type": "checkbox",
                    "required": False,
                },
                {
                    "key": "verdict",
                    "label": "Verdict",
                    "type": "select",
                    "required": True,
                    "system": True,
                    "options": [
                        {"value": "oui", "label": "Oui"},
                        {"value": "non", "label": "Non"},
                        {"value": "reserve", "label": "Avec réserve"},
                        {"value": "a_revoir", "label": "À revoir"},
                    ],
                },
                {
                    "key": "comment",
                    "label": "Commentaire validateur",
                    "type": "textarea",
                    "required": False,
                    "system": True,
                },
            ],
        },
        "motivation": {
            "title": "Motivation",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom jury motivation",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "comment",
                    "label": "Commentaire motivation",
                    "type": "textarea",
                    "required": True,
                    "system": True,
                },
            ],
        },
    },
}


def get_default_scorecard_config(formation):
    if formation == "dev-web-mobile":
        return deepcopy(DWM_SCORECARD_CONFIG)

    sections = {
        "filter": {
            "title": "Filtreur",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom du filtreur",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "comment",
                    "label": "Commentaire filtreur",
                    "type": "textarea",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "decision",
                    "label": "Décision filtreur",
                    "type": "select",
                    "required": True,
                    "system": True,
                    "options": [
                        {"value": "validateur", "label": "Validateur"},
                        {"value": "echec", "label": "Échec"},
                    ],
                },
            ],
        },
        "validator": {
            "title": "Validateur",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom du validateur",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "verdict",
                    "label": "Verdict",
                    "type": "select",
                    "required": True,
                    "system": True,
                    "options": [
                        {"value": "oui", "label": "Oui"},
                        {"value": "non", "label": "Non"},
                        {"value": "reserve", "label": "Avec réserve"},
                        {"value": "a_revoir", "label": "À revoir"},
                    ],
                },
                {
                    "key": "comment",
                    "label": "Commentaire validateur",
                    "type": "textarea",
                    "required": False,
                    "system": True,
                },
            ],
        },
        "motivation": {
            "title": "Motivation",
            "criteria": [
                {
                    "key": "interviewer",
                    "label": "Nom jury motivation",
                    "type": "text",
                    "required": True,
                    "system": True,
                },
                {
                    "key": "comment",
                    "label": "Commentaire motivation",
                    "type": "textarea",
                    "required": True,
                    "system": True,
                },
            ],
        },
    }
    return {
        "source": "custom",
        "source_label": "Grille à configurer par le super admin",
        "sections": sections,
    }


def sanitize_scorecard_config(value):
    if not isinstance(value, dict):
        raise ValueError("La grille d'entretien est invalide")

    raw_sections = value.get("sections")
    if not isinstance(raw_sections, dict):
        raise ValueError("Les sections de la grille sont requises")

    sections = {}
    for section_key in SCORECARD_SECTION_KEYS:
        raw_section = raw_sections.get(section_key) or {}
        raw_criteria = raw_section.get("criteria") or []
        if not isinstance(raw_criteria, list):
            raise ValueError(
                f"Les critères de la section {section_key} sont invalides"
            )

        criteria = []
        seen_keys = set()
        for raw_criterion in raw_criteria:
            criterion = _sanitize_criterion(
                raw_criterion,
                section_key=section_key,
                seen_keys=seen_keys,
            )
            criteria.append(criterion)
            seen_keys.add(criterion["key"])

        sections[section_key] = {
            "title": (raw_section.get("title") or section_key.title()).strip(),
            "criteria": criteria,
        }

    return {
        "source": (value.get("source") or "custom").strip(),
        "source_label": (
            value.get("source_label") or "Grille personnalisée"
        ).strip(),
        "sections": sections,
    }


def _sanitize_criterion(raw_criterion, section_key, seen_keys):
    if not isinstance(raw_criterion, dict):
        raise ValueError("Un critère de la grille est invalide")

    key = (raw_criterion.get("key") or "").strip()
    label = (raw_criterion.get("label") or "").strip()
    criterion_type = raw_criterion.get("type")
    if not SCORECARD_KEY_PATTERN.match(key):
        raise ValueError(f"Clé de critère invalide: {key or 'vide'}")
    if key in seen_keys:
        raise ValueError(
            f"Le critère {key} est dupliqué dans la section {section_key}"
        )
    if not label:
        raise ValueError(f"Le libellé du critère {key} est requis")
    if criterion_type not in SCORECARD_CRITERION_TYPES:
        raise ValueError(f"Type invalide pour le critère {label}")

    is_system_criterion = bool(raw_criterion.get("system"))
    expected_system_type = SCORECARD_SYSTEM_CRITERIA[section_key].get(key)
    if is_system_criterion and expected_system_type != criterion_type:
        raise ValueError(f"Le champ système {label} est invalide")
    if (
        not is_system_criterion
        and criterion_type not in SCORECARD_BUSINESS_CRITERION_TYPES
    ):
        raise ValueError(
            f"Le critère {label} doit être une case à cocher ou une note"
        )

    criterion = {
        "key": key,
        "label": label,
        "type": criterion_type,
        "required": bool(raw_criterion.get("required")),
        "system": is_system_criterion,
    }
    placeholder = (raw_criterion.get("placeholder") or "").strip()
    if placeholder:
        criterion["placeholder"] = placeholder
    if criterion_type == "number":
        criterion["min"] = raw_criterion.get("min", 0)
        criterion["max"] = raw_criterion.get("max", 20)
    if criterion_type == "computed":
        criterion["suffix"] = (raw_criterion.get("suffix") or "").strip()
        criterion["depends_on"] = [
            dependency
            for dependency in (raw_criterion.get("depends_on") or [])
            if isinstance(dependency, str)
            and SCORECARD_KEY_PATTERN.match(dependency)
        ]
    if criterion_type == "select":
        criterion["options"] = _sanitize_select_options(raw_criterion, label)

    return criterion


def _sanitize_select_options(raw_criterion, label):
    options = []
    for option in raw_criterion.get("options") or []:
        if not isinstance(option, dict):
            continue
        option_value = (option.get("value") or "").strip()
        option_label = (option.get("label") or "").strip()
        if option_value and option_label:
            options.append({"value": option_value, "label": option_label})
    if not options:
        raise ValueError(
            f"Le critère {label} doit contenir au moins une option"
        )
    return options


def is_scorecard_ready(scorecard_config):
    sections = (scorecard_config or {}).get("sections") or {}
    return any(
        any(
            not criterion.get("system")
            and criterion.get("type") != "computed"
            for criterion in (
                (sections.get(section_key) or {}).get("criteria") or []
            )
        )
        for section_key in SCORECARD_SECTION_KEYS
    )


def is_required_value_filled(value, criterion_type):
    if criterion_type == "checkbox":
        return isinstance(value, bool)
    return value is not None and str(value).strip() != ""


def is_evaluation_complete(evaluation, scorecard_config):
    sections = (scorecard_config or {}).get("sections") or {}
    reviews = {
        "filter": _read_evaluation_value(evaluation, "filter_review") or {},
        "validator": _read_evaluation_value(
            evaluation,
            "validator_review",
        ) or {},
        "motivation": _read_evaluation_value(
            evaluation,
            "motivation_review",
        ) or {},
    }
    for section_key in SCORECARD_SECTION_KEYS:
        criteria = (sections.get(section_key) or {}).get("criteria") or []
        if not criteria:
            return False
        for criterion in criteria:
            if criterion.get("required") and not is_required_value_filled(
                reviews[section_key].get(criterion.get("key")),
                criterion.get("type"),
            ):
                return False
    return True


def _read_evaluation_value(evaluation, field):
    if isinstance(evaluation, dict):
        return evaluation.get(field)
    return getattr(evaluation, field, None)


def sanitize_review(review, section):
    if not isinstance(review, dict):
        raise ValueError("Les réponses de la section sont invalides")

    sanitized = {}
    for criterion in (section or {}).get("criteria") or []:
        criterion_type = criterion.get("type")
        if criterion_type == "computed":
            sanitized[criterion["key"]] = _compute_criterion(
                review,
                criterion,
            )
            continue

        key = criterion["key"]
        value = review.get(key)
        if criterion_type == "checkbox":
            sanitized[key] = bool(value)
        elif criterion_type == "number":
            sanitized[key] = _sanitize_number(value, criterion)
        elif criterion_type == "select":
            sanitized[key] = _sanitize_select(value, criterion)
        else:
            sanitized[key] = str(value or "").strip()

    return sanitized


def _compute_criterion(review, criterion):
    return sum(
        int(bool(review.get(dependency)))
        for dependency in criterion.get("depends_on") or []
    )


def _sanitize_number(value, criterion):
    if value in [None, ""]:
        return None

    number_value = float(value)
    minimum = criterion.get("min")
    maximum = criterion.get("max")
    if minimum is not None and number_value < float(minimum):
        raise ValueError(
            f"La valeur de {criterion['label']} est trop basse"
        )
    if maximum is not None and number_value > float(maximum):
        raise ValueError(
            f"La valeur de {criterion['label']} est trop élevée"
        )
    return number_value


def _sanitize_select(value, criterion):
    allowed_values = {
        option.get("value")
        for option in criterion.get("options") or []
    }
    if value and value not in allowed_values:
        raise ValueError(
            f"Choix invalide pour {criterion['label']}"
        )
    return value or ""
