# odcdeploye\backend\app\__init__.py
 
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mongoengine import MongoEngine
from flask_mail import Mail
from flask_session import Session
from app.services.email_service import EmailService
import os
from dotenv import load_dotenv
from flask.json.provider import DefaultJSONProvider
from app.utils.error_handlers import register_error_handlers
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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
 
def create_app(config_class=Config):
    load_dotenv()
 
    app = Flask(__name__)
   
    app.config.from_object(config_class)
    if hasattr(config_class, "validate"):
        config_class.validate()
    app.json = CustomJSONProvider(app)
 
    # Configuration des sessions
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = (
        app.config.get("ENVIRONMENT") == "production"
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True
 
    # Configuration JWT
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
                "origins": app.config.get("CORS_ALLOWED_ORIGINS", []),
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
    mail.init_app(app)
    email_service.init_app(app)
   
    if app.config.get("RUN_INDEX_MAINTENANCE"):
        with app.app_context():
            from app.utils.fix_indexes import fix_problematic_indexes

            fix_problematic_indexes()
 
    # Enregistrement des blueprints
    from app.routes.auth_routes import auth_bp
    from app.routes.candidature_startup_routes import startup_bp
 
    from app.routes.admin_routes import admin_bp
    from app.routes.admin_event import admin_event_bp
    from app.routes.contact_route import contact_bp
    from app.routes.competence_routes import competence_bp
    from app.routes.job_offer_routes import job_offer_bp
    from app.routes.startup_school_routes import startup_school_bp
    from app.routes.candidature_routes import candidature_bp, candidature_public_bp
    from app.routes.resource_request_routes import resource_bp
    from app.routes.event_routes import events
    from app.routes.orangefab_routes import orangefab_bp
    from app.routes.test_violation_routes import test_violation_bp
    from app.routes.interview_routes import interview_bp, interview_public_bp
    from app.routes.portal_content_routes import portal_content_bp
   
    from app.routes.test_routes import test_bp
    from app.routes.test_group_routes import test_group_bp
 
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(startup_bp, url_prefix="/api/startup")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_event_bp, url_prefix="/api/admin")
    app.register_blueprint(contact_bp, url_prefix="/api/contact")
    app.register_blueprint(competence_bp, url_prefix='/api/competences')
    app.register_blueprint(job_offer_bp, url_prefix='/api/job-offers')
    app.register_blueprint(
        startup_school_bp,
        url_prefix="/api/startup-school",
    )
    app.register_blueprint(resource_bp, url_prefix='/api/resources')
    app.register_blueprint(events, url_prefix='/api/events')
    app.register_blueprint(orangefab_bp, url_prefix='/api/orangefab')
    app.register_blueprint(test_violation_bp, url_prefix='/api/admin')
    app.register_blueprint(interview_bp, url_prefix='/api/admin')
    app.register_blueprint(interview_public_bp, url_prefix='/api/interviews')
    app.register_blueprint(portal_content_bp, url_prefix='/api')
   
    app.register_blueprint(test_bp, url_prefix='/api/admin')
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
