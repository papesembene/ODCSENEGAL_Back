from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import re
import uuid
from app.models.startup import Startup
from app.services.startup_email_service import StartupEmailService

startup_bp = Blueprint("startup", __name__)
UPLOAD_FOLDER = os.path.join("uploads", "startups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def validate_email(email):
    """Valider le format de l'email"""
    pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """Valider le format du téléphone (au moins 8 chiffres)"""
    phone_digits = re.sub(r'[^\d]', '', phone)
    return len(phone_digits) >= 8

def validate_date(date_string):
    """Valider que la date de création n'est pas dans le futur"""
    try:
        creation_date = datetime.strptime(date_string, '%Y-%m-%d')
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return creation_date <= today
    except ValueError:
        return False

@startup_bp.route("/check-email", methods=["GET"])
def check_email():
    """Vérifier si un email existe déjà"""
    try:
        email = request.args.get('email')
        
        if not email:
            return jsonify({'error': 'Email requis'}), 400
        
        exists = Startup.check_email_exists(email)
        return jsonify({'exists': exists})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@startup_bp.route("/check-phone", methods=["GET"])
def check_phone():
    """Vérifier si un numéro de téléphone existe déjà"""
    try:
        phone = request.args.get('phone')
        
        if not phone:
            return jsonify({'error': 'Téléphone requis'}), 400
        
        exists = Startup.check_phone_exists(phone)
        return jsonify({'exists': exists})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@startup_bp.route("/submit", methods=["GET", "POST"])
def submit_application():
    """Soumettre une candidature startup"""
    if request.method == 'GET':
        return jsonify({
            "message": "Submit endpoint for Startup Lab",
            "instructions": "Send POST request with form-data containing all required fields",
            "program": "startup_lab"
        }), 200
    
    try:
        # Récupérer les données du formulaire
        data = request.form.to_dict()
        cv_file = request.files.get("cv")
        pitch_file = request.files.get("pitch_deck")

        print(f"Données reçues du formulaire: {data}")  # Debug log

        # Validation des champs obligatoires
        required_fields = [
            "firstName", "lastName", "role", "email", "phone", "phoneCountry",
            "region", "department", "diploma", "companyName", "ninea", "sector", 
            "businessModel", "creationDate", "legalForm", "employees", "raisedFunds",
            "productName", "productDescription", "activityDescription", 
            "hasWorkingProduct"
        ]
        
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({"error": f"Champs requis manquants: {', '.join(missing_fields)}"}), 400

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
        if Startup.check_email_exists(data['email']):
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
        if Startup.check_phone_exists(full_phone):
            return jsonify({'error': 'Ce numéro de téléphone a déjà été utilisé pour une candidature'}), 400

        # Validation de la date de création
        if not validate_date(data['creationDate']):
            return jsonify({'error': 'Date de création invalide ou dans le futur'}), 400

        # CV requis
        if not cv_file or not cv_file.filename:
            return jsonify({"error": "CV requis"}), 400

        # Pitch deck requis
        if not pitch_file or not pitch_file.filename:
            return jsonify({"error": "Document de présentation requis"}), 400

        # Validation de la taille des fichiers (250MB max)
        max_file_size = 250 * 1024 * 1024  # 250MB en bytes
        
        # Vérifier la taille des fichiers
        cv_file.seek(0, os.SEEK_END)
        cv_size = cv_file.tell()
        cv_file.seek(0)
        
        pitch_file.seek(0, os.SEEK_END)
        pitch_size = pitch_file.tell()
        pitch_file.seek(0)
        
        if cv_size > max_file_size:
            return jsonify({"error": "Le CV est trop volumineux (max 250MB)"}), 400
            
        if pitch_size > max_file_size:
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
        data["pitchDeck"] = pitch_path

        # Conversion des booléens et ajout des métadonnées
        data["acceptTerms"] = data.get("acceptTerms") == "true"
        data["createdAt"] = datetime.utcnow()
        data["program"] = "startup_lab"

        # Ajouter le founder_email pour la compatibilité avec l'index existant
        data["founder_email"] = data["email"]  # Utiliser l'email principal comme founder_email

        # Générer un nom unique pour la startup en ajoutant un identifiant unique
        unique_id = str(uuid.uuid4())[:8]  # Utiliser les 8 premiers caractères de l'UUID
        timestamp_short = datetime.now().strftime("%y%m%d%H%M")  # Format court: AAMMJJHHMM
        
        # Assurer la compatibilité avec l'ancien modèle qui a un index unique sur startup_name
        data["startup_name"] = f"{data['companyName']}-{timestamp_short}-{unique_id}"
        
        print(f"Nom unique généré pour la startup: {data['startup_name']}")  # Debug log
        print(f"Données avant sauvegarde: {data}")  # Debug log

        # Créer et sauvegarder l'application
        try:
            application = Startup(**data)
            application.save()  # Sauvegarde en base de données
            print(f"Application sauvegardée avec l'ID: {application.id}")  # Debug log
        except Exception as save_error:
            print(f"Erreur lors de la sauvegarde: {save_error}")
            return jsonify({"error": f"Erreur lors de la sauvegarde: {str(save_error)}"}), 500

        # Envoyer l'email de confirmation
        try:
            email_service = StartupEmailService()
            email_service.init_app(current_app)
            
            # Préparer les données pour l'email
            email_data = {
                'firstName': data.get('firstName'),
                'lastName': data.get('lastName'),
                'email': data.get('email'),
                'companyName': data.get('companyName'),
                'sector': data.get('sector'),
                'productName': data.get('productName'),
                'program': 'Startup Lab',
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
            "success": True,
            "message": "Candidature soumise avec succès", 
            "data": {
                "id": str(application.id),
                "companyName": application.companyName,
                "startup_name": application.startup_name,
                "program": "startup_lab"
            }
        }), 201

    except Exception as e:
        print(f"Erreur lors de la soumission: {e}")
        import traceback
        traceback.print_exc()  # Pour avoir plus de détails sur l'erreur
        return jsonify({"error": "Erreur interne du serveur"}), 500

