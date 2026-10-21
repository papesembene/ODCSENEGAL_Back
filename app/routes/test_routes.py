from flask import Blueprint, Response, abort, g, request, jsonify, stream_with_context
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
from app.services.tests.test_session_service import (
    TestSessionService,
    TestSessionServiceError,
)

logger = logging.getLogger(__name__)

test_bp = Blueprint("test", __name__)
test_management_service = TestManagementService()
test_access_service = TestAccessService()
test_session_service = TestSessionService()


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


@test_bp.route('/tests/sessions', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def get_test_sessions():
    try:
        payload = test_session_service.list_admin_sessions({
            "status": request.args.get("status"),
            "testId": request.args.get("testId"),
            "search": request.args.get("search"),
            "page": request.args.get("page"),
            "per_page": request.args.get("per_page"),
        })
        return jsonify({
            "success": True,
            **payload,
        }), 200
    except TestSessionServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    except Exception:
        logger.exception("Erreur lors de la récupération des sessions de test")
        return jsonify({
            "success": False,
            "error": "Erreur lors de la récupération des sessions de test",
        }), 500


@test_bp.route('/tests/sessions/<session_id>/reschedule', methods=['PATCH'])
@admin_required({'competences', 'super_admin'})
def mark_test_session_for_reschedule(session_id):
    try:
        session = test_session_service.mark_for_reschedule(session_id)
        return jsonify({
            "success": True,
            "message": "Session marquée à reprogrammer",
            "data": session.to_dict(),
        }), 200
    except TestSessionServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    except Exception:
        logger.exception("Erreur lors du marquage à reprogrammer")
        return jsonify({
            "success": False,
            "error": "Erreur lors du marquage à reprogrammer",
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['GET'])
@admin_required({'competences', 'super_admin'})
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


@test_bp.route('/tests/<test_id>/content', methods=['POST'])
def get_candidate_test_content(test_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return build_candidate_error("Donnees invalides", 400)
    try:
        test_access_service.content_access(
            test_id, payload.get("email"), payload.get("phone"), request.remote_addr or "unknown",
        )
        test = test_management_service.get_test(test_id)
        content = {field: getattr(test, field) for field in (
            "title", "referentiel", "duration", "scheduledDate", "scheduledTime",
            "totalQuestions", "passingScore", "description", "status",
        )}
        content["id"] = str(test.id)
        content["questions"] = [{
            "question": question.question, "type": question.type,
            "options": question.options, "score": question.score, "image": question.image,
        } for question in test.questions]
        response = jsonify({"success": True, "data": content})
        response.headers["Cache-Control"] = "no-store"
        return response
    except TestAccessError as error:
        return build_candidate_error(str(error), error.status_code)
    except TestServiceError as error:
        return test_service_error_response(error)
 
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
        test_access_service.cache.invalidate(test_id)
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
        test_access_service.cache.invalidate(test_id)
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
    """Return a bounded page; candidate answers are loaded separately."""
    from app.services.tests.test_result_queries import TestResultQueries
    try:
        response = jsonify(success=True, **TestResultQueries.page(request.args))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des résultats : {str(e)}"
        }), 500


@test_bp.route('/tests/results/export', methods=['GET'])
@admin_required({'competences', 'super_admin'})
def export_results():
    from app.services.tests.test_result_queries import TestResultQueries
    try:
        stream = TestResultQueries.export(request.args)
        return Response(stream_with_context(stream), content_type='text/csv; charset=utf-8', headers={
            'Content-Disposition': 'attachment; filename="resultats-tests.csv"', 'Cache-Control': 'no-store',
        })
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
 
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
 
@test_bp.route('/tests/results/import', methods=['POST'])
@admin_required({'competences', 'super_admin'})
def import_test_result():
    if (getattr(g.current_admin, "profile_data", None) or {}).get("admin_scope") == "interview_member":
        abort(403)
    payload = request.get_json(silent=True) or {}
    try:
        result, created = test_management_service.submit_result(payload, trusted_import=True)
        test_session_service.mark_submitted(payload["testId"], payload["candidate"]["email"], payload["candidate"])
        return jsonify({"success": True, "idempotent": not created, "data": result.to_dict()}), 201 if created else 200
    except TestServiceError as error:
        return test_service_error_response(error)


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
        result, created = test_management_service.submit_result(payload)
        test_session_service.mark_submitted(
            payload.get("testId"),
            (candidate.get("email") or "").strip().lower(),
            candidate,
        )
        logger.info(
            "Résultat test candidat confirmé",
            extra={
                "test_id": payload.get("testId"),
                "candidate_email": (candidate.get("email") or "").strip().lower(),
                "candidate_phone": (candidate.get("phone") or "").strip(),
                "test_session_status": "submitted",
                "idempotent": not created,
            },
        )
        return jsonify({
            'success': True,
            'message': (
                'Résultat enregistré avec succès'
                if created
                else 'Résultat déjà enregistré'
            ),
            'idempotent': not created,
            'data': result.to_dict()
        }), 201 if created else 200
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


@test_bp.route('/tests/<test_id>/session-draft', methods=['GET'])
def get_test_session_draft(test_id):
    try:
        email = request.args.get("email")
        phone = request.args.get("phone")
        access = test_access_service.validate_draft(
            test_id,
            email,
            phone,
            request.remote_addr or "unknown",
        )
        draft = test_session_service.get_draft(
            test_id,
            access["candidate"]["email"],
        )
        return jsonify({
            "success": True,
            "data": draft.to_dict() if draft else None,
        }), 200
    except TestAccessError as error:
        return build_candidate_error(str(error), error.status_code)
    except TestSessionServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    except Exception as error:
        logger.error(
            "Internal draft read error test_id=%s ip=%s error=%s",
            test_id,
            request.remote_addr,
            error,
        )
        return jsonify({
            "success": False,
            "error": "Erreur lors de la lecture du brouillon",
        }), 500


@test_bp.route('/tests/<test_id>/session-draft', methods=['PUT'])
def save_test_session_draft(test_id):
    try:
        data = request.get_json(silent=True) or {}
        access = test_access_service.validate_draft(
            test_id,
            data.get("email"),
            data.get("phone"),
            request.remote_addr or "unknown",
        )
        draft = test_session_service.save_draft(test_id, data, access)
        logger.info(
            "Brouillon test candidat sauvegardé",
            extra={
                "test_id": test_id,
                "candidate_email": (data.get("email") or "").strip().lower(),
                "candidate_phone": (data.get("phone") or "").strip(),
                "test_session_status": "in_progress",
            },
        )
        return jsonify({
            "success": True,
            "message": "Brouillon sauvegardé",
            "data": draft.to_dict(),
        }), 200
    except TestAccessError as error:
        return build_candidate_error(str(error), error.status_code)
    except TestSessionServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    except Exception as error:
        logger.error(
            "Internal draft save error test_id=%s ip=%s error=%s",
            test_id,
            request.remote_addr,
            error,
        )
        return jsonify({
            "success": False,
            "error": "Erreur lors de la sauvegarde du brouillon",
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
 
# ==================== NOTIFICATIONS DE RESULTATS ====================
 
@test_bp.route('/tests/send-emails', methods=['POST'])
@admin_required({'competences', 'super_admin'})
def send_emails():
    """Queue real notifications without blocking the API on email delivery."""
    from app.services.result_notification_service import ResultNotificationService
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Corps JSON invalide")
        summary = ResultNotificationService().enqueue(data)
        return jsonify(success=True, queued=True, data=summary, message="Emails places en file d'attente"), 202
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400


@test_bp.route('/tests/notifications/<batch_id>/status', methods=['GET'])
@test_bp.route('/tests/notifications/<batch_id>/retry', methods=['POST'])
@admin_required({'competences', 'super_admin'})
def result_notification_status(batch_id):
    from app.services.result_notification_service import ResultNotificationService
    try:
        service = ResultNotificationService()
        summary = service.retry_failed(batch_id) if request.method == 'POST' else service.summary(batch_id)
        if not summary['total']:
            return jsonify(success=False, error="Envoi introuvable"), 404
        return jsonify(success=True, data=summary)
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
 
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
        response = jsonify({
            'success': True,
            'data': test_access_service.get_public_metadata(test_id),
        })
        response.headers["Cache-Control"] = (
            "public, max-age=60, stale-while-revalidate=300"
        )
        return response, 200
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
