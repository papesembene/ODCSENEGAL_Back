from app import db
from mongoengine import Document, StringField, BooleanField, DateField, DateTimeField
from datetime import datetime

class Candidature(Document):
    first_name = StringField(required=True)
    last_name = StringField(required=True)
    email = StringField(required=True, unique=True)
    phone = StringField(required=True)
    date_of_birth = DateField(required=True)
    place_of_birth = StringField(required=True)
    gender = StringField(required=True)
    cni_or_passport_number = StringField(required=True, unique=True)
    nationality = StringField(required=True)
    region_of_residence = StringField(required=True)  # Région de résidence
    current_structure = StringField()         # Structure actuelle
    education_level = StringField()           # Niveau d'étude
    computer_skills = BooleanField(required=True)  # Notions en informatique (Oui/Non)
    available_for_10_months = BooleanField(required=True)  # Disponibilité pour 10 mois (Oui/Non)
    desired_training = StringField(required=True)  # Formation souhaitée
    accept_conditions = BooleanField(required=True)  # Acceptation des conditions
    speciality = StringField()
    is_working = BooleanField(default=False)
    contract_type = StringField()
    
    # Statut de la candidature
    status = StringField(
        default='pending',
        choices=['pending', 'accepted', 'rejected', 'interviewed'],
        help_text="Statut de la candidature: pending (en attente), accepted (acceptée), rejected (refusée), interviewed (entretien)"
    )

    created_at = DateTimeField(default=datetime.utcnow)

    

    meta = {
        'indexes': ['email']  # Indexer l'email pour des recherches rapides
    }

    def to_dict(self):
        return {
            'id': str(self.id),
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'place_of_birth': self.place_of_birth,
            'gender': self.gender,
            'cni_or_passport_number': self.cni_or_passport_number,
            'nationality': self.nationality,
            'region_of_residence': self.region_of_residence,
            'current_structure': self.current_structure,
            'education_level': self.education_level,
            'computer_skills': self.computer_skills,
            'available_for_10_months': self.available_for_10_months,
            'desired_training': self.desired_training,
            'accept_conditions': self.accept_conditions,
            'speciality': self.speciality,
            'is_working': self.is_working,
            'contract_type': self.contract_type,
            'status': self.status if hasattr(self, 'status') else 'pending',
            'application_date': self.created_at.isoformat() if hasattr(self, 'created_at') else None
        }
