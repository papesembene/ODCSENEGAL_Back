from flask import Blueprint, request, jsonify
from app.models.test_violation import TestViolation
from datetime import datetime

test_violation_bp = Blueprint('test_violations', __name__)

@test_violation_bp.route('/tests/<test_id>/log-violation', methods=['POST'])
def log_violation(test_id):
    """
    Enregistre une violation anti-triche pour un candidat
    Crée un nouveau document ou met à jour le document existant
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'Données manquantes'}), 400
        
        candidate_email = data.get('candidateEmail')
        violation_type = data.get('type')
        message = data.get('message')
        elapsed_time = data.get('elapsedTime')
        
        if not candidate_email or not violation_type or not message:
            return jsonify({
                'success': False, 
                'error': 'Email, type et message sont requis'
            }), 400
        
        # Chercher ou créer le document de violations pour ce test/candidat
        test_violation = TestViolation.objects(
            testId=test_id,
            candidateEmail=candidate_email
        ).first()
        
        if not test_violation:
            # Créer un nouveau document
            test_violation = TestViolation(
                testId=test_id,
                candidateEmail=candidate_email,
                metadata=data.get('metadata', {})
            )
        
        # Ajouter la violation
        test_violation.add_violation(violation_type, message, elapsed_time)
        test_violation.save()
        
        return jsonify({
            'success': True,
            'message': 'Violation enregistrée',
            'data': {
                'totalViolations': test_violation.totalViolations,
                'stats': test_violation.stats
            }
        }), 201
        
    except Exception as e:
        print(f"Erreur lors de l'enregistrement de la violation: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500


@test_violation_bp.route('/tests/<test_id>/violations', methods=['GET'])
def get_test_violations(test_id):
    """
    Récupère toutes les violations pour un test donné
    """
    try:
        violations = TestViolation.objects(testId=test_id).all()
        
        return jsonify({
            'success': True,
            'data': [v.to_dict() for v in violations],
            'count': len(violations)
        }), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des violations: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500


@test_violation_bp.route('/tests/<test_id>/violations/<candidate_email>', methods=['GET'])
def get_candidate_violations(test_id, candidate_email):
    """
    Récupère les violations d'un candidat spécifique pour un test
    """
    try:
        violation_doc = TestViolation.objects(
            testId=test_id,
            candidateEmail=candidate_email
        ).first()
        
        if not violation_doc:
            return jsonify({
                'success': True,
                'data': None,
                'message': 'Aucune violation enregistrée'
            }), 200
        
        return jsonify({
            'success': True,
            'data': violation_doc.to_dict()
        }), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des violations du candidat: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500


@test_violation_bp.route('/violations/all', methods=['GET'])
def get_all_violations():
    """
    Récupère toutes les violations de tous les tests
    Utilisé pour l'affichage dans la page admin
    """
    try:
        violations = TestViolation.objects.all()
        
        return jsonify({
            'success': True,
            'data': [v.to_dict() for v in violations],
            'count': len(violations)
        }), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération de toutes les violations: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500


@test_violation_bp.route('/tests/<test_id>/violations/<candidate_email>', methods=['DELETE'])
def delete_candidate_violations(test_id, candidate_email):
    """
    Supprime toutes les violations d'un candidat pour un test
    """
    try:
        violation_doc = TestViolation.objects(
            testId=test_id,
            candidateEmail=candidate_email
        ).first()
        
        if not violation_doc:
            return jsonify({
                'success': False,
                'error': 'Aucune violation trouvée'
            }), 404
        
        violation_doc.delete()
        
        return jsonify({
            'success': True,
            'message': 'Violations supprimées'
        }), 200
        
    except Exception as e:
        print(f"Erreur lors de la suppression des violations: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500
