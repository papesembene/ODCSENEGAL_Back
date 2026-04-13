from flask import Blueprint, request, jsonify
from mongoengine.errors import ValidationError, DoesNotExist
from datetime import datetime, timedelta
import re
import time
from collections import defaultdict
from bson import ObjectId
from bson.errors import InvalidId
import logging
 
# Configuration du logger pour ce module
logger = logging.getLogger(__name__)
 

# Import avec gestion d'erreur pour éviter les conflits avec le module standard 'test'
# Ces imports peuvent échouer, donc on les fait dans un try/except global
try:
    from app.models.test import Test, Question, ConnectionLog
    from app.models.test_result import TestResult, Candidate
    from app.models.test_group import TestGroup
    from app.models.candidature import Candidature
    from app.models.test_violation import TestViolation
    MODELS_AVAILABLE = True
except ImportError as e:
    # Si l'import échoue, on marque que les modèles ne sont pas disponibles
    # Le blueprint sera créé mais les routes nécessiteront les modèles
    print(f"⚠️  Avertissement: Les modèles de tests ne peuvent pas être importés: {str(e)}")
    MODELS_AVAILABLE = False
    # Créer des variables None pour éviter les erreurs de référence
    Test = None
    Question = None
    ConnectionLog = None
    TestResult = None
    Candidate = None
    TestGroup = None
    Candidature = None
    TestViolation = None
 
test_bp = Blueprint("test", __name__)
 
RATE_LIMIT = 5
RATE_WINDOW = 60  # secondes
rate_limit_store = defaultdict(list)
test_cache = {}
TEST_CACHE_TTL = 30  # secondes
 
# ==================== GESTION DES TESTS ====================
 
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
 
@test_bp.route('/tests', methods=['GET'])
@require_models
def get_all_tests():
    """Récupérer tous les tests"""
    try:
        tests = Test.objects()
        return jsonify({
            'success': True,
            'data': [test.to_dict() for test in tests]
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
        test = Test.objects(id=test_id).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test non trouvé'
            }), 404
       
        return jsonify({
            'success': True,
            'data': test.to_dict()
        }), 200
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Test non trouvé'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests', methods=['POST'])
def create_test():
    """Créer un nouveau test"""
    try:
        data = request.get_json()
       
        # Validation des champs obligatoires
        required_fields = ['title', 'referentiel', 'duration', 'scheduledDate', 'scheduledTime', 'passingScore']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f"Le champ {field} est requis"
                }), 400
       
        # Créer les questions
        questions = []
        if 'questions' in data and data['questions']:
            for q in data['questions']:
                question = Question(
                    question=q.get('question'),
                    type=q.get('type'),
                    options=q.get('options', []),
                    correctAnswer=q.get('correctAnswer'),
                    correctAnswers=q.get('correctAnswers', []),
                    score=q.get('score', 5),
                    image=q.get('image')
                )
                questions.append(question)
       
        # Créer le test
        test = Test(
            title=data['title'],
            referentiel=data['referentiel'],
            duration=data['duration'],
            scheduledDate=data['scheduledDate'],
            scheduledTime=data['scheduledTime'],
            totalQuestions=len(questions),
            passingScore=data['passingScore'],
            candidatesGroup=data.get('candidatesGroup', ''),
            description=data.get('description', ''),
            questions=questions,
            status=data.get('status', 'active'),
            createdBy=data.get('createdBy', '')
        )
       
        test.save()
       
        return jsonify({
            'success': True,
            'message': 'Test créé avec succès',
            'data': test.to_dict()
        }), 201
       
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la création du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['PUT', 'PATCH'])
def update_test(test_id):
    """Mettre à jour un test existant"""
    try:
        test = Test.objects(id=test_id).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test non trouvé'
            }), 404
       
        data = request.get_json()
       
        # Mettre à jour les champs simples
        if 'title' in data:
            test.title = data['title']
        if 'referentiel' in data:
            test.referentiel = data['referentiel']
        if 'duration' in data:
            test.duration = data['duration']
        if 'scheduledDate' in data:
            test.scheduledDate = data['scheduledDate']
        if 'scheduledTime' in data:
            test.scheduledTime = data['scheduledTime']
        if 'passingScore' in data:
            test.passingScore = data['passingScore']
        if 'candidatesGroup' in data:
            test.candidatesGroup = data['candidatesGroup']
        if 'description' in data:
            test.description = data['description']
        if 'status' in data:
            test.status = data['status']
       
        # Mettre à jour les questions si fournies
        if 'questions' in data:
            questions = []
            for q in data['questions']:
                question = Question(
                    question=q.get('question'),
                    type=q.get('type'),
                    options=q.get('options', []),
                    correctAnswer=q.get('correctAnswer'),
                    correctAnswers=q.get('correctAnswers', []),
                    score=q.get('score', 5),
                    image=q.get('image')
                )
                questions.append(question)
            test.questions = questions
            test.totalQuestions = len(questions)
       
        test.updatedAt = datetime.utcnow()
        test.updatedBy = data.get('updatedBy', '')
        test.save()
       
        return jsonify({
            'success': True,
            'message': 'Test mis à jour avec succès',
            'data': test.to_dict()
        }), 200
       
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Test non trouvé'
        }), 404
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour du test : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>', methods=['DELETE'])
def delete_test(test_id):
    """Supprimer un test"""
    try:
        test = Test.objects(id=test_id).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test non trouvé'
            }), 404
       
        test.delete()
       
        return jsonify({
            'success': True,
            'message': 'Test supprimé avec succès'
        }), 200
       
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Test non trouvé'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la suppression du test : {str(e)}"
        }), 500
 
