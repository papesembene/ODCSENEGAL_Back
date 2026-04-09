# config.py
from dotenv import load_dotenv
import os
from datetime import timedelta

load_dotenv()

class Config:
    ELASTIC_APM = {
        'SERVICE_NAME': os.getenv('ELASTIC_APM_SERVICE_NAME'),
        'SECRET_TOKEN': os.getenv('ELASTIC_APM_SECRET_TOKEN'),
        'SERVER_URL': os.getenv('ELASTIC_APM_SERVER_URL'),
        'DEBUG': os.getenv('FLASK_ENV') != 'production'
    }


    # Configuration de base
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev_key')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt_dev_key')
    JWT_EXPIRATION_DELTA = timedelta(days=1)

    # Configuration MongoDB - Version corrigée
    MONGODB_SETTINGS = {
        "db": os.getenv('MONGO_DBNAME', 'odcdb'),
        "host": os.getenv('MONGO_URI', 'mongodb://localhost:27017/odcdb'), 
        "connect": False,  # Important pour éviter les problèmes de fork
        # Configuration du pool optimisée pour serveur dédié (15 Go RAM)
        "maxPoolSize": 300,  # Augmenté car serveur dédié avec ressources suffisantes
        "minPoolSize": 30,   # Plus de connexions maintenues pour performance
        "maxIdleTimeMS": 45000,  # Temps max avant fermeture connexion inactive
        "serverSelectionTimeoutMS": 10000,  # Timeout pour sélection serveur
        "socketTimeoutMS": 30000,  # Timeout pour opérations socket
        "connectTimeoutMS": 10000,  # Timeout pour connexion initiale
        "retryWrites": True,  # Réessayer les écritures en cas d'échec
        "w": "majority",  # Attendre confirmation majorité pour écritures
        # Options supplémentaires pour performance sur serveur dédié
        # Note: readConcern et writeConcern doivent être passés via l'URI MongoDB
        # ou configurés au niveau de la connexion, pas ici dans MongoEngine
        "readPreference": "primary"
    }

    # Autres configurations (gardez vos valeurs existantes)
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')

    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
    LINKEDIN_CLIENT_ID = os.getenv('LINKEDIN_CLIENT_ID', '')
    LINKEDIN_CLIENT_SECRET = os.getenv('LINKEDIN_CLIENT_SECRET', '')
    LINKEDIN_REDIRECT_URI = os.getenv('LINKEDIN_REDIRECT_URI','')
    
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://orangedigitalcenter.sn')
    SESSION_TYPE = 'filesystem'

    # Configuration Mail
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')


   # Dans config.py
   

    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'https://api.orangedigitalcenter.sn/api/auth/google/callback')# Ajustez selon votre environnement
    SESSION_PERMANENT = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
   # Configuration des uploads
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    ALLOWED_EXTENSIONS = {
        'image': ['png', 'jpg', 'jpeg'],
        'document': ['pdf', 'doc', 'docx', 'ppt', 'pptx']
    }
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    # Pour S3 (optionnel)
    USE_S3 = False
    AWS_ACCESS_KEY_ID = None
    AWS_SECRET_ACCESS_KEY = None
    S3_BUCKET_NAME = None
    S3_REGION = None


    # Configuration Mail
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')