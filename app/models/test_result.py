from app import db
from mongoengine import Document, StringField, IntField, DateTimeField, DictField, ListField, EmbeddedDocument, EmbeddedDocumentField
from datetime import datetime

class Candidate(EmbeddedDocument):
    """Informations du candidat"""
    name = StringField(required=True)
    email = StringField(required=True)
    phone = StringField(required=True)

class TestResult(Document):
    """Modèle pour les résultats d'un test"""
    testId = StringField(required=True)
    testTitle = StringField(required=True)
    referentiel = StringField(required=True)
    candidate = EmbeddedDocumentField(Candidate, required=True)
    answers = DictField()  # {questionIndex: answer}
    score = IntField(required=True)
    status = StringField(required=True, choices=['admis', 'rejeté', 'pending'], default='pending')
    completedAt = DateTimeField(default=datetime.utcnow)
    submittedDate = StringField()
    submittedTime = StringField()
    manualGrades = DictField()  # Notes manuelles pour les questions de texte libre

    meta = {
        'collection': 'test_results',
        'indexes': [
            # Index unique composé pour éviter les doublons (CRITIQUE pour 42k candidats)
            {'fields': ('testId', 'candidate.email'), 'unique': True, 'sparse': False},
            # Index simples pour les requêtes
            'testId',
            'candidate.email',
            'referentiel',
            'status',
            'completedAt'
        ]
    }

    def to_dict(self):
        return {
            'id': str(self.id),
            'testId': self.testId,
            'testTitle': self.testTitle,
            'referentiel': self.referentiel,
            'candidate': {
                'name': self.candidate.name,
                'email': self.candidate.email,
                'phone': self.candidate.phone
            } if self.candidate else None,
            'answers': self.answers,
            'score': self.score,
            'status': self.status,
            'completedAt': self.completedAt.isoformat() if self.completedAt else None,
            'submittedDate': self.submittedDate,
            'submittedTime': self.submittedTime,
            'manualGrades': self.manualGrades
        }
