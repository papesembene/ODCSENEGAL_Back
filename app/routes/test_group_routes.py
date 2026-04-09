from flask import Blueprint, request, jsonify, current_app
from mongoengine.errors import ValidationError, DoesNotExist
from datetime import datetime

# Import avec gestion d'erreur pour éviter les problèmes d'import
try:
    from app.models.test_group import TestGroup
    from app.models.candidature import Candidature
    from app.models.test import Test
    from app.services.test_email_service import TestEmailService
    MODELS_AVAILABLE = True
except ImportError as e:
    # Si l'import échoue, on marque que les modèles ne sont pas disponibles
    print(f"⚠️  Avertissement: Les modèles de test_group ne peuvent pas être importés: {str(e)}")
    MODELS_AVAILABLE = False
    # Créer des variables None pour éviter les erreurs de référence
    TestGroup = None
    Candidature = None
    Test = None
    TestEmailService = None

test_group_bp = Blueprint("test_group", __name__)

# Décorateur pour vérifier la disponibilité des modèles
def require_models(f):
    """Décorateur pour vérifier que les modèles sont disponibles"""
    def wrapper(*args, **kwargs):
        if not MODELS_AVAILABLE:
            return jsonify({
                'success': False,
                'error': 'Les modèles de tests ne sont pas disponibles. Veuillez vérifier la configuration.'
            }), 503
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==================== ROUTES ADMIN ====================

@test_group_bp.route('/test-groups', methods=['GET'])
@require_models
def get_all_test_groups():
    """Récupérer tous les groupes de tests avec filtres"""
    try:
        # Paramètres de filtre
        formation = request.args.get('formation')
        status = request.args.get('status')
        
        # Construction de la requête
        query = {}
        if formation and formation != 'all':
            query['formation'] = formation
        if status and status != 'all':
            query['status'] = status
        
        groups = TestGroup.objects(**query).order_by('-created_at')
        
        # Enrichir avec les informations des candidats
        result = []
        for group in groups:
            group_dict = group.to_dict()
            
            # Récupérer les infos des candidats
            if group.candidate_ids:
                candidates = Candidature.objects(id__in=group.candidate_ids)
                group_dict['candidates'] = [
                    {
                        'id': str(c.id),
                        'first_name': c.first_name,
                        'last_name': c.last_name,
                        'email': c.email,
                        'phone': c.phone,
                    }
                    for c in candidates
                ]
            else:
                group_dict['candidates'] = []
            
            result.append(group_dict)
        
        return jsonify({
            'success': True,
            'data': result,
            'total': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des groupes : {str(e)}"
        }), 500


@test_group_bp.route('/test-groups', methods=['POST'])

@require_models
def create_test_group():
    """Créer un nouveau groupe de test"""
    try:
        data = request.get_json()
        
        # Validation
        required_fields = ['name', 'formation', 'test_date', 'candidate_ids']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({
                    'success': False,
                    'error': f"Le champ {field} est requis"
                }), 400
        
        # Vérifier que les candidats existent
        candidate_count = Candidature.objects(id__in=data['candidate_ids']).count()
        if candidate_count != len(data['candidate_ids']):
            return jsonify({
                'success': False,
                'error': "Certains candidats n'existent pas"
            }), 400
        
        # Créer le groupe
        group = TestGroup(
            name=data['name'],
            formation=data['formation'],
            test_id=data.get('test_id'),
            test_date=datetime.fromisoformat(data['test_date'].replace('Z', '+00:00')),
            duration=data.get('duration', 60),
            candidate_ids=data['candidate_ids'],
            location=data.get('location', ''),
            instructions=data.get('instructions', ''),
            status='pending',
            created_by=data.get('created_by', 'admin')
        )
        
        group.save()
        
        # Si un test_id est fourni, assigner le groupe au test
        if data.get('test_id'):
            test = Test.objects(id=data['test_id']).first()
            if test:
                test.candidatesGroup = str(group.id)
                test.save()
                print(f"DEBUG: Test {data['test_id']} assigné au groupe {group.id} lors de la création")
        
        return jsonify({
            'success': True,
            'message': 'Groupe créé avec succès',
            'data': group.to_dict()
        }), 201
        
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la création du groupe : {str(e)}"
        }), 500


