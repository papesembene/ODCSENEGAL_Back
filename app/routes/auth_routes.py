from urllib.parse import urlencode

from flask import Blueprint, request, jsonify, redirect, current_app, session
from werkzeug.exceptions import BadRequest, Unauthorized, InternalServerError
from app.services.auth_service import AuthService
from app.services.oauth_service import GoogleOAuthService, LinkedInOAuthService
from app.services.profiles.profile_service import (
    ProfileService,
    ProfileValidationError,
)
from flask_jwt_extended import jwt_required
import os

UPLOAD_FOLDER = 'uploads'  # Assure-toi que ce dossier existe
os.makedirs(UPLOAD_FOLDER, exist_ok=True)



auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
profile_service = ProfileService()

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
    data = request.get_json() if request.is_json else request.form.to_dict()
    if not data:
        raise BadRequest("Données manquantes")
    try:
        user = profile_service.register(
            data,
            {} if request.is_json else request.files,
            os.path.join(current_app.root_path, 'static/uploads'),
        )
    except ProfileValidationError as error:
        raise BadRequest(str(error)) from error

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
        GoogleOAuthService.validate_state()
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
        redirect_url = (
            f"{frontend_url}/oauth-callback?"
            f"{urlencode({'token': auth_result['token']})}"
        )
        return redirect(redirect_url)

    except Exception as e:
        current_app.logger.error(f"Google OAuth error: {str(e)}", exc_info=True)
        frontend_url = current_app.config['FRONTEND_URL']
        return redirect(
            f"{frontend_url}/oauth-callback?"
            f"{urlencode({'error': 'google_oauth_failed'})}"
        )
@auth_bp.route('/linkedin/authorize')
def linkedin_authorize():
    redirect_uri = current_app.config["LINKEDIN_REDIRECT_URI"]

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
        return redirect(
            f"{frontend_url}/oauth-callback?"
            f"{urlencode({'error': error})}"
        )
    
    if not code:
        current_app.logger.error("Aucun code reçu de LinkedIn")
        return redirect(f"{frontend_url}/oauth-callback?error=no_code_received")
    
    try:
        # 1. Obtenir le token
        token = LinkedInOAuthService.get_token(code)
        
        # 2. Log pour debug
        # 3. Obtenir les infos utilisateur
        user_info = LinkedInOAuthService.get_user_info(token)
        
        # 4. Traiter la connexion - Correction du nom du paramètre
        auth_result = AuthService.login_with_oauth(
            provider='linkedin',
            oauth_id=user_info['oauth_id'],
            oauth_data=user_info  # Changé de user_info à oauth_data
        )
        
        # 5. Rediriger vers le frontend avec le token
        return redirect(
            f"{frontend_url}/oauth-callback?"
            f"{urlencode({'token': auth_result['token']})}"
        )
    
    except Exception as e:
        current_app.logger.error(f"LinkedIn OAuth error: {str(e)}", exc_info=True)
        return redirect(
            f"{frontend_url}/oauth-callback?"
            f"{urlencode({'error': 'linkedin_oauth_failed'})}"
        )


@auth_bp.route('/verify-token', methods=['POST', 'OPTIONS'])
def verify_token():
    if request.method == 'OPTIONS':
        return '', 200
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

        return jsonify({
            'success': True,
            'user': profile_service.serialize(user),
        })

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

        form_data = request.form.to_dict()
        files = request.files.to_dict()
        user = profile_service.update(
            user,
            form_data,
            files,
            current_app.config['UPLOAD_FOLDER'],
        )

        return jsonify({
            'success': True,
            'message': 'Profil mis à jour avec succès',
            'user': profile_service.serialize_update_response(user),
        })

    except Exception as e:
        current_app.logger.error(f"Erreur update-profile: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
