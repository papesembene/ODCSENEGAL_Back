from flask_mongoengine import MongoEngine
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.services.file_service import FileService
db = MongoEngine()



class FileField(db.EmbeddedDocument):
    filename = db.StringField(required=True)
    path = db.StringField(required=True)  # Chemin relatif du fichier
    content_type = db.StringField()
    size = db.IntField()
    uploaded_at = db.DateTimeField(default=datetime.utcnow)

    def get_url(self):
        return FileService.get_file_url(self.path)
    
    def to_json(self):
        return {
            "filename": self.filename,
            "url": self.get_url(),
            "content_type": self.content_type,
            "size": self.size,
            "uploaded_at": self.uploaded_at.isoformat()
        }

class StudentProfile(db.EmbeddedDocument):
    institution = db.StringField(required=True)
    education_level = db.StringField(required=True)
    sector = db.StringField(required=True)
    motivations = db.StringField()
    interests = db.StringField()
    cv_file = db.EmbeddedDocumentField(FileField)
    cover_letter_file = db.EmbeddedDocumentField(FileField)

    def to_json(self):
        return {
            "institution": self.institution,
            "education_level": self.education_level,
            "sector": self.sector,
            "motivations": self.motivations,
            "interests": self.interests,
            "cv_file": self.cv_file.to_json() if self.cv_file else None,
            "cover_letter_file": self.cover_letter_file.to_json() if self.cover_letter_file else None
        }

class StartupProfile(db.EmbeddedDocument):
    company_name = db.StringField(required=True)
    company_sector = db.StringField(required=True)
    location = db.StringField(required=True)
    value_proposition = db.StringField(required=True)
    maturity_stage = db.StringField(required=True)
    founding_team = db.StringField()
    needs = db.StringField()
    logo_file = db.EmbeddedDocumentField(FileField)
    pitch_deck_file = db.EmbeddedDocumentField(FileField)
    business_plan_file = db.EmbeddedDocumentField(FileField)

    def to_json(self):
        return {
            "company_name": self.company_name,
            "company_sector": self.company_sector,
            "location": self.location,
            "value_proposition": self.value_proposition,
            "maturity_stage": self.maturity_stage,
            "founding_team": self.founding_team,
            "needs": self.needs,
            "logo_file": self.logo_file.to_json() if self.logo_file else None,
            "pitch_deck_file": self.pitch_deck_file.to_json() if self.pitch_deck_file else None,
            "business_plan_file": self.business_plan_file.to_json() if self.business_plan_file else None
        }

class CorporateInvestorProfile(db.EmbeddedDocument):
    organization_name = db.StringField(required=True)
    activities = db.StringField(required=True)
    interest_sectors = db.StringField(required=True)
    cooperation_objectives = db.StringField()
    brochure_file = db.EmbeddedDocumentField(FileField)

    def to_json(self):
        return {
            "organization_name": self.organization_name,
            "activities": self.activities,
            "interest_sectors": self.interest_sectors,
            "cooperation_objectives": self.cooperation_objectives,
            "brochure_file": self.brochure_file.to_json() if self.brochure_file else None
        }

class User(db.Document):
    # Champs d'authentification

    email = db.EmailField(required=True, unique=True)
    password_hash = db.StringField(required=True)  # Champ requis pour l'authentification email
    first_name = db.StringField()
    last_name = db.StringField()
    
    # Timestamps
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_login = db.DateTimeField()
    
    # Statut
    is_active = db.BooleanField(default=True)
    email_verified = db.BooleanField(default=False)
    
    # Admin fields
    is_admin = db.BooleanField(default=False)
    admin_type = db.StringField(choices=['competences', 'startups', 'super_admin'])  # Type d'administrateur
    
    # OAuth fields
    oauth_provider = db.StringField()  # 'google', 'linkedin', etc.
    oauth_id = db.StringField()        # ID from OAuth provider
    oauth_data = db.DictField()       # Additional OAuth data
    
    # Profile fields

    profile_type = db.StringField(required=True, choices=['student', 'startup', 'corporate', 'investor'])

    profile_data = db.DictField()

    profile_picture = db.StringField()
    
    # Profile-specific data
    student_profile = db.EmbeddedDocumentField(StudentProfile)
    startup_profile = db.EmbeddedDocumentField(StartupProfile)
    corporate_investor_profile = db.EmbeddedDocumentField(CorporateInvestorProfile)
    
    meta = {
        'collection': 'users',
        'indexes': [
            'email',
            'oauth_id',
            'profile_type'
        ]
    }

    def set_password(self, password):
        """Hash et stocke le mot de passe"""
        self.password_hash = generate_password_hash(password)
        self.save()  # Sauvegarde automatique
        
    def check_password(self, password):
        """Vérifie le mot de passe"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def to_json(self):
        """Serialise l'utilisateur pour les réponses API"""
        return {
            "id": str(self.id),
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "profile_picture": self.profile_picture,
            "oauth_provider": self.oauth_provider,
            "profile_type": self.profile_type,
            "created_at": self.created_at.isoformat() if self.created_at else None

        }