# ==================== GESTION DES RÉSULTATS ====================
 
@test_bp.route('/tests/results', methods=['GET'])
def get_all_results():
    """Récupérer tous les résultats des tests"""
    try:
        # Filtres optionnels
        test_id = request.args.get('testId')
        referentiel = request.args.get('referentiel')
        status = request.args.get('status')
       
        # Construire la requête
        query = {}
        if test_id:
            query['testId'] = test_id
        if referentiel:
            query['referentiel'] = referentiel
        if status:
            query['status'] = status
       
        results = TestResult.objects(**query).order_by('-completedAt')
       
        return jsonify({
            'success': True,
            'data': [result.to_dict() for result in results]
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des résultats : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results/<result_id>', methods=['GET'])
def get_result(result_id):
    """Récupérer un résultat spécifique"""
    try:
        result = TestResult.objects(id=result_id).first()
        if not result:
            return jsonify({
                'success': False,
                'error': 'Résultat non trouvé'
            }), 404
       
        return jsonify({
            'success': True,
            'data': result.to_dict()
        }), 200
       
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Résultat non trouvé'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération du résultat : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results', methods=['POST'])
def submit_result():
    """Soumettre un résultat de test - Optimisé pour 42k candidats avec pics de 10k soumissions"""
    try:
        data = request.get_json()
       
        # Validation des champs obligatoires
        required_fields = ['testId', 'testTitle', 'referentiel', 'candidate', 'score']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f"Le champ {field} est requis"
                }), 400
       
        # Garder l'email tel quel (sans normalisation) mais faire une recherche insensible à la casse pour les doublons
        candidate_email = data['candidate']['email'].strip()
        email_pattern = re.compile(f'^{re.escape(candidate_email)}$', re.IGNORECASE)
       
        # Vérifier si le candidat a déjà passé ce test (check rapide avant insertion)
        # Recherche insensible à la casse pour éviter les doublons avec différentes casses
        existing_result = TestResult.objects(
            testId=data['testId'],
            candidate__email=email_pattern
        ).only('id').first()  # only('id') pour requête plus rapide
       
        if existing_result:
            return jsonify({
                'success': False,
                'error': 'Vous avez déjà passé ce test',
                'duplicate': True
            }), 409  # 409 Conflict au lieu de 400
       
        # Créer le candidat
        candidate = Candidate(
            name=data['candidate']['name'],
            email=candidate_email,  # Email conservé tel quel (sans normalisation)
            phone=data['candidate']['phone']
        )
       
        # Déterminer le statut basé sur le score
        passing_score = data.get('passingScore', 70)
        status = 'admis' if data['score'] >= passing_score else 'rejeté'
       
        # Créer le résultat
        result = TestResult(
            testId=data['testId'],
            testTitle=data['testTitle'],
            referentiel=data['referentiel'],
            candidate=candidate,
            answers=data.get('answers', {}),
            score=data['score'],
            status=status,
            submittedDate=data.get('submittedDate', ''),
            submittedTime=data.get('submittedTime', ''),
            manualGrades=data.get('manualGrades', {})
        )
       
        # Sauvegarder avec gestion d'erreur de duplication (race condition)
        try:
            result.save()
        except Exception as save_error:
            # Si erreur de duplication (index unique), vérifier à nouveau
            error_str = str(save_error).lower()
            if 'duplicate' in error_str or 'e11000' in error_str or 'duplicate key' in error_str:
                # Doublon détecté par MongoDB (race condition)
                # Recherche insensible à la casse
                existing_result = TestResult.objects(
                    testId=data['testId'],
                    candidate__email=email_pattern
                ).first()
               
                if existing_result:
                    return jsonify({
                        'success': False,
                        'error': 'Vous avez déjà passé ce test',
                        'duplicate': True
                    }), 409
            # Autre erreur, relancer
            raise save_error
       
        return jsonify({
            'success': True,
            'message': 'Résultat enregistré avec succès',
            'data': result.to_dict()
        }), 201
       
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        # Log l'erreur pour debugging
        import logging
        logging.error(f"Erreur lors de la soumission du résultat: {str(e)}", exc_info=True)
       
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la soumission du résultat : {str(e)}"
        }), 500
 
