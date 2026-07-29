"""Shared referential naming helpers for online tests."""

import unicodedata


FORMATION_ALIASES = {
    "Dev Web": (
        "Dev Web",
        "dev-web-mobile",
        "developpement-web-mobile",
        "Développement Web",
        "Developpement Web",
        "Dev Web Mobile",
    ),
    "Data": (
        "Data",
        "dev-data",
        "Data Science",
        "data-science",
        "data science",
        "Dev Data",
    ),
    "Hackeuse": (
        "Hackeuse",
        "Hackeuses",
        "hackeuses",
    ),
    "AWS": (
        "AWS",
        "aws-cloud",
        "AWS Cloud",
        "Cloud",
    ),
    "Référent Digital": (
        "Référent Digital",
        "Référent digital",
        "Referent Digital",
        "Referent digital",
        "referent-digital",
        "référent-digital",
    ),
    "Cyber security": (
        "Cyber security",
        "Cyber Security",
        "cyber-security",
        "Cybersecurity",
        "Cyber sécurité",
        "Cyber Sécurité",
        "Cyber securite",
        "Cyber Securite",
    ),
    "Intelligence Artificielle": (
        "Intelligence Artificielle",
        "intelligence-artificielle",
        "IA",
        "AI",
    ),
}

FORMATIONS = tuple(FORMATION_ALIASES.keys())


def normalize_formation(value):
    token = normalize_formation_token(value)
    for label, aliases in FORMATION_ALIASES.items():
        if token in {normalize_formation_token(alias) for alias in aliases}:
            return label

    if "dev" in token and ("web" in token or "mobile" in token):
        return "Dev Web"
    if "data" in token:
        return "Data"
    if "hack" in token:
        return "Hackeuse"
    if "aws" in token or "cloud" in token:
        return "AWS"
    if "referent" in token or "digital" in token:
        return "Référent Digital"
    if "cyber" in token:
        return "Cyber security"
    if "intel" in token or token == "ia":
        return "Intelligence Artificielle"

    return value


def formation_aliases(value):
    normalized = normalize_formation(value)
    aliases = list(FORMATION_ALIASES.get(normalized, (value,)))
    if value and value not in aliases:
        aliases.append(value)
    return aliases


def normalize_formation_token(value):
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.replace("_", " ").replace("-", " ").split())
