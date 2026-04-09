from flask import Blueprint, request, jsonify
from app.models.candidature import Candidature
from mongoengine.errors import NotUniqueError, ValidationError, DoesNotExist
from datetime import datetime

# Blueprint pour les routes publiques (candidats)
candidature_public_bp = Blueprint("candidature_public", __name__)

# Blueprint pour les routes admin
candidature_bp = Blueprint("candidature", __name__)

@candidature_public_bp.route('/apply', methods=['POST'])
def apply():
    data = request.get_json()

    # Validation préliminaire
    required_fields = [
        'first_name', 'last_name', 'email', 'phone',
        'date_of_birth', 'place_of_birth', 'gender',
        'cni_or_passport_number', 'nationality',
        'region_of_residence', 'computer_skills',
        'available_for_10_months', 'desired_training',
        'accept_conditions'
    ]
      
    boolean_fields = ['computer_skills', 'available_for_10_months', 'accept_conditions']

    for field in required_fields:
      if field not in data:
        return jsonify(error=f"Le champ {field} est requis"), 400
    
      if field in boolean_fields:
         if not isinstance(data[field], bool):
            return jsonify(error=f"Le champ {field} doit être un booléen"), 400
    else:
        if not data[field]:
            return jsonify(error=f"Le champ {field} est requis"), 400

    try:
        # Vérification des doublons avant création
        email_exists = Candidature.objects(email=data['email']).first()
        if email_exists:
            return jsonify(error="Un utilisateur avec cet email existe déjà"), 400

        cni_exists = Candidature.objects(cni_or_passport_number=data['cni_or_passport_number']).first()
        if cni_exists:
            return jsonify(error="Un utilisateur avec ce numéro CNI/passeport existe déjà"), 400

        # Création de la candidature
        candidature = Candidature(
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            phone=data['phone'],
            date_of_birth=data['date_of_birth'],
            place_of_birth=data['place_of_birth'],
            gender=data['gender'],
            cni_or_passport_number=data['cni_or_passport_number'],
            nationality=data['nationality'],
            region_of_residence=data['region_of_residence'],
            current_structure=data.get('current_structure', ''),
            education_level=data.get('education_level', ''),
            computer_skills=data['computer_skills'],
            available_for_10_months=data['available_for_10_months'],
            desired_training=data['desired_training'],
            accept_conditions=data['accept_conditions'],
            speciality=data.get('speciality', ''),
            is_working=data.get('is_working', False),
            contract_type=data.get('contract_type', '')
        )
        
        candidature.save()
        return jsonify(
            message="Candidature enregistrée avec succès",
            candidature_id=str(candidature.id)
        ), 201

    except ValidationError as e:
        return jsonify(error=f"Erreur de validation des données : {str(e)}"), 400
    except Exception as e:
        return jsonify(error=f"Erreur inconnue : {str(e)}"), 500
    
@candidature_public_bp.route('/check-unique', methods=['GET'])
def check_unique():
    field = request.args.get('field')
    value = request.args.get('value')
    
    if not field or not value:
        return jsonify(error="Les paramètres field et value sont requis"), 400
    
    if field not in ['email', 'cni_or_passport_number']:
        return jsonify(error="Champ non valide pour vérification"), 400
    
    exists = False
    if field == 'email':
        exists = Candidature.objects(email=value).first() is not None
    elif field == 'cni_or_passport_number':
        exists = Candidature.objects(cni_or_passport_number=value).first() is not None
    
    return jsonify(exists=exists)

# ==================== ROUTES ADMIN ====================

@candidature_bp.route('/candidatures', methods=['GET'])
def get_all_candidatures():
    """Récupérer toutes les candidatures avec filtres"""
    try:
        # Paramètres de filtre
        desired_training = request.args.get('desired_training')
        status = request.args.get('status')
        search = request.args.get('search', '')
        
        # Construction de la requête
        query = {}
        if desired_training and desired_training != 'all':
            query['desired_training'] = desired_training
        if status and status != 'all':
            query['status'] = status
        
        candidatures = Candidature.objects(**query)
        
        # Recherche par nom, email, ou téléphone
        if search:
            candidatures = candidatures.filter(
                __raw__={
                    '$or': [
                        {'first_name': {'$regex': search, '$options': 'i'}},
                        {'last_name': {'$regex': search, '$options': 'i'}},
                        {'email': {'$regex': search, '$options': 'i'}},
                        {'phone': {'$regex': search, '$options': 'i'}}
                    ]
                }
            )
        
        # Trier par date de création (plus récentes en premier)
        candidatures = candidatures.order_by('-created_at')
        
        return jsonify({
            'success': True,
            'data': [c.to_dict() for c in candidatures],
            'total': candidatures.count()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des candidatures : {str(e)}"
        }), 500