@test_bp.route('/tests/results/<result_id>', methods=['PUT', 'PATCH'])
def update_result(result_id):
    """Mettre à jour un résultat (ex: notes manuelles, statut)"""
    try:
        result = TestResult.objects(id=result_id).first()
        if not result:
            return jsonify({
                'success': False,
                'error': 'Résultat non trouvé'
            }), 404
       
        data = request.get_json()
       
        # Mettre à jour les champs
        if 'status' in data:
            result.status = data['status']
        if 'score' in data:
            result.score = data['score']
        if 'manualGrades' in data:
            result.manualGrades = data['manualGrades']
       
        result.save()
       
        return jsonify({
            'success': True,
            'message': 'Résultat mis à jour avec succès',
            'data': result.to_dict()
        }), 200
       
    except DoesNotExist:
        return jsonify({
            'success': False,
            'error': 'Résultat non trouvé'
        }), 404
    except ValidationError as e:
        return jsonify({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour du résultat : {str(e)}"
        }), 500
 
# ==================== STATISTIQUES ====================
 
@test_bp.route('/tests/statistics', methods=['GET'])
def get_statistics():
    """Récupérer les statistiques des tests"""
    try:
        referentiel = request.args.get('referentiel')
       
        # Construire la requête
        query = {}
        if referentiel:
            query['referentiel'] = referentiel
       
        results = TestResult.objects(**query)
       
        total = results.count()
        admis = results.filter(status='admis').count()
        rejetes = results.filter(status='rejeté').count()
        pending = results.filter(status='pending').count()
       
        # Calculer la moyenne des scores
        scores = [r.score for r in results]
        average_score = sum(scores) / len(scores) if scores else 0
       
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'admis': admis,
                'rejetes': rejetes,
                'pending': pending,
                'average_score': round(average_score, 2),
                'pass_rate': round((admis / total * 100) if total > 0 else 0, 2)
            }
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500
 
