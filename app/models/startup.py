from mongoengine import Document, StringField, DateTimeField, BooleanField
from datetime import datetime

class Startup(Document):
    # Informations personnelles
    firstName = StringField(required=True)
    lastName = StringField(required=True)
    role = StringField(required=True)
    otherRole = StringField()
    email = StringField(required=True)
    founder_email = StringField(required=True, unique=True)  # Ajouter ce champ pour la compatibilité avec l'index existant
    emailAlternate = StringField()
    phone = StringField(required=True)
    phoneCountry = StringField(required=True, default="+221")
    fullPhone = StringField(required=True)  # Téléphone complet avec indicatif
    region = StringField(required=True)
    department = StringField(required=True)
    diploma = StringField(required=True)
    otherDiploma = StringField()
    institution = StringField()
    cv = StringField(required=True)
    
    # Informations entreprise
    startup_name = StringField(required=True, unique=True)  # Garder le nom original du champ pour compatibilité avec l'index existant
    companyName = StringField(required=True)  # Champ pour stocker la valeur du frontend
    website = StringField()
    ninea = StringField(required=True)
    sector = StringField(required=True)
    otherSector = StringField()
    businessModel = StringField(required=True)
    creationDate = StringField(required=True)
    legalForm = StringField(required=True)
    otherLegalForm = StringField()
    capital = StringField()
    capitalCurrency = StringField(default="F CFA")
    employees = StringField(required=True)
    address = StringField()
    revenue = StringField()
    revenueCurrency = StringField(default="F CFA")
    raisedFunds = StringField(required=True)
    raisedAmount = StringField()
    raisedCurrency = StringField(default="F CFA")
    clients = StringField()
    pitchDeck = StringField(required=True)
    
    # Informations produit/service
    productName = StringField(required=True)
    productDescription = StringField(required=True)
    activityDescription = StringField(required=True)
    hasWorkingProduct = StringField(required=True)
    
    # Programme et acceptation
    program = StringField(default="startup_lab")
    acceptTerms = BooleanField(required=True)
    
    # Métadonnées
    createdAt = DateTimeField(default=datetime.utcnow)

    meta = {
        'strict': False  # Ignorer les champs supplémentaires présents en base mais non définis ici
    }
    
    @classmethod
    def check_email_exists(cls, email):
        """Vérifier si un email existe déjà"""
        return cls.objects(email=email).count() > 0
    
    @classmethod
    def check_phone_exists(cls, phone):
        """Vérifier si un numéro de téléphone existe déjà"""
        return cls.objects(fullPhone=phone).count() > 0
    
    def to_dict(self):
        """Convertir en dictionnaire pour l'API"""
        return {
            "id": str(self.id),
            "startup_name": self.startup_name,
            "firstName": self.firstName,
            "lastName": self.lastName,
            "role": self.role,
            "otherRole": self.otherRole,
            "email": self.email,
            "founder_email": self.founder_email,  # Ajouter cette ligne
            "emailAlternate": self.emailAlternate,
            "phone": self.phone,
            "phoneCountry": self.phoneCountry,
            "fullPhone": self.fullPhone,
            "region": self.region,
            "department": self.department,
            "diploma": self.diploma,
            "otherDiploma": self.otherDiploma,
            "institution": self.institution,
            "cv": self.cv,
            "companyName": self.companyName,
            "website": self.website,
            "ninea": self.ninea,
            "sector": self.sector,
            "otherSector": self.otherSector,
            "businessModel": self.businessModel,
            "creationDate": self.creationDate,
            "legalForm": self.legalForm,
            "otherLegalForm": self.otherLegalForm,
            "capital": self.capital,
            "capitalCurrency": self.capitalCurrency,
            "employees": self.employees,
            "address": self.address,
            "revenue": self.revenue,
            "revenueCurrency": self.revenueCurrency,
            "raisedFunds": self.raisedFunds,
            "raisedAmount": self.raisedAmount,
            "raisedCurrency": self.raisedCurrency,
            "clients": self.clients,
            "pitchDeck": self.pitchDeck,
            "productName": self.productName,
            "productDescription": self.productDescription,
            "activityDescription": self.activityDescription,
            "hasWorkingProduct": self.hasWorkingProduct,
            "program": self.program,
            "acceptTerms": self.acceptTerms,
            "createdAt": self.createdAt,
        }
