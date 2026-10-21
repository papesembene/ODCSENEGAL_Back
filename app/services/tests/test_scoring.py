"""Grade candidate answers against the stored test, never against client scores."""


def calculate_test_score(questions, answers):
    earned = 0
    maximum = sum(question.score for question in questions)
    for index, question in enumerate(questions):
        answer = answers.get(str(index))
        correct = False
        if question.type == "qcm_simple":
            correct = type(answer) is int and answer == question.correctAnswer
        elif question.type == "qcm_multiple":
            expected = question.correctAnswers or []
            correct = (
                isinstance(answer, list) and all(type(item) is int for item in answer)
                and len(answer) == len(expected) and set(answer) == set(expected)
            )
        elif question.type == "texte_libre":
            # Preserve the current provisional credit rule; staff can grade later.
            correct = isinstance(answer, str) and bool(answer.strip())
        if correct:
            earned += question.score
    return int(earned * 100 / maximum + 0.5) if maximum > 0 else 0
