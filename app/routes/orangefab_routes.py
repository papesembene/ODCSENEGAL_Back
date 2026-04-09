from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import re
from app.models.orangefab import OrangeFab
from app.services.email_service import EmailService
 
orangefab_bp = Blueprint("orangefab", __name__)
UPLOAD_FOLDER = os.path.join("uploads", "orangefab")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
 
def validate_email(email):
    """Valider le format de l'email"""
    pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return re.match(pattern, email) is not None
 
def validate_phone(phone):
    """Valider le format du téléphone (au moins 8 chiffres)"""
    # Enlever l'indicatif pays pour valider seulement le numéro local
    phone_digits = re.sub(r'[^\d]', '', phone)
    return len(phone_digits) >= 8
 
@orangefab_bp.route("/check-email", methods=["GET"])
def check_email():
    """Vérifier si un email existe déjà"""
    try:
        email = request.args.get('email')
       
        if not email:
            return jsonify({'error': 'Email requis'}), 400
       
        exists = OrangeFab.check_email_exists(email)
        return jsonify({'exists': exists})
       
    except Exception as e:
        return jsonify({'error': str(e)}), 500
 
@orangefab_bp.route("/check-phone", methods=["GET"])
def check_phone():
    """Vérifier si un numéro de téléphone existe déjà"""
    try:
        phone = request.args.get('phone')
       
        if not phone:
            return jsonify({'error': 'Téléphone requis'}), 400
       
        exists = OrangeFab.check_phone_exists(phone)
        return jsonify({'exists': exists})
       
    except Exception as e:
        return jsonify({'error': str(e)}), 500
 
@orangefab_bp.route("/", methods=["POST"])
def submit_application():
    """Soumettre une candidature"""
    try:
        # Récupérer les données du formulaire
        data = request.form.to_dict()
        cv_file = request.files.get("cv")
        pitch_file = request.files.get("pitch_deck")
 
        # Validation des champs obligatoires (mis à jour)
        required_fields = [
            "firstName", "lastName", "role", "email", "phone", "phoneCountry", "region",
            "department","diploma", "companyName", "ninea", "sector",
            "businessModel", "creationDate", "legalForm", "employees", "raisedFunds",
            "productName", "productDescription", "activityDescription",
            "hasWorkingProduct"
        ]
       
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"Champ requis manquant: {field}"}), 400
 
        # Vérifier les champs conditionnels "Autre"
        if data.get('role') == 'Autre' and not data.get('otherRole'):
            return jsonify({"error": "Précisez votre rôle"}), 400
       
        if data.get('diploma') == 'autre' and not data.get('otherDiploma'):
            return jsonify({"error": "Précisez votre diplôme"}), 400
       
        if data.get('sector') == 'other' and not data.get('otherSector'):
            return jsonify({"error": "Précisez votre secteur d'activité"}), 400
       
        if data.get('legalForm') == 'Autre' and not data.get('otherLegalForm'):
            return jsonify({"error": "Précisez votre forme juridique"}), 400
 
        # Validation du montant levé si "Oui" est sélectionné
        if data.get('raisedFunds') == 'Oui' and not data.get('raisedAmount'):
            return jsonify({"error": "Le montant levé est obligatoire"}), 400
 
        # Validation de l'email
        if not validate_email(data['email']):
            return jsonify({'error': 'Format email invalide'}), 400
 
        # Vérifier si l'email existe déjà
        if OrangeFab.check_email_exists(data['email']):
            return jsonify({'error': 'Cet email a déjà été utilisé pour une candidature'}), 400
 
        # Validation email alternatif
        if data.get('emailAlternate'):
            if not validate_email(data['emailAlternate']):
                return jsonify({'error': 'Format email alternatif invalide'}), 400
            if data['emailAlternate'] == data['email']:
                return jsonify({'error': 'L\'email alternatif doit être différent de l\'email principal'}), 400
 
        # Construire le numéro de téléphone complet
        full_phone = data['phoneCountry'] + data['phone']
        data['fullPhone'] = full_phone
 
        # Validation du téléphone
        if not validate_phone(data['phone']):
            return jsonify({'error': 'Le téléphone doit contenir au moins 8 chiffres'}), 400
 
        # Vérifier si le téléphone existe déjà
        if OrangeFab.check_phone_exists(full_phone):
            return jsonify({'error': 'Ce numéro de téléphone a déjà été utilisé pour une candidature'}), 400
 
        # CV requis
        if not cv_file:
            return jsonify({"error": "CV requis"}), 400
 
        # Pitch deck requis
        if not pitch_file:
            return jsonify({"error": "Document de présentation requis"}), 400
 
        # Validation de la taille des fichiers (250MB max)
        max_file_size = 250 * 1024 * 1024  # 250MB en bytes
       
        if cv_file.content_length and cv_file.content_length > max_file_size:
            return jsonify({"error": "Le CV est trop volumineux (max 250MB)"}), 400
           
        if pitch_file.content_length and pitch_file.content_length > max_file_size:
            return jsonify({"error": "Le document de présentation est trop volumineux (max 250MB)"}), 400
 
        # Générer des noms de fichiers uniques avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
       
        # Sauvegarde du CV
        cv_filename = f"{timestamp}_{secure_filename(cv_file.filename)}"
        cv_path = os.path.join(UPLOAD_FOLDER, cv_filename)
        cv_file.save(cv_path)
        data["cv"] = cv_path
 
        # Sauvegarde du pitch deck
        pitch_filename = f"{timestamp}_{secure_filename(pitch_file.filename)}"
        pitch_path = os.path.join(UPLOAD_FOLDER, pitch_filename)
        pitch_file.save(pitch_path)
        data["pitch_deck"] = pitch_path
 
        # Conversion des booléens
        data["acceptTerms"] = data.get("acceptTerms") == "true"
        data["createdAt"] = datetime.utcnow()
 
        # Créer et sauvegarder l'application
        application = OrangeFab(**data)
        application.save()
 
        # Envoyer l'email de confirmation
        try:
            email_service = EmailService()
            email_service.init_app(current_app)
           
            # Préparer les données pour l'email
            email_data = {
                'firstName': data.get('firstName'),
                'lastName': data.get('lastName'),
                'email': data.get('email'),
                'companyName': data.get('companyName'),
                'sector': data.get('sector'),
                'productName': data.get('productName'),
                'created_at': application.createdAt
            }
           
            # Envoyer l'email de confirmation au candidat
            email_service.send_confirmation_email(email_data)
           
            # Envoyer la notification à l'admin
            email_service.send_admin_notification(email_data)
           
        except Exception as email_error:
            print(f"Erreur lors de l'envoi de l'email: {email_error}")
            # Ne pas faire échouer la candidature si l'email échoue
 
        return jsonify({
            "message": "Candidature soumise avec succès",
            "id": str(application.id)
        }), 201
 
    except Exception as e:
        print(f"Erreur lors de la soumission: {e}")
        return jsonify({"error": "Erreur interne du serveur"}), 500
 