@startup_bp.route('/uploads/<filename>', methods=['GET'])
def get_uploaded_file(filename):
    """Récupération d'un fichier uploadé"""
    try:
        from flask import send_from_directory
        return send_from_directory(UPLOAD_FOLDER, filename)
    except FileNotFoundError:
        return jsonify({"error": "Fichier introuvable"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@startup_bp.route('/delete/<startup_id>', methods=['DELETE'])
def delete_startup(startup_id):
    """Suppression d'une startup et des fichiers associés"""
    try:
        startup = Startup.objects.get(id=startup_id)

        # Suppression des fichiers associés
        for field in ['cv', 'pitchDeck']:
            file_path = getattr(startup, field, None)
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

        startup.delete()
        return jsonify({"success": True, "message": "Startup supprimée"}), 200

    except Startup.DoesNotExist:
        return jsonify({"error": "Startup introuvable"}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur suppression : {str(e)}", exc_info=True)
        return jsonify({"error": "Suppression échouée"}), 500

@startup_bp.route('/list', methods=['GET'])
def list_startups():
    """Lister toutes les candidatures startup pour debug"""
    try:
        startups = Startup.objects.all()
        startup_list = []
        for startup in startups:
            startup_list.append({
                'id': str(startup.id),
                'companyName': startup.companyName,
                'startup_name': startup.startup_name,
                'firstName': startup.firstName,
                'lastName': startup.lastName,
                'email': startup.email,
                'createdAt': startup.createdAt.strftime('%d/%m/%Y %H:%M') if startup.createdAt else None
            })
        
        return jsonify({
            'success': True,
            'count': len(startup_list),
            'startups': startup_list
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
