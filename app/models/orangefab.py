from mongoengine import Document, StringField, DateTimeField, BooleanField
from datetime import datetime

class OrangeFab(Document):
    # Informations personnelles
    firstName = StringField(required=True)
    lastName = StringField(required=True)
    role = StringField(required=True)  # Changé de function à role
    otherRole = StringField()  # Changé de otherFunction à otherRole
    email = StringField(required=True)
    emailAlternate = StringField()
    phone = StringField(required=True)
    phoneCountry = StringField(required=True, default="+221")  # NOUVEAU - Indicatif pays
    fullPhone = StringField(required=True)  # NOUVEAU - Téléphone complet avec indicatif
    region = StringField(required=True)
    department = StringField(required=True)
    diploma = StringField(required=True)
    otherDiploma = StringField()
    institution = StringField()  # Plus obligatoire
    cv = StringField(required=True)
    pitch_deck = StringField(required=True)
    
    # Informations entreprise
    companyName = StringField(required=True)
    website = StringField()
    ninea = StringField(required=True)  # Maintenant obligatoire
    creationDate = StringField(required=True)
    capital = StringField()
    capitalCurrency = StringField(default="F CFA")
    legalForm = StringField(required=True)
    otherLegalForm = StringField()
    sector = StringField(required=True)
    otherSector = StringField()
    businessModel = StringField(required=True)
    address = StringField()
    revenue = StringField()
    revenueCurrency = StringField(default="F CFA")
    employees = StringField(required=True)
    raisedFunds = StringField(required=True)
    raisedAmount = StringField()  # NOUVEAU - Montant levé
    raisedCurrency = StringField(default="F CFA")  # NOUVEAU - Devise du montant levé
    clients = StringField()
    pitch_deck = StringField(required=True)
    
    # Informations produit/service
    productName = StringField(required=True)
    productDescription = StringField(required=True)
    activityDescription = StringField(required=True)

    hasWorkingProduct = StringField(required=True)
    acceptTerms = BooleanField(required=True)
    
    # Métadonnées
    createdAt = DateTimeField(default=datetime.utcnow)
    
    @classmethod
    def check_email_exists(cls, email):
        """Vérifier si un email existe déjà"""
        return cls.objects(email=email).count() > 0
    
    @classmethod
    def check_phone_exists(cls, phone):
        """Vérifier si un numéro de téléphone existe déjà"""
        return cls.objects(fullPhone=phone).count() > 0
