from app import db
from mongoengine import Document, StringField, DateTimeField, DictField, IntField, ListField, EmbeddedDocument, EmbeddedDocumentField
from datetime import datetime
 
class Violation(EmbeddedDocument):
    """Document embarqué pour chaque violation individuelle"""
    violationType = StringField(required=True)  # copy, paste, tab_switch, devtools, etc.
    message = StringField(required=True)
    timestamp = DateTimeField(default=datetime.utcnow)
    elapsedTime = IntField()  # Temps écoulé depuis le début du test (en ms)
   
    def to_dict(self):
        return {
            'violationType': self.violationType,
            'message': self.message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'elapsedTime': self.elapsedTime
        }
 
class TestViolation(Document):
    """Modèle optimisé pour enregistrer toutes les violations d'un candidat pour un test"""
    testId = StringField(required=True)
    testResultId = StringField()  # ID du résultat de test associé (si disponible)
    candidateEmail = StringField(required=True)
   
    # Tableau de toutes les violations
    violations = ListField(EmbeddedDocumentField(Violation), default=list)
   
    # Statistiques agrégées
    stats = DictField(default=dict)  # {copy: 5, paste: 3, tab_switch: 10, ...}
   
    # Métadonnées
    firstViolationAt = DateTimeField()
    lastViolationAt = DateTimeField()
    totalViolations = IntField(default=0)
    metadata = DictField()  # Informations supplémentaires (user agent, etc.)
   
    # Dates de création et mise à jour
    createdAt = DateTimeField(default=datetime.utcnow)
    updatedAt = DateTimeField(default=datetime.utcnow)
   
    meta = {
        'collection': 'test_violations',
        'indexes': [
            {'fields': ['testId', 'candidateEmail'], 'unique': True},  # Un seul document par test/candidat
            'testId',
            'candidateEmail',
            'totalViolations',
            'createdAt'
        ]
    }
   
    def add_violation(self, violation_type, message, elapsed_time=None):
        """Ajoute une nouvelle violation au document"""
        violation = Violation(
            violationType=violation_type,
            message=message,
            timestamp=datetime.utcnow(),
            elapsedTime=elapsed_time
        )
       
        self.violations.append(violation)
        self.totalViolations = len(self.violations)
       
        # Mettre à jour les statistiques
        if not self.stats:
            self.stats = {}
        self.stats[violation_type] = self.stats.get(violation_type, 0) + 1
       
        # Mettre à jour les timestamps
        now = datetime.utcnow()
        if not self.firstViolationAt:
            self.firstViolationAt = now
        self.lastViolationAt = now
        self.updatedAt = now
       
        return violation
   
    def to_dict(self):
        return {
            'id': str(self.id),
            'testId': self.testId,
            'testResultId': self.testResultId,
            'candidateEmail': self.candidateEmail,
            'violations': [v.to_dict() for v in self.violations],
            'stats': self.stats,
            'firstViolationAt': self.firstViolationAt.isoformat() if self.firstViolationAt else None,
            'lastViolationAt': self.lastViolationAt.isoformat() if self.lastViolationAt else None,
            'totalViolations': self.totalViolations,
            'metadata': self.metadata,
            'createdAt': self.createdAt.isoformat() if self.createdAt else None,
            'updatedAt': self.updatedAt.isoformat() if self.updatedAt else None
        }
 
 