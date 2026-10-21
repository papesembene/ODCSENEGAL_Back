# config.py
from dotenv import load_dotenv
import os
from datetime import timedelta
from app.runtime_config import env_int
from urllib.parse import urlsplit

load_dotenv()

class Config:
    ENVIRONMENT = os.getenv("FLASK_ENV", "development")
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
        # Budget per process: multiply by API replicas and background workers.
        "maxPoolSize": env_int("MONGO_MAX_POOL_SIZE", 50, maximum=1000),
        "minPoolSize": env_int("MONGO_MIN_POOL_SIZE", 0, minimum=0, maximum=1000),
        "maxIdleTimeMS": 45000,  # Temps max avant fermeture connexion inactive
        "serverSelectionTimeoutMS": env_int("MONGO_SELECTION_TIMEOUT_MS", 5000),
        "socketTimeoutMS": env_int("MONGO_SOCKET_TIMEOUT_MS", 30000),
        "connectTimeoutMS": env_int("MONGO_CONNECT_TIMEOUT_MS", 5000),
        "waitQueueTimeoutMS": env_int("MONGO_WAIT_QUEUE_TIMEOUT_MS", 5000),
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
    LINKEDIN_REDIRECT_URI = os.getenv(
        "LINKEDIN_REDIRECT_URI",
        "http://localhost:5000/api/auth/linkedin/callback",
    )
    
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://orangedigitalcenter.sn')
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            ",".join(
                [
                    os.getenv('FRONTEND_URL', 'https://orangedigitalcenter.sn'),
                    "http://localhost:3000",
                    "https://localhost:3000",
                    "http://localhost:3001",
                ]
            ),
        ).split(",")
        if origin.strip()
    ]
    SESSION_TYPE = os.getenv("SESSION_TYPE", "filesystem")

    # Configuration Mail
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')

    RUN_INDEX_MAINTENANCE = (
        os.getenv("RUN_INDEX_MAINTENANCE", "false").lower() == "true"
    )


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


    @classmethod
    def validate(cls):
        if cls.MONGODB_SETTINGS["minPoolSize"] > cls.MONGODB_SETTINGS["maxPoolSize"]:
            raise RuntimeError("MONGO_MIN_POOL_SIZE depasse MONGO_MAX_POOL_SIZE")
        if cls.SESSION_TYPE == "redis" and not os.getenv("REDIS_URL"):
            raise RuntimeError("REDIS_URL requis pour les sessions partagees")
        if cls.SESSION_TYPE not in {"redis", "filesystem"}:
            raise RuntimeError("SESSION_TYPE invalide")
        if os.getenv("EMAIL_PROVIDER", "auto") not in {"auto", "brevo", "brevo_smtp", "sendgrid", "smtp"}:
            raise RuntimeError("EMAIL_PROVIDER invalide")
        if os.getenv("EMAIL_DELIVERY_MODE", "sync") not in {"sync", "queued"}:
            raise RuntimeError("EMAIL_DELIVERY_MODE invalide")
        if cls.MAIL_USE_TLS and cls.MAIL_USE_SSL:
            raise RuntimeError("MAIL_USE_TLS et MAIL_USE_SSL sont incompatibles")
        if cls.ENVIRONMENT != "production":
            return
        weak_values = {"", "dev_key", "jwt_dev_key"}
        missing = []
        if cls.SECRET_KEY in weak_values:
            missing.append("SECRET_KEY")
        if cls.JWT_SECRET_KEY in weak_values:
            missing.append("JWT_SECRET_KEY")
        if not os.getenv("MONGO_URI"):
            missing.append("MONGO_URI")
        if not os.getenv("MONGO_DBNAME"):
            missing.append("MONGO_DBNAME")
        if len(cls.SECRET_KEY) < 32 or len(cls.JWT_SECRET_KEY) < 32:
            missing.append("cles SECRET_KEY/JWT_SECRET_KEY d'au moins 32 caracteres")
        if os.getenv("RUN_PREPROD_SEED", "false").lower() == "true":
            missing.append("RUN_PREPROD_SEED doit rester false en production")
        if urlsplit(cls.FRONTEND_URL).scheme != "https" or not os.getenv("CORS_ALLOWED_ORIGINS"):
            missing.append("FRONTEND_URL HTTPS et CORS_ALLOWED_ORIGINS explicites")
        if any(urlsplit(origin).scheme != "https" or not urlsplit(origin).hostname or "*" in origin
               for origin in cls.CORS_ALLOWED_ORIGINS):
            missing.append("CORS: utiliser uniquement des origines HTTPS precises")
        database_in_uri = urlsplit(cls.MONGODB_SETTINGS["host"]).path.strip("/")
        if database_in_uri and database_in_uri != cls.MONGODB_SETTINGS["db"]:
            missing.append("MONGO_URI et MONGO_DBNAME ne ciblent pas la meme base")
        if env_int("APP_INSTANCES", 1, maximum=100) > 1 and cls.SESSION_TYPE != "redis":
            missing.append("SESSION_TYPE=redis requis pour plusieurs instances")
        if missing:
            raise RuntimeError(
                "Configuration de production invalide: "
                + ", ".join(missing)
            )