@test_bp.route('/tests/performance-stats', methods=['GET'])
def get_performance_stats():
    """Récupérer les statistiques de performance par référentiel et taux de réussite"""
    try:
        from collections import defaultdict
        from datetime import datetime, timedelta
       
        # Récupérer tous les résultats
        all_results = TestResult.objects()
       
        # Performance par référentiel
        referentiel_stats = defaultdict(lambda: {
            'total': 0,
            'admis': 0,
            'rejetes': 0,
            'pending': 0,
            'total_score': 0,
            'average_score': 0,
            'pass_rate': 0
        })
       
        for result in all_results:
            ref = result.referentiel or "Non spécifié"
            referentiel_stats[ref]['total'] += 1
            referentiel_stats[ref]['total_score'] += result.score or 0
           
            if result.status == 'admis':
                referentiel_stats[ref]['admis'] += 1
            elif result.status == 'rejeté':
                referentiel_stats[ref]['rejetes'] += 1
            else:
                referentiel_stats[ref]['pending'] += 1
       
        # Calculer les moyennes et taux de réussite
        performance_by_referentiel = []
        for ref, stats in referentiel_stats.items():
            if stats['total'] > 0:
                stats['average_score'] = round(stats['total_score'] / stats['total'], 2)
                stats['pass_rate'] = round((stats['admis'] / stats['total'] * 100), 2)
            performance_by_referentiel.append({
                'referentiel': ref,
                **stats
            })
       
        # Taux de réussite mensuel (6 derniers mois)
        monthly_pass_rate = []
        now = datetime.utcnow()
       
        for i in range(5, -1, -1):  # 6 derniers mois
            # Calculer le mois de début
            target_month = now.month - i
            target_year = now.year
           
            if target_month <= 0:
                target_month += 12
                target_year -= 1
           
            month_start = datetime(target_year, target_month, 1)
           
            # Calculer le mois de fin (mois suivant)
            if target_month == 12:
                month_end = datetime(target_year + 1, 1, 1)
            else:
                month_end = datetime(target_year, target_month + 1, 1)
           
            month_results = TestResult.objects(
                completedAt__gte=month_start,
                completedAt__lt=month_end
            )
           
            total_month = month_results.count()
            admis_month = month_results.filter(status='admis').count()
           
            # Noms des mois en français
            month_names_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
            month_name = month_names_fr[target_month - 1]
           
            pass_rate = round((admis_month / total_month * 100) if total_month > 0 else 0, 2)
           
            monthly_pass_rate.append({
                'mois': month_name,
                'taux': pass_rate,
                'total': total_month,
                'admis': admis_month
            })
       
        # Taux de réussite global
        total_all = all_results.count()
        admis_all = all_results.filter(status='admis').count()
        global_pass_rate = round((admis_all / total_all * 100) if total_all > 0 else 0, 2)
       
        return jsonify({
            'success': True,
            'data': {
                'performance_by_referentiel': performance_by_referentiel,
                'monthly_pass_rate': monthly_pass_rate,
                'global_pass_rate': global_pass_rate,
                'total_tests': total_all,
                'total_admis': admis_all
            }
        }), 200
       
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Erreur lors de la récupération des statistiques de performance: {str(e)}")
        print(f"Traceback: {error_trace}")
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
        }), 500
 
# ==================== ENVOI D'EMAILS (simulation) ====================
 
