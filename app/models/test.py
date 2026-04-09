from app import db
from mongoengine import Document, StringField, IntField, DateTimeField, BooleanField, DictField, ListField, EmbeddedDocument, EmbeddedDocumentField
from datetime import datetime

class Question(EmbeddedDocument):
    """Sous-document pour une question de test"""
    question = StringField(required=True)
    type = StringField(required=True, choices=['qcm_simple', 'qcm_multiple', 'texte_libre'])
    options = ListField(StringField())  # Liste des options pour les QCM
    correctAnswer = IntField()  # Index de la bonne réponse pour QCM simple
    correctAnswers = ListField(IntField())  # Indices des bonnes réponses pour QCM multiple
    score = IntField(required=True, default=5)
    image = StringField()  # URL ou base64 de l'image

class ConnectionLog(EmbeddedDocument):
    """Log de connexion d'un candidat"""
    email = StringField(required=True)
    candidateId = StringField()
    connectedAt = DateTimeField(default=datetime.utcnow)
    completedAt = DateTimeField()
    status = StringField(choices=['connected', 'in_progress', 'completed'], default='connected')

class Test(Document):
    """Modèle pour un test en ligne"""
    title = StringField(required=True)
    referentiel = StringField(required=True)
    duration = IntField(required=True)  # Durée en minutes
    scheduledDate = StringField(required=True)
    scheduledTime = StringField(required=True)
    totalQuestions = IntField(required=True)
    passingScore = IntField(required=True, default=70)
    candidatesGroup = StringField()
    description = StringField()
    questions = ListField(EmbeddedDocumentField(Question))
    status = StringField(required=True, choices=['active', 'scheduled', 'completed', 'draft'], default='active')
    
    # Logs et statistiques
    connectionLogs = ListField(EmbeddedDocumentField(ConnectionLog))
    totalConnections = IntField(default=0)
    totalCompleted = IntField(default=0)
    
    createdAt = DateTimeField(default=datetime.utcnow)
    createdBy = StringField()
    updatedAt = DateTimeField()
    updatedBy = StringField()

    meta = {
        'collection': 'tests',
        'indexes': ['referentiel', 'status', 'createdAt']
    }

    def to_dict(self):
        return {
            'id': str(self.id),
            'title': self.title,
            'referentiel': self.referentiel,
            'duration': self.duration,
            'scheduledDate': self.scheduledDate,
            'scheduledTime': self.scheduledTime,
            'totalQuestions': self.totalQuestions,
            'passingScore': self.passingScore,
            'candidatesGroup': self.candidatesGroup,
            'description': self.description,
            'questions': [
                {
                    'question': q.question,
                    'type': q.type,
                    'options': q.options,
                    'correctAnswer': q.correctAnswer,
                    'correctAnswers': q.correctAnswers,
                    'score': q.score,
                    'image': q.image
                } for q in self.questions
            ] if self.questions else [],
            'status': self.status,
            'connectionLogs': [
                {
                    'email': log.email,
                    'candidateId': log.candidateId,
                    'connectedAt': log.connectedAt.isoformat() if log.connectedAt else None,
                    'completedAt': log.completedAt.isoformat() if log.completedAt else None,
                    'status': log.status
                } for log in (self.connectionLogs or [])
            ],
            'totalConnections': self.totalConnections or 0,
            'totalCompleted': self.totalCompleted or 0,
            'createdAt': self.createdAt.isoformat() if self.createdAt else None,
            'createdBy': self.createdBy,
            'updatedAt': self.updatedAt.isoformat() if self.updatedAt else None,
            'updatedBy': self.updatedBy
        }