@candidature_bp.route('/candidatures/<candidature_id>', methods=['GET'])
def get_candidature(candidature_id):
    """Récupérer une candidature spécifique"""
    try:
        candidature = Candidature.objects(id=candidature_id).first()
        if not candidature:
            return jsonify({
                'success': False,
                'error': 'Candidature non trouvée'
            }), 404
        
        return jsonify({
            'success': True,
            'data': candidature.to_dict()
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Candidature non trouvée'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération de la candidature : {str(e)}"
        }), 500

@candidature_bp.route('/candidatures/<candidature_id>', methods=['PATCH', 'PUT'])
def update_candidature(candidature_id):
    """Mettre à jour une candidature"""
    try:
        candidature = Candidature.objects(id=candidature_id).first()
        if not candidature:
            return jsonify({
                'success': False,
                'error': 'Candidature non trouvée'
            }), 404
        
        data = request.get_json()
        
        # Mettre à jour les champs autorisés
        allowed_fields = [
            'status', 'admin_notes', 'interview_date', 'score',
            'first_name', 'last_name', 'phone', 'email',
            'desired_training', 'region_of_residence'
        ]
        
        for field in allowed_fields:
            if field in data:
                setattr(candidature, field, data[field])
        
        candidature.updated_at = datetime.utcnow()
        candidature.save()
        
        return jsonify({
            'success': True,
            'message': 'Candidature mise à jour avec succès',
            'data': candidature.to_dict()
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Candidature non trouvée'
        }), 404
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour : {str(e)}"
        }), 500

@candidature_bp.route('/candidatures/<candidature_id>', methods=['DELETE'])
def delete_candidature(candidature_id):
    """Supprimer une candidature"""
    try:
        candidature = Candidature.objects(id=candidature_id).first()
        if not candidature:
            return jsonify({
                'success': False,
                'error': 'Candidature non trouvée'
            }), 404
        
        candidature.delete()
        
        return jsonify({
            'success': True,
            'message': 'Candidature supprimée avec succès'
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Candidature non trouvée'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la suppression : {str(e)}"
        }), 500

@candidature_bp.route('/candidatures/statistics', methods=['GET'])
def get_statistics():
    """Récupérer les statistiques des candidatures"""
    try:
        desired_training = request.args.get('desired_training')
        
        query = {}
        if desired_training and desired_training != 'all':
            query['desired_training'] = desired_training
        
        candidatures = Candidature.objects(**query)
        
        total = candidatures.count()
        pending = candidatures.filter(status='pending').count()
        accepted = candidatures.filter(status='accepted').count()
        rejected = candidatures.filter(status='rejected').count()
        interview = candidatures.filter(status='interview').count()
        
        # Statistiques par référentiel
        referentiel_stats = {}
        for ref in ['Dev Web', 'Data', 'Hackeuse', 'AWS', 'Design UX/UI']:
            ref_candidatures = Candidature.objects(desired_training=ref)
            referentiel_stats[ref] = {
                'total': ref_candidatures.count(),
                'pending': ref_candidatures.filter(status='pending').count(),
                'accepted': ref_candidatures.filter(status='accepted').count(),
                'rejected': ref_candidatures.filter(status='rejected').count(),
                'interview': ref_candidatures.filter(status='interview').count()
            }
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'pending': pending,
                'accepted': accepted,
                'rejected': rejected,
                'interview': interview,
                'referentielStats': referentiel_stats
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500

@candidature_bp.route('/candidatures/send-emails', methods=['POST'])
def send_emails_to_candidates():
    """Envoyer des emails aux candidats sélectionnés"""
    try:
        data = request.get_json()
        
        email_type = data.get('emailType')
        candidate_ids = data.get('candidateIds', [])
        custom_message = data.get('customMessage', '')
        
        if not candidate_ids:
            return jsonify({
                'success': False,
                'error': 'Aucun candidat sélectionné'
            }), 400
        
        # Récupérer les candidats
        candidatures = Candidature.objects(id__in=candidate_ids)
        
        # Simulation d'envoi d'emails (à remplacer par un vrai service d'email)
        email_type_labels = {
            'interview_invitation': "d'invitation à l'entretien",
            'acceptance': "d'acceptation",
            'rejection': "de refus",
            'information': "d'information"
        }
        
        message = f"Email {email_type_labels.get(email_type, '')} envoyé à {candidatures.count()} candidat(s)"
        
        print(f"=== Simulation d'envoi d'emails ===")
        print(f"Type: {email_type}")
        print(f"Candidats: {[c.email for c in candidatures]}")
        print(f"Message personnalisé: {custom_message}")
        print(f"===================================")
        
        return jsonify({
            'success': True,
            'message': message,
            'data': {
                'sent': candidatures.count(),
                'type': email_type,
                'timestamp': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de l'envoi des emails : {str(e)}"
        }), 500