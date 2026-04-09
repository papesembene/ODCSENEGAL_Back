from flask import Blueprint, request, jsonify, redirect, url_for, current_app, session
from werkzeug.exceptions import BadRequest, Unauthorized, InternalServerError
from app.services.auth_service import AuthService
from app.services.oauth_service import GoogleOAuthService, LinkedInOAuthService
from app.models.user import User, StudentProfile, StartupProfile, CorporateInvestorProfile, FileField
from flask_jwt_extended import jwt_required
from app.services.file_service import FileService
import os
from datetime import datetime
from uuid import uuid4
from flask import send_from_directory
import json
import jwt
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'uploads'  # Assure-toi que ce dossier existe
os.makedirs(UPLOAD_FOLDER, exist_ok=True)



auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def save_uploaded_file(file, upload_folder):
    if not file:
        return None
    
    # Créer le dossier s'il n'existe pas
    os.makedirs(upload_folder, exist_ok=True)
    
    # Générer un nom de fichier unique
    filename = f"{datetime.now().timestamp()}_{file.filename}"
    filepath = os.path.join(upload_folder, filename)
    
    # Sauvegarder le fichier
    file.save(filepath)
    
    return {
        'filename': filename,
        'url': f"/uploads/{filename}",  # À adapter selon votre configuration
        'content_type': file.content_type,
        'size': os.path.getsize(filepath)
    }

@auth_bp.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 200  # Réponse vide = préflight validé
    data = request.get_json()
    
    if not data:
        raise BadRequest("Données manquantes")
    
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        raise BadRequest("Email et mot de passe requis")
    
    result = AuthService.login_with_email(email, password)
    return jsonify(result)

@auth_bp.route('/register', methods=['POST'])
def register():
    # Initialiser les variables de données et fichiers
    if request.is_json:
        data = request.get_json()
        files = {}  # Pas de fichiers pour les requêtes JSON
    else:
        data = request.form.to_dict()
        files = request.files  # Récupérer les fichiers pour form-data

    if not data:
        raise BadRequest("Données manquantes")

    # Validation des champs requis
    required_fields = ['email', 'password', 'profileType']
    if not all(field in data for field in required_fields):
        raise BadRequest("Email, mot de passe et type de profil requis")

    email = data['email']
    password = data['password']
    profile_type = data['profileType']

    # Vérifier si l'utilisateur existe déjà
    if User.objects(email=email).first():
        raise BadRequest("Un utilisateur avec cet email existe déjà")

    # Créer un nouvel utilisateur
    user = User(
        email=email,
        profile_type=profile_type,
        first_name=data.get('firstName', ''),
        last_name=data.get('lastName', ''),
        is_active=True
    )
    user.set_password(password)

    # Configurer le dossier d'upload
    upload_folder = os.path.join(current_app.root_path, 'static/uploads')
    os.makedirs(upload_folder, exist_ok=True)

    # Fonction pour sauvegarder les fichiers
    def save_file(file, subfolder=''):
        if not file or file.filename == '':
            return None
            
        filename = secure_filename(file.filename)
        unique_name = f"{uuid4().hex}_{filename}"
        save_path = os.path.join(upload_folder, subfolder, unique_name)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
        
        return {
            'filename': filename,
            'path': os.path.join(subfolder, unique_name),
            'content_type': file.content_type,
            'size': os.path.getsize(save_path)
        }

    # Gestion des profils et fichiers
    profile_data = {}
    
    if profile_type == 'student':
        # Créer le profil étudiant
        student_profile = StudentProfile(
            institution=data.get('institution', ''),
            education_level=data.get('educationLevel', ''),
            sector=data.get('sector', ''),
            motivations=data.get('motivations', ''),
            interests=data.get('interests', '')
        )
        
        # Gestion des fichiers étudiants
        if not request.is_json:
            if 'cv_file' in files:
                file_info = save_file(files['cv_file'], 'students/cv')
                if file_info:
                    student_profile.cv_file = FileField(**file_info)
                    profile_data['cv_path'] = file_info['path']
            
            if 'cover_letter_file' in files:
                file_info = save_file(files['cover_letter_file'], 'students/cover_letters')
                if file_info:
                    student_profile.cover_letter_file = FileField(**file_info)
                    profile_data['cover_letter_path'] = file_info['path']
        
        user.student_profile = student_profile

    elif profile_type == 'startup':
        # Créer le profil startup
        startup_profile = StartupProfile(
            company_name=data.get('companyName', ''),
            company_sector=data.get('companySector', ''),
            location=data.get('location', ''),
            value_proposition=data.get('valueProposition', ''),
            maturity_stage=data.get('maturityStage', ''),
            founding_team=data.get('foundingTeam', ''),
            needs=data.get('needs', '')
        )
        
        # Gestion des fichiers startup
        if not request.is_json:
            if 'logo_file' in files:
                file_info = save_file(files['logo_file'], 'startups/logos')
                if file_info:
                    startup_profile.logo_file = FileField(**file_info)
                    profile_data['logo_path'] = file_info['path']
            
            if 'pitch_deck_file' in files:
                file_info = save_file(files['pitch_deck_file'], 'startups/pitch_decks')
                if file_info:
                    startup_profile.pitch_deck_file = FileField(**file_info)
                    profile_data['pitch_deck_path'] = file_info['path']
            
            if 'business_plan_file' in files:
                file_info = save_file(files['business_plan_file'], 'startups/business_plans')
                if file_info:
                    startup_profile.business_plan_file = FileField(**file_info)
                    profile_data['business_plan_path'] = file_info['path']
        
        user.startup_profile = startup_profile

    elif profile_type in ['corporate', 'investor']:
        # Créer le profil corporate/investor
        corp_profile = CorporateInvestorProfile(
            organization_name=data.get('organizationName', ''),
            activities=data.get('activities', ''),
            interest_sectors=data.get('interestSectors', ''),
            cooperation_objectives=data.get('cooperationObjectives', '')
        )
        
        # Gestion des fichiers corporate/investor
        if not request.is_json and 'brochure_file' in files:
            file_info = save_file(files['brochure_file'], 'corporate/brochures')
            if file_info:
                corp_profile.brochure_file = FileField(**file_info)
                profile_data['brochure_path'] = file_info['path']
        
        user.corporate_investor_profile = corp_profile

    # Ajouter les données de profil communes
    user.profile_data = profile_data
    user.save()

    # Générer token JWT
    auth_result = AuthService.generate_token(user)

    return jsonify({
        'success': True,
        'message': 'Inscription réussie',
        'token': auth_result['token'],
        'user': auth_result['user']
    })
