# odcdeploye\backend\app\__init__.py
 
from flask import Flask, send_from_directory, current_app
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mongoengine import MongoEngine
from flask_mail import Mail
from flask_session import Session
from datetime import timedelta
from app.services.email_service import EmailService
import os
from dotenv import load_dotenv
from flask.json.provider import DefaultJSONProvider
from app.utils.error_handlers import register_error_handlers
from werkzeug.utils import secure_filename
from uuid import uuid4
from app.config import Config
 
# Initialisation des extensions
db = MongoEngine()
jwt = JWTManager()
mail = Mail()
email_service = EmailService()
session = Session()
 
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)
 
# Fonction globale pour la sécurité Clickjacking
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
    return response
 
def create_app(config_class=Config):
    load_dotenv()
 
    app = Flask(__name__)
   
    app.config.from_object(config_class)
    app.json = CustomJSONProvider(app)
 
    # Configuration des sessions
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key')
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
 
    # Configuration JWT
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'dev_key')
    app.config['JWT_IDENTITY_CLAIM'] = 'sub'
   
    # Configuration des uploads
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
    app.config['ALLOWED_EXTENSIONS'] = {'document': ['pdf', 'doc', 'docx', 'pptx']}
    app.config['MAX_FILE_SIZE'] = 10 * 1024 * 1024  # 10MB
 
    # CORS Configuration
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    "https://odcdeploye-ee2i.vercel.app",
                    "http://localhost:3000",
                    "https://localhost:3000",
                    "http://localhost:3001",
                    "https://orangedigitalcenter.sn"
                ],
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"],
                "supports_credentials": True
            }
        },
        supports_credentials=True
    )
 
    # Initialisation des extensions
    db.init_app(app)
    jwt.init_app(app)
    session.init_app(app)
   
    # Correction automatique des index MongoDB problématiques au démarrage
    with app.app_context():
        try:
            from app.utils.fix_indexes import fix_problematic_indexes
            fix_problematic_indexes()
        except Exception as e:
            # Ne pas bloquer le démarrage si la correction échoue
            print(f"⚠️  Impossible de corriger les index MongoDB: {str(e)}")
            pass
 
    # Enregistrement des blueprints
    from app.routes.auth_routes import auth_bp
    #from app.routes.startup_routes import startup_bp
    from app.routes.candidature_startup_routes import startup_bp
 
    from app.routes.connect_routes import connect_bp
    from app.routes.admin_routes import admin_bp
    from app.routes.contact_route import contact_bp
    from app.routes.competence_routes import competence_bp
    from app.routes.job_offer_routes import job_offer_bp
    from app.routes.candidature_routes import candidature_bp, candidature_public_bp
    from app.routes.resource_request_routes import resource_bp
    from app.routes.event_routes import events
    from app.routes.orangefab_routes import orangefab_bp
    from app.routes.test_violation_routes import test_violation_bp
   
    # Importer les routes de tests avec gestion d'erreur
    try:
        from app.routes.test_routes import test_bp
        from app.routes.test_group_routes import test_group_bp
    except ImportError as e:
        print(f"⚠️  Attention: Les routes de tests ne peuvent pas être chargées: {str(e)}")
        print(f"   Le backend continuera de fonctionner, mais les fonctionnalités de tests seront indisponibles.")
        test_bp = None
        test_group_bp = None
 
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(startup_bp, url_prefix="/api/startup")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(contact_bp, url_prefix="/api/contact")
    app.register_blueprint(competence_bp, url_prefix='/api/competences')
    app.register_blueprint(job_offer_bp, url_prefix='/api/job-offers')
    app.register_blueprint(resource_bp, url_prefix='/api/resources')
    app.register_blueprint(events, url_prefix='/api/events')
    app.register_blueprint(orangefab_bp, url_prefix='/api/orangefab')
    app.register_blueprint(test_violation_bp, url_prefix='/api/admin')
   
    # Enregistrer les blueprints de tests uniquement s'ils ont été importés avec succès
    if test_bp is not None:
        app.register_blueprint(test_bp, url_prefix='/api/admin')
    if test_group_bp is not None:
        app.register_blueprint(test_group_bp, url_prefix='/api/admin')
   
    app.register_blueprint(candidature_public_bp, url_prefix='/api/candidature')
    app.register_blueprint(candidature_bp, url_prefix='/api/admin')
   
    register_error_handlers(app)
 
    @app.route('/')
    def index():
        return {"message": "Bienvenue sur l'API ODC Backend"}
 
    # Créer le dossier uploads au démarrage
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
 
    # Sécurité Clickjacking : Interdiction d'affichage en iframe
    app.after_request(add_security_headers)
 
    return app