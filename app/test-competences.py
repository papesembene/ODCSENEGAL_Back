from app.models.competence import Competence  # ton modèle
from app import app  # si nécessaire pour l'init de MongoEngine

with app.app_context():
    candidatures = Competence.objects()
    print(f"Nombre de candidatures : {candidatures.count()}")
    for c in candidatures:
        print(c.to_mongo())  # affiche le document brut
