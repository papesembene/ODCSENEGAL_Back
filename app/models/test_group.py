from app import db
from mongoengine import Document, StringField, DateTimeField, ListField, ReferenceField, IntField
from datetime import datetime

class TestGroup(Document):
    # Informations du groupe
    name = StringField(required=True)  # Ex: "Groupe Dev Web - Session 1"
    formation = StringField(required=True)  # Formation concernée (Dev Web, Data, etc.)
    test_id = StringField()  # ID du test associé (optionnel au début)
    
    # Date et heure du test
    test_date = DateTimeField(required=True)  # Date et heure du test
    duration = IntField(default=60)  # Durée en minutes
    
    # Candidats du groupe
    candidate_ids = ListField(StringField())  # Liste des IDs des candidats
    
    # Informations de passage
    location = StringField()  # Lieu du test (si présentiel)
    instructions = StringField()  # Instructions particulières
    
    # Statut
    status = StringField(default='pending', choices=['pending', 'scheduled', 'completed', 'cancelled'])
    email_sent = DateTimeField()  # Date d'envoi de l'email d'invitation
    
    # Métadonnées
    created_by = StringField()  # Email de l'admin qui a créé le groupe
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'test_groups',
        'indexes': ['formation', 'test_date', 'status', 'created_at']
    }
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'name': self.name,
            'formation': self.formation,
            'test_id': self.test_id,
            'test_date': self.test_date.isoformat() if self.test_date else None,
            'duration': self.duration,
            'candidate_ids': self.candidate_ids,
            'candidate_count': len(self.candidate_ids) if self.candidate_ids else 0,
            'location': self.location,
            'instructions': self.instructions,
            'status': self.status,
            'email_sent': self.email_sent.isoformat() if self.email_sent else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
