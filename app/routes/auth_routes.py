from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.exceptions import BadRequest, Unauthorized, InternalServerError, NotFound
from app.utils.auth_decorators import _extract_bearer_token
from app.utils.request_guards import login_credentials, is_request_rate_limited
from app.services.auth_service import AuthService
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

@auth_bp.after_request
def private_auth_response(response):
    response.headers.setdefault('Cache-Control', 'no-store')
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@auth_bp.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 200  # Réponse vide = préflight validé
    data = request.get_json(silent=True)
    
    if not data:
        raise BadRequest("Données manquantes")
    
    email, password = login_credentials(data)
    
    if not email or not password:
        raise BadRequest("Email et mot de passe requis")
    
    result = AuthService.login_with_email(email, password)
    return jsonify(result)

@auth_bp.route('/register', methods=['POST'])
def register():
    if is_request_rate_limited("profile_register_ip", request.remote_addr, limit=30, window=300):
        return jsonify(error="Trop de tentatives, veuillez réessayer plus tard"), 429
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


@auth_bp.route('/documents/<path:filename>', methods=['GET'])
def download_own_document(filename):
    user = AuthService.verify_token(_extract_bearer_token())
    normalized = filename.replace('\\', '/')
    if normalized not in profile_service.document_paths(user):
        raise NotFound('Document introuvable')
    # Registrations used static/uploads; profile updates used app/uploads.
    for root in (current_app.config['UPLOAD_FOLDER'], os.path.join(current_app.root_path, 'static', 'uploads')):
        try:
            response = send_from_directory(root, normalized, as_attachment=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        except NotFound:
            continue
    raise NotFound('Document introuvable')

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

    except ProfileValidationError as error:
        return jsonify(success=False, message=str(error)), 400
    except Exception as e:
        current_app.logger.error(f"Erreur update-profile: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