@test_group_bp.route('/test-groups/<group_id>', methods=['GET'])

@require_models
def get_test_group(group_id):
    """Récupérer un groupe spécifique"""
    try:
        group = TestGroup.objects(id=group_id).first()
        if not group:
            return jsonify({
                'success': False,
                'error': 'Groupe non trouvé'
            }), 404
        
        group_dict = group.to_dict()
        
        # Récupérer les infos complètes des candidats
        if group.candidate_ids:
            candidates = Candidature.objects(id__in=group.candidate_ids)
            group_dict['candidates'] = [c.to_dict() for c in candidates]
        else:
            group_dict['candidates'] = []
        
        return jsonify({
            'success': True,
            'data': group_dict
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Groupe non trouvé'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du groupe : {str(e)}"
        }), 500


@test_group_bp.route('/test-groups/<group_id>', methods=['PATCH', 'PUT'])
@require_models
def update_test_group(group_id):
    """Mettre à jour un groupe"""
    try:
        group = TestGroup.objects(id=group_id).first()
        if not group:
            return jsonify({
                'success': False,
                'error': 'Groupe non trouvé'
            }), 404
        
        data = request.get_json()
        
        # Si on assigne un test_id, mettre à jour aussi le test avec le candidatesGroup
        old_test_id = group.test_id
        if 'test_id' in data:
            new_test_id = data['test_id']
            
            # Retirer l'ancien test du groupe (si différent)
            if old_test_id and old_test_id != new_test_id:
                old_test = Test.objects(id=old_test_id).first()
                if old_test and old_test.candidatesGroup == str(group.id):
                    old_test.candidatesGroup = ''
                    old_test.save()
            
            # Assigner le nouveau test au groupe
            group.test_id = new_test_id
            if new_test_id:
                new_test = Test.objects(id=new_test_id).first()
                if new_test:
                    new_test.candidatesGroup = str(group.id)
                    new_test.save()
                    print(f"DEBUG: Test {new_test_id} assigné au groupe {group_id}")
                else:
                    print(f"DEBUG: Test {new_test_id} non trouvé")
            else:
                # Si test_id est vide, retirer le groupe du test
                if old_test_id:
                    old_test = Test.objects(id=old_test_id).first()
                    if old_test and old_test.candidatesGroup == str(group.id):
                        old_test.candidatesGroup = ''
                        old_test.save()
        
        # Mettre à jour les champs autorisés
        if 'name' in data:
            group.name = data['name']
        if 'formation' in data:
            group.formation = data['formation']
        if 'test_date' in data:
            group.test_date = datetime.fromisoformat(data['test_date'].replace('Z', '+00:00'))
        if 'duration' in data:
            group.duration = data['duration']
        if 'candidate_ids' in data:
            group.candidate_ids = data['candidate_ids']
        if 'location' in data:
            group.location = data['location']
        if 'instructions' in data:
            group.instructions = data['instructions']
        if 'status' in data:
            group.status = data['status']
        
        group.updated_at = datetime.utcnow()
        group.save()
        
        return jsonify({
            'success': True,
            'message': 'Groupe mis à jour avec succès',
            'data': group.to_dict()
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Groupe non trouvé'
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


@test_group_bp.route('/test-groups/<group_id>', methods=['DELETE'])
@require_models
def delete_test_group(group_id):
    """Supprimer un groupe"""
    try:
        group = TestGroup.objects(id=group_id).first()
        if not group:
            return jsonify({
                'success': False,
                'error': 'Groupe non trouvé'
            }), 404
        
        group.delete()
        
        return jsonify({
            'success': True,
            'message': 'Groupe supprimé avec succès'
        }), 200
        
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Groupe non trouvé'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la suppression : {str(e)}"
        }), 500