@auth_bp.route('/google/authorize')
def google_authorize():
    # Utilisez toujours l'URI de votre backend pour le callback
    redirect_uri = current_app.config['GOOGLE_REDIRECT_URI']
    auth_url = GoogleOAuthService.get_auth_url(redirect_uri)
    return redirect(auth_url)
@auth_bp.route('/google/callback')
def google_callback():
    code = request.args.get('code')
    
    if not code:
        current_app.logger.error("Aucun code reçu de Google")
        return jsonify({"error": "no_code_received"}), 400

    try:
        # 1. Obtenir les données du token
        token_data = GoogleOAuthService.get_token(code)
        
        # 2. Vérifier que token_data contient access_token
        if 'access_token' not in token_data:
            raise ValueError("Access token manquant dans la réponse")
            
        # 3. Obtenir les informations utilisateur avec le token d'accès
        access_token = token_data['access_token']
        user_info = GoogleOAuthService.get_user_info(access_token)
        
        # 4. Traiter la connexion
        auth_result = AuthService.login_with_oauth(
            provider='google',
            oauth_id=user_info['oauth_id'],
            oauth_data=user_info
        )

        # 5. Récupérer l'URL frontend
        frontend_url = current_app.config['FRONTEND_URL']
        
        # 6. Rediriger vers la page de callback OAuth spécifique
        redirect_url = f"{frontend_url}/oauth-callback?token={auth_result['token']}"
        current_app.logger.debug(f"Redirection vers: {redirect_url}")
        return redirect(redirect_url)

    except Exception as e:
        current_app.logger.error(f"Google OAuth error: {str(e)}", exc_info=True)
        frontend_url = current_app.config['FRONTEND_URL']
        return redirect(f"{frontend_url}/oauth-callback?error={str(e)}")
@auth_bp.route('/linkedin/authorize')
def linkedin_authorize():
    redirect_uri = "http://localhost:5000/api/auth/linkedin/callback"

    frontend_redirect = request.args.get('frontend_redirect', '/')

    # Sauvegarde dans la session
    session['frontend_redirect'] = frontend_redirect

    # Génère l'URL d'autorisation LinkedIn
    auth_url = LinkedInOAuthService.get_auth_url(redirect_uri)

    # Redirige immédiatement le navigateur (popup) vers LinkedIn
    return redirect(auth_url)
