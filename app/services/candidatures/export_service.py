"""Stream all filtered candidates without materializing the export in memory."""

import csv
from io import StringIO

from app.repositories.candidature_filters import candidate_filter
from app.repositories.candidature_read_repository import CandidatureReadRepository


EXPORT_COLUMNS = (
    ("first_name", "Prenom"), ("last_name", "Nom"), ("email", "Email"),
    ("phone", "Telephone"), ("gender", "Genre"), ("desired_training", "Formation"),
    ("status", "Statut"), ("application_date", "Date de candidature"),
    ("date_of_birth", "Date de naissance"), ("place_of_birth", "Lieu de naissance"),
    ("nationality", "Nationalite"), ("region_of_residence", "Region"),
    ("education_level", "Niveau d'etude"), ("current_structure", "Structure actuelle"),
    ("cni_or_passport_number", "CNI / Passeport"), ("computer_skills", "Notions informatiques"),
    ("available_for_10_months", "Disponible 10 mois"), ("accept_conditions", "Conditions acceptees"),
    ("speciality", "Specialite"), ("is_working", "En activite"), ("contract_type", "Contrat"),
)


def export_candidates(filters):
    candidate_filter(filters)  # Validate before Flask starts the streamed response.
    repository = CandidatureReadRepository()

    def stream():
        output = StringIO(newline="")
        writer = csv.writer(output)
        yield "\ufeff"
        writer.writerow([title for _, title in EXPORT_COLUMNS])
        yield output.getvalue()
        for row in repository.export_rows(filters):
            output.seek(0)
            output.truncate(0)
            cells = []
            for field, _ in EXPORT_COLUMNS:
                value = row.get(field)
                text = "" if value is None else str(value)
                cells.append("'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text)
            writer.writerow(cells)
            yield output.getvalue()
    return stream()
