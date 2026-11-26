"""Question bank validation, questionnaire generation and scoring."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from random import SystemRandom
import unicodedata

from app.services.interviews.exceptions import InterviewValidationError


SECTIONS = {"technique": (5, 50), "motivation": (3, 30), "social": (2, 20)}
SECTION_LABELS = {"technique": "technique", "motivation": "motivation", "social": "situation sociale"}
PROFILES = ("avec", "sans")
LETTERS = "ABCD"
MAX_QUESTIONS = 400
MAX_SECTION_QUESTIONS = 50


def default_config():
    return {section: {"count": count, "weight": weight} for section, (count, weight) in SECTIONS.items()}


def normalize_config(value):
    """Validate the per-section question count and weight (weights total 100)."""
    if value in (None, {}):
        return default_config()
    if not isinstance(value, dict) or set(value) != set(SECTIONS):
        raise InterviewValidationError("Renseignez le nombre de questions et la pondération de chaque partie.")
    config = {}
    for section in SECTIONS:
        item = value[section]
        if not isinstance(item, dict):
            raise InterviewValidationError("Configuration du questionnaire invalide.")
        count, weight = item.get("count"), item.get("weight")
        label = SECTION_LABELS[section]
        if type(count) is not int or not 1 <= count <= MAX_SECTION_QUESTIONS:
            raise InterviewValidationError(f"Le nombre de questions {label} doit être compris entre 1 et {MAX_SECTION_QUESTIONS}.")
        if type(weight) is not int or not 0 <= weight <= 100:
            raise InterviewValidationError(f"La pondération {label} doit être un entier entre 0 et 100.")
        config[section] = {"count": count, "weight": weight}
    if sum(item["weight"] for item in config.values()) != 100:
        raise InterviewValidationError("La somme des pondérations doit être égale à 100.")
    return config


def config_weights(config):
    """Weights of a questionnaire snapshot; questionnaires generated before configuration use the defaults."""
    try:
        return {section: item["weight"] for section, item in normalize_config(config or None).items()}
    except InterviewValidationError:
        return {section: weight for section, (_, weight) in SECTIONS.items()}


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _text(value, label, maximum, required=True):
    if not isinstance(value, str):
        raise InterviewValidationError(f"{label} doit être du texte.")
    result = value.strip()
    if (required and not result) or len(result) > maximum:
        raise InterviewValidationError(f"{label} doit contenir au plus {maximum} caractères et être renseigné si obligatoire.")
    return result


def _correct_letters(value, count):
    """'A', 'A,C', 'A;C', 'A et C' or ['A', 'C'] -> 'AC' (sorted, distinct letters among the filled options)."""
    if isinstance(value, list):
        value = ",".join(str(item) for item in value)
    if not isinstance(value, str):
        raise InterviewValidationError("La bonne réponse doit être une ou plusieurs lettres (ex. A ou A,C).")
    text = value.upper().replace(" ET ", ",")
    letters = [char for char in text if not char.isspace() and char not in ",;/+-"]
    if not letters or len(letters) > 4 or len(set(letters)) != len(letters) or any(letter not in LETTERS[:count] for letter in letters):
        raise InterviewValidationError("La bonne réponse doit désigner une ou plusieurs propositions renseignées (ex. B ou A,C).")
    return "".join(sorted(letters))


def is_multiple(question):
    return len(question.get("correct") or "") > 1


def _answer_value(question, answer):
    """Validated answer: 'aucune', one letter, or for multiple-answer questions a sorted list of letters."""
    if answer == "aucune":
        return answer
    letters = tuple(LETTERS[:len(question["options"])])
    if is_multiple(question):
        if not isinstance(answer, list) or not answer or len(set(answer)) != len(answer) or any(item not in letters for item in answer):
            return None
        return sorted(answer)
    return answer if isinstance(answer, str) and answer in letters else None


def _is_right(question, answer):
    """All-or-nothing: a multiple-answer question is right only when exactly the right letters are chosen."""
    if answer == "aucune":
        return False
    chosen = "".join(answer) if isinstance(answer, list) else answer
    return chosen == question["correct"]


def _question(row):
    if not isinstance(row, dict):
        raise InterviewValidationError("Cette ligne doit contenir une question.")
    section = _text(row.get("section", ""), "Catégorie", 32).lower()
    if section in {"situation sociale", "situation familiale", "situation sociale ou familiale"}:
        section = "social"
    if section not in SECTIONS:
        raise InterviewValidationError("Catégorie attendue parmi technique, motivation et social.")
    profile = _text(row.get("profile", ""), "Profil", 16, required=False).lower()
    if section == "technique" and profile not in PROFILES:
        raise InterviewValidationError("Une question technique requiert le profil avec ou sans informatique (avec/sans).")
    if section != "technique" and profile not in {"", "tous"}:
        raise InterviewValidationError("Utilisez le profil tous pour la motivation et la situation sociale.")
    topic = _text(row.get("topic", ""), "Thématique", 100)
    prompt = _text(row.get("prompt", ""), "Question", 1000)
    raw_options = row.get("options", [])
    if not isinstance(raw_options, list) or len(raw_options) > 4:
        raise InterviewValidationError("Les propositions doivent être renseignées de A à D.")
    options = [_text(value, "Proposition", 350, required=False) for value in raw_options]
    while options and not options[-1]:
        options.pop()
    raw_correct = row.get("correct", "")
    if options:
        if len(options) < 3 or not all(options) or len({normalized(option) for option in options}) != len(options):
            raise InterviewValidationError("Un QCM doit proposer trois ou quatre réponses distinctes, sans case vide entre elles.")
        correct = _correct_letters(raw_correct, len(options))
        if len(correct) == len(options):
            raise InterviewValidationError("Toutes les propositions ne peuvent pas être de bonnes réponses.")
    elif section == "technique" or (raw_correct.strip() if isinstance(raw_correct, str) else raw_correct):
        raise InterviewValidationError("Les questions techniques doivent être des QCM.")
    points = row.get("points")
    if type(points) is not int or not 1 <= points <= 100:
        raise InterviewValidationError("Les points doivent être un entier de 1 à 100.")
    question = {
        "section": section, "profile": profile if section == "technique" else "tous",
        "topic": topic, "prompt": prompt, "options": options, "correct": correct if options else "", "points": points,
    }
    if row.get("active") is False:
        question["active"] = False
    return question


def validate_bank(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_QUESTIONS:
        raise InterviewValidationError(f"La banque doit contenir entre 1 et {MAX_QUESTIONS} questions.")
    questions, errors, seen = [], [], set()
    for index, row in enumerate(rows):
        try:
            question = _question(row)
            identity = (question["section"], question["profile"], normalized(question["prompt"]))
            if identity in seen:
                raise InterviewValidationError("Cette question figure déjà dans cette catégorie et ce profil.")
            seen.add(identity)
            questions.append(question)
        except InterviewValidationError as error:
            errors.append({"index": index, "message": str(error)})
    return questions, errors


def _topics(bank, profile, section):
    topics = defaultdict(list)
    for question in bank:
        if question.get("active", True) and question["section"] == section and question["profile"] == (profile if section == "technique" else "tous"):
            topics[normalized(question["topic"])].append(question)
    return list(topics.values())


def question_groups(bank, profile, config=None):
    """Check that each section offers enough distinct topics for the configured question count."""
    if not isinstance(profile, str) or profile not in PROFILES:
        raise InterviewValidationError("Sélectionnez le profil informatique du candidat.")
    config = normalize_config(config)
    groups = {}
    for section, item in config.items():
        topics = _topics(bank, profile, section)
        if len(topics) < item["count"]:
            raise InterviewValidationError(
                f"La banque doit contenir au moins {item['count']} thématique(s) actives pour la partie "
                f"{SECTION_LABELS[section]} et le profil {'avec' if profile == 'avec' else 'sans'} informatique."
            )
        groups[section] = topics
    return groups


def generate_questions(bank, profile, config=None):
    """Draw the configured number of topics per section, then one question variant per topic."""
    random = SystemRandom()
    config = normalize_config(config)
    selected = []
    for section, topics in question_groups(bank, profile, config).items():
        indexes = sorted(random.sample(range(len(topics)), config[section]["count"]))
        selected.extend(random.choice(topics[index]) for index in indexes)
    return [{**question, "id": str(index)} for index, question in enumerate(selected, start=1)]


def review_answers(questions, answers):
    review = {}
    for question in questions:
        key = question["id"]
        answer = answers.get(key)
        if question["options"]:
            expected = question["correct"]
            if answer is None:
                outcome = "unanswered"
            elif answer == "aucune":
                outcome = "no_answer"
            else:
                outcome = "correct" if _is_right(question, answer) else "incorrect"
            review[key] = {
                "outcome": outcome, "expected_option": expected,
                "points": None if answer is None else question["points"] if outcome == "correct" else 0,
            }
        else:
            points = answer.get("points") if isinstance(answer, dict) else None
            review[key] = {"outcome": "graded" if points is not None else "ungraded", "points": points}
    return review


def grade_answers(questions, answers, *, complete, weights=None):
    if not isinstance(answers, dict) or set(answers) - {question["id"] for question in questions}:
        raise InterviewValidationError("Les réponses ne correspondent pas au questionnaire.")
    saved = {}
    earned = defaultdict(Decimal)
    possible = defaultdict(int)
    for question in questions:
        section, key, points = question["section"], question["id"], question["points"]
        possible[section] += points
        if key not in answers:
            if complete:
                raise InterviewValidationError(f"Renseignez la réponse à la question {key}.")
            continue
        answer = answers[key]
        if question["options"]:
            value = _answer_value(question, answer)
            if value is None:
                raise InterviewValidationError(f"Réponse invalide à la question {key}.")
            saved[key] = value
            earned[section] += points if _is_right(question, value) else 0
            continue
        if not isinstance(answer, dict):
            raise InterviewValidationError(f"Note invalide à la question {key}.")
        note = answer.get("points")
        text = _text(answer.get("comment", ""), "Appréciation", 3000, required=False)
        if note is None and not complete:
            saved[key] = {"points": None, "comment": text}
            continue
        if type(note) not in {int, float} or not 0 <= note <= points:
            raise InterviewValidationError(f"La note de la question {key} doit être comprise entre 0 et {points}.")
        earned[section] += Decimal(str(note))
        saved[key] = {"points": note, "comment": text}
    if not complete:
        return saved, None
    weights = weights or {section: weight for section, (_, weight) in SECTIONS.items()}
    scores = {
        section: earned[section] * weight / possible[section] if possible[section] else Decimal(0)
        for section, weight in weights.items()
    }
    scores["global"] = sum(scores.values())
    return saved, {section: float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for section, score in scores.items()}