@auth_bp.route('/linkedin/callback')
def linkedin_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    
    frontend_url = current_app.config['FRONTEND_URL']
    
    if error:
        current_app.logger.error(f"LinkedIn error: {error}")
        return redirect(f"{frontend_url}/oauth-callback?error={error}")
    
    if not code:
        current_app.logger.error("Aucun code reçu de LinkedIn")
        return redirect(f"{frontend_url}/oauth-callback?error=no_code_received")
    
    try:
        # 1. Obtenir le token
        token = LinkedInOAuthService.get_token(code)
        
        # 2. Log pour debug
        current_app.logger.debug(f"LinkedIn token: {token}")
        
        # 3. Obtenir les infos utilisateur
        user_info = LinkedInOAuthService.get_user_info(token)
        
        # 4. Traiter la connexion - Correction du nom du paramètre
        auth_result = AuthService.login_with_oauth(
            provider='linkedin',
            oauth_id=user_info['oauth_id'],
            oauth_data=user_info  # Changé de user_info à oauth_data
        )
        
        # 5. Rediriger vers le frontend avec le token
        return redirect(f"{frontend_url}/oauth-callback?token={auth_result['token']}")
    
    except Exception as e:
        current_app.logger.error(f"LinkedIn OAuth error: {str(e)}", exc_info=True)
        return redirect(f"{frontend_url}/oauth-callback?error={str(e)}")
def verify_token():
    data = request.get_json()
    
    if not data or 'token' not in data:
        raise BadRequest("Token manquant")
    
    token = data['token']
    user = AuthService.verify_token(token)
    
    return jsonify({
        'valid': True,
        'user': user.to_json()
    })

@auth_bp.errorhandler(BadRequest)
@auth_bp.errorhandler(Unauthorized)
@auth_bp.errorhandler(InternalServerError)
def handle_error(error):
    response = jsonify({
        'error': True,
        'message': str(error)
    })
    response.status_code = error.code
    return response



@auth_bp.route('/get-profile', methods=['GET'])
@jwt_required()
def get_profile():
    try:
        user = AuthService.get_current_user()
        if not user:
            raise Unauthorized("Utilisateur invalide")

        response_data = user.to_json()
        
        # Ajouter les données de profil spécifiques
        if user.profile_type == 'student' and user.student_profile:
            response_data['profile_data'] = {
                'institution': user.student_profile.institution,
                'education_level': user.student_profile.education_level,
                'sector': user.student_profile.sector,
                'motivations': user.student_profile.motivations,
                'interests': user.student_profile.interests,
                'cv_file': user.student_profile.cv_file.to_json() if user.student_profile.cv_file else None,
                'cover_letter_file': user.student_profile.cover_letter_file.to_json() if user.student_profile.cover_letter_file else None
            }
        elif user.profile_type == 'startup' and user.startup_profile:
            response_data['profile_data'] = {
                'company_name': user.startup_profile.company_name,
                'company_sector': user.startup_profile.company_sector,
                'location': user.startup_profile.location,
                'value_proposition': user.startup_profile.value_proposition,
                'maturity_stage': user.startup_profile.maturity_stage,
                'founding_team': user.startup_profile.founding_team,
                'needs': user.startup_profile.needs,
                'logo_file': user.startup_profile.logo_file.to_json() if user.startup_profile.logo_file else None,
                'pitch_deck_file': user.startup_profile.pitch_deck_file.to_json() if user.startup_profile.pitch_deck_file else None,
                'business_plan_file': user.startup_profile.business_plan_file.to_json() if user.startup_profile.business_plan_file else None
            }
        elif user.profile_type in ['corporate', 'investor'] and user.corporate_investor_profile:
            response_data['profile_data'] = {
                'organization_name': user.corporate_investor_profile.organization_name,
                'activities': user.corporate_investor_profile.activities,
                'interest_sectors': user.corporate_investor_profile.interest_sectors,
                'cooperation_objectives': user.corporate_investor_profile.cooperation_objectives,
                'brochure_file': user.corporate_investor_profile.brochure_file.to_json() if user.corporate_investor_profile.brochure_file else None
            }
        
        return jsonify({'success': True, 'user': response_data})

    except Exception as e:
        current_app.logger.error(f"Erreur get-profile: {str(e)}")
        raise InternalServerError("Erreur de récupération")

