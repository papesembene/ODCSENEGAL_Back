from flask import Blueprint, request, jsonify
import logging
from app.utils.auth_decorators import admin_required
from app.services.tests.test_management_service import (
    TestManagementService,
    TestServiceError,
)
from app.services.tests.test_access_service import (
    TestAccessError,
    TestAccessService,
)

logger = logging.getLogger(__name__)

test_bp = Blueprint("test", __name__)
test_management_service = TestManagementService()
test_access_service = TestAccessService()


def build_candidate_error(message, status_code):
    return jsonify({
        "success": False,
        "authorized": False,
        "error": message,
    }), status_code


def test_service_error_response(error):
    payload = {
        "success": False,
        "error": str(error),
        **error.details,
    }
    return jsonify(payload), error.status_code


@test_bp.route('/tests', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_all_tests():
    """Récupérer tous les tests"""
    try:
        return jsonify({
            'success': True,
            'data': test_management_service.list_tests(),
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des tests : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['GET'])
def get_test(test_id):
    """Récupérer un test spécifique par son ID"""
    try:
        test = test_management_service.get_test(test_id)
        return jsonify({
            'success': True,
            'data': test.to_dict()
        }), 200
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests', methods=['POST'])
@admin_required({'competences', 'super_admin'})
def create_test():
    """Créer un nouveau test"""
    try:
        test = test_management_service.create_test(
            request.get_json() or {},
        )
        return jsonify({
            'success': True,
            'message': 'Test créé avec succès',
            'data': test.to_dict()
        }), 201
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la création du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['PUT', 'PATCH'])
@admin_required({'competences', 'super_admin'})
def update_test(test_id):
    """Mettre à jour un test existant"""
    try:
        test = test_management_service.update_test(
            test_id,
            request.get_json() or {},
        )
        return jsonify({
            'success': True,
            'message': 'Test mis à jour avec succès',
            'data': test.to_dict()
        }), 200
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['DELETE'])
@admin_required({'competences', 'super_admin'})
def delete_test(test_id):
    """Supprimer un test"""
    try:
        test_management_service.delete_test(test_id)
        return jsonify({
            'success': True,
            'message': 'Test supprimé avec succès'
        }), 200
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la suppression du test : {str(e)}"
        }), 500
 
# ==================== GESTION DES RÉSULTATS ====================
 