@test_bp.route('/tests/send-emails', methods=['POST'])
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
    email = "unknown"
    try:
        ip = request.remote_addr or "unknown"
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip()
 
        logger.debug(f"[START] Accès test {test_id} demandé par {ip}")
        print(f"DEBUG: [START] verify_test_access for {test_id}, email={email}")
 
        # =====================
        # RATE LIMIT
        # =====================
        if is_rate_limited(ip):
            logger.warning(f"[RATE LIMIT] Trop de tentatives pour IP={ip}")
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "⏳ Trop de tentatives, réessayez plus tard"
            }), 429
 
        # =====================
        # JSON SAFE READ
        # =====================
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip()
        logger.debug(f"[INPUT] email={email}, phone={phone}")
 
        if not email or not phone:
            logger.warning(f"[MISSING FIELDS] email={email}, phone={phone}")
            log_access_async(False, email, test_id, "missing_fields", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Email et numéro requis"
            }), 400
 
        # =====================
        # TEST ID VALIDATION
        # =====================
        try:
            test_oid = ObjectId(test_id)
        except InvalidId:
            logger.warning(f"[INVALID TEST ID] {test_id}")
            log_access_async(False, email, test_id, "invalid_test_id", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Identifiant de test invalide"
            }), 400
 
        # =====================
        # TEST (CACHE)
        # =====================
        test = get_test_cached(test_oid)
        if not test:
            logger.warning(f"[TEST NOT FOUND] test_id={test_id}")
            log_access_async(False, email, test_id, "test_not_found", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Test non trouvé"
            }), 404
        logger.debug(f"[TEST FOUND] {test.title} ({test.referentiel})")
 
        # =====================
        # CANDIDATURE (INDEX)
        # =====================
        candidature = Candidature.objects(email=email).only(
            "id", "first_name", "last_name", "email", "phone"
        ).first()
 
        if not candidature or not candidature.phone:
            logger.warning(f"[EMAIL/PHONE NOT FOUND] email={email}")
            log_access_async(False, email, test_id, "email_not_found", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Email ou numéro incorrect"
            }), 403
        logger.debug(f"[CANDIDATE FOUND] {candidature.first_name} {candidature.last_name} ({candidature.id})")
 
        # =====================
        # PHONE CHECK (O(1))
        # =====================
        def digits(p): return "".join(c for c in p if c.isdigit())
        stored = digits(candidature.phone)
        incoming = digits(phone)
 
        if stored != incoming and not stored.endswith(incoming):
            logger.warning(f"[PHONE MISMATCH] {stored} != {incoming}")
            log_access_async(False, email, test_id, "phone_mismatch", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Numéro incorrect"
            }), 403
        logger.debug(f"[PHONE OK] {stored}")
 
        # =====================
        # DÉJÀ PASSÉ ?
        # =====================
        if TestResult.objects(testId=str(test.id), candidate__email=email).only("id").first():
            logger.warning(f"[ALREADY PASSED] email={email}, test_id={test_id}")
            log_access_async(False, email, test_id, "already_passed", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Test déjà passé"
            }), 403
 
        # =====================
        # GROUP CHECK
        # =====================
        group = TestGroup.objects(test_id=test_id).only("candidate_ids", "formation").first()
        if not group:
            logger.warning(f"[GROUP NOT FOUND] test_id={test_id}")
            log_access_async(False, email, test_id, "group_not_found", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Groupe du test non trouvé"
            }), 404
 
        if str(candidature.id) not in group.candidate_ids or group.formation != test.referentiel:
            logger.warning(f"[NOT IN GROUP] candidate_id={candidature.id}, group={group.id}")
            log_access_async(False, email, test_id, "not_in_group", ip)
            return jsonify({
                "success": False,
                "authorized": False,
                "error": "Vous ne faites pas partie du groupe autorisé pour ce test"
            }), 403
        logger.debug(f"[GROUP OK] candidate_id={candidature.id} appartient au groupe")
 
        # =====================
        # TIME WINDOW
        # =====================
        if test.scheduledDate and test.scheduledTime and test.duration:
            try:
                start = datetime.strptime(f"{test.scheduledDate} {test.scheduledTime}", "%Y-%m-%d %H:%M")
                end = start + timedelta(minutes=int(test.duration))
                now = datetime.now()
                if now < start or now > end:
                    logger.warning(f"[OUTSIDE TIME WINDOW] now={now}, start={start}, end={end}")
                    log_access_async(False, email, test_id, "outside_time_window", ip)
                    return jsonify({
                        "success": False,
                        "authorized": False,
                        "error": "Test non accessible"
                    }), 403
            except Exception as e:
                logger.error(f"[TIME WINDOW ERROR] {e}")
 
        # =====================
        # SUCCESS
        # =====================
        log_access_async(True, email, test_id, None, ip)
        logger.info(f"[ACCESS GRANTED] email={email}, test_id={test_id}, IP={ip}")
 
        return jsonify({
            "success": True,
            "authorized": True,
            "candidate": {
                "id": str(candidature.id),
                "firstName": candidature.first_name,
                "lastName": candidature.last_name,
                "email": candidature.email
            },
            "test": {
                "id": str(test.id),
                "title": test.title,
                "referentiel": test.referentiel
            }
        }), 200
 
       
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"DEBUG: [INTERNAL ERROR] {str(e)}")
        # Logger l'erreur interne avec email si disponible
        logger.error(f"[INTERNAL ERROR] email={email}, test_id={test_id}, IP={ip}, error={e}")
        return jsonify({
            "success": False,
            "error": "Erreur interne"
        }), 500
 
def is_rate_limited(ip):
    now = time.time()
    attempts = rate_limit_store[ip]
 
    # garder seulement les tentatives dans la fenêtre
    rate_limit_store[ip] = [t for t in attempts if now - t < RATE_WINDOW]
 
    if len(rate_limit_store[ip]) >= RATE_LIMIT:
        return True
 
    rate_limit_store[ip].append(now)
    return False
 