@test_group_bp.route('/test-groups/<group_id>/send-invitations', methods=['POST'])
@require_models
def send_test_invitations(group_id):
    """Envoyer les invitations aux candidats d'un groupe via SendGrid"""
    try:
        group = TestGroup.objects(id=group_id).first()
        if not group:
            return jsonify({
                'success': False,
                'error': 'Groupe non trouvé'
            }), 404
        
        # Récupérer le test associé au groupe
        test = None
        test_title = "Test en ligne"
        if group.test_id:
            test = Test.objects(id=group.test_id).first()
            if test:
                test_title = test.title
        
        # Récupérer les candidats
        candidates = list(Candidature.objects(id__in=group.candidate_ids))
        
        if not candidates:
            return jsonify({
                'success': False,
                'error': 'Aucun candidat trouvé dans ce groupe'
            }), 400
        
        # Préparer les informations du test
        test_date = group.test_date.strftime('%d/%m/%Y') if hasattr(group.test_date, 'strftime') else str(group.test_date)
        test_time = group.test_date.strftime('%H:%M') if hasattr(group.test_date, 'strftime') else '09:00'
        test_duration = group.duration if group.duration else 60
        
        # Construire le lien du test
        frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
        if test:
            test_link = f"{frontend_url}/test/{str(test.id)}"
        else:
            test_link = f"{frontend_url}/test"
        
        # Envoyer les emails via SendGrid
        email_service = TestEmailService()
        result = email_service.send_bulk_invitations(
            candidates=candidates,
            test_title=test_title,
            test_date=test_date,
            test_time=test_time,
            test_duration=test_duration,
            test_link=test_link
        )
        
        # Marquer comme envoyé
        group.email_sent = datetime.utcnow()
        group.status = 'scheduled'
        group.save()
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': f"Invitations envoyées avec succès à {result['sent']} candidat(s)",
                'data': {
                    'sent': result['sent'],
                    'failed': result['failed'],
                    'timestamp': group.email_sent.isoformat()
                }
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': f"Invitations partiellement envoyées : {result['sent']} succès, {result['failed']} échecs",
                'data': {
                    'sent': result['sent'],
                    'failed': result['failed'],
                    'failed_emails': result.get('failed_emails', []),
                    'timestamp': group.email_sent.isoformat()
                }
            }), 207  # 207 Multi-Status
        
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi des invitations : {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f"Erreur lors de l'envoi des invitations : {str(e)}"
        }), 500


@test_group_bp.route('/test-groups/statistics', methods=['GET'])
@require_models
def get_test_groups_statistics():
    """Récupérer les statistiques des groupes de tests"""
    try:
        formation = request.args.get('formation')
        
        query = {}
        if formation and formation != 'all':
            query['formation'] = formation
        
        groups = TestGroup.objects(**query)
        
        total = groups.count()
        pending = groups.filter(status='pending').count()
        scheduled = groups.filter(status='scheduled').count()
        completed = groups.filter(status='completed').count()
        cancelled = groups.filter(status='cancelled').count()
        
        # Candidats totaux
        total_candidates = 0
        for group in groups:
            total_candidates += len(group.candidate_ids) if group.candidate_ids else 0
        
        # Statistiques par formation
        formation_stats = {}
        for form in ['Dev Web', 'Data', 'Hackeuse', 'AWS', 'Design UX/UI', 'Cyber security', 'Intelligence Artificielle']:
            form_groups = TestGroup.objects(formation=form)
            candidates_count = 0
            for g in form_groups:
                candidates_count += len(g.candidate_ids) if g.candidate_ids else 0
            
            formation_stats[form] = {
                'total_groups': form_groups.count(),
                'total_candidates': candidates_count,
                'pending': form_groups.filter(status='pending').count(),
                'scheduled': form_groups.filter(status='scheduled').count(),
                'completed': form_groups.filter(status='completed').count(),
            }
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'pending': pending,
                'scheduled': scheduled,
                'completed': completed,
                'cancelled': cancelled,
                'total_candidates': total_candidates,
                'formationStats': formation_stats
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500