@test_bp.route('/tests/results', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_all_results():
    """Récupérer tous les résultats des tests"""
    try:
        return jsonify({
            'success': True,
            'data': test_management_service.list_results({
                'testId': request.args.get('testId'),
                'referentiel': request.args.get('referentiel'),
                'status': request.args.get('status'),
            }),
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des résultats : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results/<result_id>', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_result(result_id):
    """Récupérer un résultat spécifique"""
    try:
        result = test_management_service.get_result(result_id)
        return jsonify({
            'success': True,
            'data': result.to_dict()
        }), 200
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du résultat : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results', methods=['POST'])
def submit_result():
    """Soumettre un résultat de test - Optimisé pour 42k candidats avec pics de 10k soumissions"""
    try:
        payload = request.get_json() or {}
        candidate = payload.get("candidate") or {}
        test_access_service.validate_submission(
            payload.get("testId"),
            candidate.get("email"),
            candidate.get("phone"),
            request.remote_addr or "unknown",
        )
        result = test_management_service.submit_result(payload)
        return jsonify({
            'success': True,
            'message': 'Résultat enregistré avec succès',
            'data': result.to_dict()
        }), 201
    except TestAccessError as error:
        return build_candidate_error(str(error), error.status_code)
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        # Log l'erreur pour debugging
        import logging
        logging.error(f"Erreur lors de la soumission du résultat: {str(e)}", exc_info=True)
       
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la soumission du résultat : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results/<result_id>', methods=['PUT', 'PATCH'])
@admin_required({'competences', 'super_admin'})
def update_result(result_id):
    """Mettre à jour un résultat (ex: notes manuelles, statut)"""
    try:
        result = test_management_service.update_result(
            result_id,
            request.get_json() or {},
        )
        return jsonify({
            'success': True,
            'message': 'Résultat mis à jour avec succès',
            'data': result.to_dict()
        }), 200
    except TestServiceError as error:
        return test_service_error_response(error)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour du résultat : {str(e)}"
        }), 500
 
# ==================== STATISTIQUES ====================
 
@test_bp.route('/tests/statistics', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_statistics():
    """Récupérer les statistiques des tests"""
    try:
        return jsonify({
            'success': True,
            'data': test_management_service.get_statistics(
                request.args.get('referentiel'),
            ),
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500
 
@test_bp.route('/tests/performance-stats', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_performance_stats():
    """Récupérer les statistiques de performance par référentiel et taux de réussite"""
    try:
        return jsonify({
            'success': True,
            'data': test_management_service.get_performance_statistics(),
        }), 200
       
    except Exception as e:
        logger.exception(
            "Erreur lors de la récupération des statistiques de performance"
        )
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500
 
# ==================== ENVOI D'EMAILS (simulation) ====================
 
@test_bp.route('/tests/send-emails', methods=['POST'])
@admin_required({'competences', 'super_admin'})
def send_emails():
    """Envoyer des emails aux candidats (simulation)"""
    try:
        data = request.get_json()
       
        email_type = data.get('emailType')
        recipients = data.get('recipients', [])
        test_details = data.get('testDetails')
        time_slot = data.get('timeSlot', '')
        custom_message = data.get('customMessage', '')
       
        # Simulation d'envoi d'emails
        # En production, utiliser un service d'email comme SendGrid, Mailgun, etc.
       
        email_type_labels = {
            'invitation': "d'invitation",
            'reminder': "de rappel",
            'results_selected': "de résultats (sélectionné)",
            'results_not_selected': "de résultats (non sélectionné)",
            'documents_reminder': "de rappel documents",
            'opening_announcement': "d'annonce de rentrée"
        }
       
        message = f"Email {email_type_labels.get(email_type, '')} envoyé à {len(recipients)} candidat(s)"
        if time_slot:
            message += f" (Créneau: {time_slot})"
       
        return jsonify({
            'success': True,
            'message': message
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de l'envoi des emails : {str(e)}"
        }), 500
 
# ==================== VÉRIFICATION D'ACCÈS ET LOGS ====================
 
@test_bp.route('/tests/<test_id>/verify-access', methods=['POST'])
def verify_test_access(test_id):
    try:
        ip = request.remote_addr or "unknown"
        data = request.get_json(silent=True) or {}
        access = test_access_service.verify(
            test_id,
            data.get("email"),
            data.get("phone"),
            ip,
        )
        return jsonify({
            "success": True,
            "authorized": True,
            **access,
        }), 200
    except TestAccessError as error:
        return build_candidate_error(str(error), error.status_code)
    except Exception as error:
        logger.error(
            "Internal access error test_id=%s ip=%s error=%s",
            test_id,
            request.remote_addr,
            error,
        )
        return jsonify({
            "success": False,
            "error": "Erreur interne"
        }), 500
 
@test_bp.route('/tests/<test_id>/public', methods=['GET'])
def get_public_test_metadata(test_id):
    """Récupérer uniquement les métadonnées publiques nécessaires avant le début du test"""
    try:
        return jsonify({
            'success': True,
            'data': test_access_service.get_public_metadata(test_id),
        }), 200
    except TestAccessError as error:
        return jsonify({
            'success': False,
            'error': str(error),
        }), error.status_code
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>/update-status', methods=['POST'])
def update_test_status_auto(test_id):
    """Mettre à jour automatiquement le statut du test si la durée est dépassée"""
    try:
        message, status = test_access_service.update_status(test_id)
        return jsonify({
            'success': True,
            'message': message,
            'status': status,
        }), 200
    except TestAccessError as error:
        return jsonify({
            'success': False,
            'error': str(error),
        }), error.status_code
    except RuntimeError as error:
        return jsonify({
            'success': False,
            'error': str(error),
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour : {str(e)}"
        }), 500
