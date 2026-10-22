"""Bounded literal search shared by admin lists, with accents and phone formatting."""

import re
import unicodedata


def fold(value):
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(char))


ACCENTS = {}
for code in range(0xC0, 0x250):
    char = chr(code)
    base = fold(char)
    if len(base) == 1 and base.isascii() and base.isalpha():
        ACCENTS.setdefault(base, set()).add(char)


def literal_pattern(value):
    parts = []
    for char in fold(value):
        variants = "".join(sorted(ACCENTS.get(char, set()) | {char}))
        atom = "[" + re.escape(variants) + "]" if char in ACCENTS else re.escape(char)
        parts.append(atom + "[\u0300-\u036f]*")
    return "".join(parts)


def text_search_filter(value, fields, phone_fields=()):
    search = " ".join(str(value or "").split())
    if len(search) > 200 or len(search.split()) > 12:
        raise ValueError("Recherche trop longue (200 caracteres, 12 mots maximum)")
    if not search:
        return {}
    if phone_fields and re.fullmatch(r"[+\d\s().-]+", search) and any(char.isdigit() for char in search):
        digits = re.sub(r"\D", "", search)
        regex = {"$regex": r"[\s().+-]*".join(digits)}
        return {"$or": [{field: regex} for field in phone_fields]}
    return {"$and": [{"$or": [
        {field: {"$regex": literal_pattern(token), "$options": "i"}} for field in fields
    ]} for token in search.split()]}