def get_test_cached(test_id):
    now = time.time()
    cached = test_cache.get(test_id)
 
    if cached and now - cached["ts"] < TEST_CACHE_TTL:
        return cached["data"]
 
    test = Test.objects(id=test_id).only(
        "id", "title", "referentiel",
        "scheduledDate", "scheduledTime", "duration"
    ).first()
 
    if test:
        test_cache[test_id] = {
            "data": test,
            "ts": now
        }
 
    return test
import threading
 
def log_access_async(success, email, test_id, reason=None, ip=None):
    def _log():
        try:
            # ConnectionLog est un EmbeddedDocument dans test.py, on ne peut pas le sauver seul
            # Pour l'instant on se contente d'un log standard
            status = "success" if success else "failed"
            logger.info(f"CONNEXION TEST: {email} | Test: {test_id} | Status: {status} | Reason: {reason} | IP: {ip}")
        except Exception:
            pass  # ne jamais casser l'app
 
    threading.Thread(target=_log, daemon=True).start()
  
 
@test_bp.route('/tests/<test_id>/update-status', methods=['POST'])
def update_test_status_auto(test_id):
    """Mettre à jour automatiquement le statut du test si la durée est dépassée"""
    try:
        test = Test.objects(id=test_id).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test non trouvé'
            }), 404
       
        # Vérifier si la durée du test est dépassée
        try:
            test_datetime = datetime.strptime(f"{test.scheduledDate} {test.scheduledTime}", "%Y-%m-%d %H:%M")
            test_end_datetime = test_datetime + timedelta(minutes=test.duration)
            now = datetime.now()
           
            if now > test_end_datetime and test.status != 'completed':
                test.status = 'completed'
                test.updatedAt = datetime.utcnow()
                test.save()
               
                return jsonify({
                    'success': True,
                    'message': 'Statut du test mis à jour à "terminé"',
                    'status': 'completed'
                }), 200
            else:
                return jsonify({
                    'success': True,
                    'message': 'Le test est toujours en cours',
                    'status': test.status
                }), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f"Erreur lors du parsing de la date : {str(e)}"
            }), 500
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la mise à jour : {str(e)}"
        }), 500
 
# ==================== LOGS DE VIOLATIONS ANTI-TRICHE ====================
 
@test_bp.route('/tests/<test_id>/log-violation', methods=['POST'])
def log_violation(test_id):
    """Enregistrer une violation anti-triche"""
    try:
        if not MODELS_AVAILABLE or not TestViolation:
            return jsonify({
                'success': False,
                'error': 'Service non disponible'
            }), 503
       
        data = request.get_json()
       
        violation = TestViolation(
            testId=str(test_id),
            testResultId=data.get('testResultId'),
            candidateEmail=data.get('candidateEmail', ''),
            violationType=data.get('type', 'unknown'),
            message=data.get('message', ''),
            elapsedTime=data.get('elapsedTime'),
            metadata={
                'userAgent': request.headers.get('User-Agent'),
                'ip': request.remote_addr,
                **data.get('metadata', {})
            }
        )
       
        violation.save()
       
        return jsonify({
            'success': True,
            'message': 'Violation enregistrée'
        }), 200
       
    except Exception as e:
        print(f"Erreur lors de l'enregistrement de la violation: {str(e)}")
        return jsonify({
            'success': False,
            'error': f"Erreur lors de l'enregistrement : {str(e)}"
        }), 500
 
@test_bp.route('/tests/<test_id>/violations', methods=['GET'])
def get_violations(test_id):
    """Récupérer les violations pour un test"""
    try:
        if not MODELS_AVAILABLE or not TestViolation:
            return jsonify({
                'success': False,
                'error': 'Service non disponible'
            }), 503
       
        candidate_email = request.args.get('candidateEmail')
       
        query = {'testId': str(test_id)}
        if candidate_email:
            query['candidateEmail'] = candidate_email
       
        violations = TestViolation.objects(**query).order_by('-timestamp')
       
        return jsonify({
            'success': True,
            'data': [v.to_dict() for v in violations]
        }), 200
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors de la récupération : {str(e)}"
        }), 500