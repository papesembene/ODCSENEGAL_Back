from flask import request, jsonify
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

auth = HTTPBasicAuth()

# Configuration des identifiants admin (à mettre dans une config sécurisée en production)
ADMIN_CREDENTIALS = {
    "admin": generate_password_hash("1234")
}

@auth.verify_password
def verify_password(username, password):
    if username in ADMIN_CREDENTIALS and \
            check_password_hash(ADMIN_CREDENTIALS.get(username), password):
        return username

@api.route('/admin/events', methods=['POST'])
@auth.login_required
def admin_create_event():
    data = request.get_json()

    # Validation des données
    required_fields = ['title', 'date', 'description', 'category']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Champs manquants"}), 400
    
    try:
        # Conversion de la date
        data['date'] = datetime.fromisoformat(data['date'])

        # Valeurs par défaut
        data.setdefault('time', "14:00")
        data.setdefault('location', "Orange Digital Center, Dakar")
        data.setdefault('attendees', 0)
        data.setdefault('image', "/images/event-default.jpg")
        
        # Optionally set other fields like agenda or speakers if provided
        data.setdefault('agenda', [])
        data.setdefault('speakers', [])
        data.setdefault('details', "")
        
        # Création de l'événement
        event_id = Event.create_event(data)

        # Si l'insertion échoue (ex: problème avec la base de données)
        if not event_id:
            return jsonify({"error": "Échec de la création de l'événement"}), 500
        
        return jsonify({
            "message": "Événement créé avec succès",
            "event_id": str(event_id)
        }), 201
        
    except ValueError as e:
        return jsonify({"error": "Format de date invalide"}), 400
    except Exception as e:
        # Catch all for unexpected errors
        return jsonify({"error": f"Erreur inattendue: {str(e)}"}), 500