@auth_bp.route('/update-profile', methods=['POST'])
@jwt_required()
def update_profile():
    try:
        user = AuthService.get_current_user()
        if not user:
            raise Unauthorized("Utilisateur invalide")

        # Initialisation
        form_data = request.form.to_dict()
        files = request.files.to_dict()
        UPLOAD_FOLDER = current_app.config['UPLOAD_FOLDER']

        # Fonction pour sauvegarder les fichiers
        def save_file(file, subfolder):
            if not file or file.filename == '':
                return None

            # Sécuriser le nom de fichier
            filename = secure_filename(file.filename)
            unique_name = f"{uuid4().hex}_{filename}"
            folder_path = os.path.join(UPLOAD_FOLDER, subfolder)
            os.makedirs(folder_path, exist_ok=True)
            file_path = os.path.join(folder_path, unique_name)
            file.save(file_path)

            return {
                'filename': filename,
                'path': os.path.join(subfolder, unique_name),
                'content_type': file.content_type,
                'size': os.path.getsize(file_path)
            }

        # Mise à jour des champs de base
        if 'email' in form_data:
            user.email = form_data['email']
        if 'firstName' in form_data:
            user.first_name = form_data['firstName']
        if 'lastName' in form_data:
            user.last_name = form_data['lastName']

        # Mise à jour selon le type de profil
        if user.profile_type == 'student':
            user.student_profile = user.student_profile or StudentProfile()

            # Champs texte
            fields_mapping = {
                'institution': 'institution',
                'educationLevel': 'education_level',
                'sector': 'sector',
                'motivations': 'motivations',
                'interests': 'interests'
            }

            for form_field, profile_field in fields_mapping.items():
                if form_field in form_data:
                    setattr(user.student_profile, profile_field, form_data[form_field])

            # Fichiers
            if 'cv_file' in files:
                if file_info := save_file(files['cv_file'], 'students/cv'):
                    user.student_profile.cv_file = FileField(**file_info)

            if 'cover_letter_file' in files:
                if file_info := save_file(files['cover_letter_file'], 'students/cover_letters'):
                    user.student_profile.cover_letter_file = FileField(**file_info)

        elif user.profile_type == 'startup':
            user.startup_profile = user.startup_profile or StartupProfile()

            # Champs texte
            fields_mapping = {
                'companyName': 'company_name',
                'companySector': 'company_sector',
                'location': 'location',
                'valueProposition': 'value_proposition',
                'maturityStage': 'maturity_stage',
                'foundingTeam': 'founding_team',
                'needs': 'needs'
            }

            for form_field, profile_field in fields_mapping.items():
                if form_field in form_data:
                    setattr(user.startup_profile, profile_field, form_data[form_field])

            # Fichiers
            if 'logo_file' in files:
                if file_info := save_file(files['logo_file'], 'startups/logos'):
                    user.startup_profile.logo_file = FileField(**file_info)

            if 'pitch_deck_file' in files:
                if file_info := save_file(files['pitch_deck_file'], 'startups/pitch_decks'):
                    user.startup_profile.pitch_deck_file = FileField(**file_info)

            if 'business_plan_file' in files:
                if file_info := save_file(files['business_plan_file'], 'startups/business_plans'):
                    user.startup_profile.business_plan_file = FileField(**file_info)

        elif user.profile_type in ['corporate', 'investor']:
            user.corporate_investor_profile = user.corporate_investor_profile or CorporateInvestorProfile()

            # Champs texte
            fields_mapping = {
                'organizationName': 'organization_name',
                'activities': 'activities',
                'interestSectors': 'interest_sectors',
                'cooperationObjectives': 'cooperation_objectives'
            }

            for form_field, profile_field in fields_mapping.items():
                if form_field in form_data:
                    setattr(user.corporate_investor_profile, profile_field, form_data[form_field])

            # Fichiers
            if 'brochure_file' in files:
                if file_info := save_file(files['brochure_file'], 'corporate/brochures'):
                    user.corporate_investor_profile.brochure_file = FileField(**file_info)

        user.save()

        return jsonify({
            'success': True,
            'message': 'Profil mis à jour avec succès',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'profile_type': user.profile_type,
                'profile_data': {
                    **(user.student_profile.to_json() if hasattr(user, 'student_profile') and user.student_profile else {}),
                    **(user.startup_profile.to_json() if hasattr(user, 'startup_profile') and user.startup_profile else {}),
                    **(user.corporate_investor_profile.to_json() if hasattr(user, 'corporate_investor_profile') and user.corporate_investor_profile else {})
                }
            }
        })

    except Exception as e:
        current_app.logger.error(f"Erreur update-profile: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@auth_bp.route('/google/debug', methods=['POST'])
def google_debug():
    import requests
    code = request.json.get('code')
    
    token_url = 'https://oauth2.googleapis.com/token'
    payload = {
        'code': code,
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
        'redirect_uri': current_app.config['GOOGLE_REDIRECT_URI'],
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=payload)
    return {
        'status_code': response.status_code,
        'headers': dict(response.headers),
        'content': response.text  # Retourne le contenu brut pour inspection
    }