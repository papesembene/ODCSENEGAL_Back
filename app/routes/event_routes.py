from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from app.models.event import Event, Registration, Newsletter
from werkzeug.exceptions import BadRequest, NotFound
from mongoengine.errors import ValidationError
import os



events = Blueprint('events', __name__)


# GET /api/events/           → tous les événements
@events.route('/', methods=['GET'])
def get_events():
    events_list = Event.get_all_events()
    return jsonify({'events': [e.to_dict() for e in events_list]}), 200

# GET /api/events/upcoming   → événements à venir
@events.route('/upcoming', methods=['GET'])
def get_upcoming_events():
    upcoming = Event.get_upcoming_events()
    return jsonify({'events': [e.to_dict() for e in upcoming]}), 200

# GET /api/events/past       → événements passés
@events.route('/past', methods=['GET'])
def get_past_events():
    past = Event.get_past_events()
    return jsonify({'events': [e.to_dict() for e in past]}), 200

# GET /api/events/<id>       → détail d’un événement
@events.route('/<event_id>', methods=['GET'])
def get_event(event_id):
    event = Event.get_event_by_id(event_id)
    if not event:
        raise NotFound("Événement non trouvé")
    return jsonify(event.to_dict()), 200

# POST /api/events/ + OPTIONS → création d’un événement

@events.route('/', methods=['POST', 'OPTIONS'])
def add_event():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'CORS preflight passed'}), 200

    # Gestion des données et fichiers
    if request.content_type.startswith('multipart/form-data'):
        data = request.form.to_dict()
        image_file = request.files.get('image')

        # 🔐 Détermine le chemin d’upload correct selon Flask
        upload_folder = os.path.join(current_app.static_folder, 'uploads')
        os.makedirs(upload_folder, exist_ok=True)

        if image_file:
            filename = image_file.filename
            save_path = os.path.join(upload_folder, filename)
            image_file.save(save_path)
            data['image'] = f'/static/uploads/{filename}'  # Chemin accessible côté client
        else:
            data['image'] = '/static/images/event-default.jpg'
    else:
        data = request.get_json() or {}
        data.setdefault('image', '/static/images/event-default.jpg')

    # Champs obligatoires
    for field in ('title', 'date', 'time', 'location'):
        if not data.get(field):
            return jsonify({'error': f'Le champ {field} est requis'}), 400

    # Formatage de la date
    try:
        raw_date = data['date']
        if isinstance(raw_date, str):
            if raw_date.endswith('Z'):
                raw_date = raw_date[:-1] + '+00:00'
            data['date'] = datetime.fromisoformat(raw_date)
        else:
            return jsonify({'error': 'Le champ date doit être une chaîne ISO'}), 400
    except ValueError as e:
        return jsonify({'error': f'Format de date invalide: {str(e)}'}), 400

    # Champs optionnels
    data.setdefault('description', '')
    data.setdefault('category', '')
    data.setdefault('agenda', [])
    data.setdefault('speakers', [])
    data.setdefault('details', '')

    try:
        event = Event.create_event(data)
        return jsonify({
            'message': 'Événement créé avec succès',
            'event': event.to_dict()
        }), 201

    except ValidationError as e:
        return jsonify({'error': f'Erreur de validation: {str(e)}'}), 400

    except Exception as e:
        print(f'Erreur serveur: {str(e)}')
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    

# PUT /api/events/<id>       → mise à jour
@events.route('/<event_id>', methods=['PUT'])
def update_event(event_id):
    data = request.get_json() or {}
    if not data:
        raise BadRequest("Données de mise à jour requises")

    updated = Event.update_event(event_id, data)
    if not updated:
        raise NotFound("Événement non trouvé ou aucune modification")
    return jsonify({'message': 'Événement mis à jour'}), 200

# DELETE /api/events/<id>    → suppression
@events.route('/<event_id>', methods=['DELETE'])
def delete_event(event_id):
    deleted = Event.delete_event(event_id)
    if not deleted:
        raise NotFound("Événement non trouvé")
    return jsonify({'message': 'Événement supprimé'}), 200

# POST /api/events/<id>/register → inscription
@events.route('/<event_id>/register', methods=['POST'])
def register_to_event(event_id):
    data = request.get_json() or {}
    for field in ('name', 'email', 'phone'):
        if not data.get(field):
            raise BadRequest("Nom, email et téléphone requis")

    event = Event.get_event_by_id(event_id)
    if not event:
        raise NotFound("Événement non trouvé")

    if Registration.check_registration(event_id, data['email']):
        return jsonify({'message': 'Déjà inscrit'}), 200

    reg_data = {
        'event_id': event,
        'email': data['email'],
        'name': data['name'],
    }
    registration = Registration.create_registration(reg_data)
    return jsonify({
        'message': 'Inscription réussie',
        'registration_id': str(registration.id)
    }), 201

# GET /api/events/<id>/registrations → lister les inscriptions
@events.route('api/<event_id>/registrations', methods=['GET'])
def get_event_registrations(event_id):
    regs = Registration.get_registrations_for_event(event_id)
    return jsonify({'registrations': [r.to_dict() for r in regs]}), 200

# POST /api/events/newsletter/subscribe    → newsletter
@events.route('/newsletter/subscribe', methods=['POST'])
def subscribe_to_newsletter():
    data = request.get_json() or {}
    email = data.get('email')
    if not email:
        raise BadRequest("Email requis")
    ok = Newsletter.subscribe(email)
    return jsonify({'message': ok and 'Inscrit à la newsletter' or 'Déjà inscrit'}), ok and 201 or 200

# POST /api/events/newsletter/unsubscribe  → désabonnement
@events.route('/newsletter/unsubscribe', methods=['POST'])
def unsubscribe_from_newsletter():
    data = request.get_json() or {}
    email = data.get('email')
    if not email:
        raise BadRequest("Email requis")
    ok = Newsletter.unsubscribe(email)
    return jsonify({'message': ok and 'Désabonnement réussi' or 'Email non trouvé'}), ok and 200 or 404
