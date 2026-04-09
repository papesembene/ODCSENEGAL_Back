from flask import Blueprint, jsonify, request
from app.models.competence import Competence  # Votre modèle pour les compétences
from app.models.startup import Startup
from app.models.candidature import Candidature
from app.models.event import Event
#from app.models.test import Test
#from app.models.test_group import TestGroup
#from app.models.test_result import TestResult
from app.services.auth_service import AuthService
from werkzeug.exceptions import Unauthorized, BadRequest
from datetime import datetime, timedelta


admin_bp = Blueprint('admin_bp', __name__)

# Route pour la connexion admin
@admin_bp.route('/login', methods=['POST', 'OPTIONS'])
def admin_login():
    """Authentification des administrateurs"""
    if request.method == 'OPTIONS':
        return '', 200  # Réponse vide = préflight validé
    try:
        data = request.get_json()
        
        if not data:
            raise BadRequest("Données manquantes")
        
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            raise BadRequest("Email et mot de passe requis")
        
        # Utiliser le service d'authentification admin
        result = AuthService.login_admin(email, password)
        
        return jsonify({
            'success': True,
            'message': 'Connexion réussie',
            'token': result['token'],
            'user': result['user']
        }), 200
        
    except Unauthorized as e:
        # Nettoyer le message d'erreur (retirer les préfixes HTTP comme "401 Unauthorized: ")
        error_message = str(e)
        # Retirer les préfixes HTTP si présents
        if error_message.startswith('401') or error_message.startswith('Unauthorized'):
            # Extraire juste le message après le préfixe
            parts = error_message.split(':', 1)
            error_message = parts[-1].strip() if len(parts) > 1 else error_message
            # Si le message contient toujours un code HTTP, utiliser un message par défaut
            if error_message.startswith('401') or error_message.startswith('Unauthorized'):
                error_message = "Email ou mot de passe incorrect"
        
        return jsonify({
            'success': False,
            'error': error_message
        }), 401
    except BadRequest as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors de la connexion: {str(e)}'
        }), 500

# Route pour récupérer les candidatures de compétences
@admin_bp.route('/competences/candidatures', methods=['GET'])
def get_competences_candidatures():
    try:
        candidatures = Competence.objects()  # Récupérer toutes les candidatures
        data = []
        
        for candidature in candidatures:
            data.append({
                'id': str(candidature.id),
                'firstName': candidature.first_name,
                'lastName': candidature.last_name,
                'email': candidature.email,
                'phone': candidature.phone,
                'gender': candidature.gender,
                'age': candidature.age,
                'education': candidature.education,
                'address': candidature.address,
                'formation': candidature.formation,
                'status': candidature.status or 'En attente',
                'applicationDate': candidature.application_date.isoformat() if candidature.application_date else None,
                'cv': candidature.cv_filename
            })
        
        return jsonify({
            'success': True,
            'candidatures': data,
            'total': len(data)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'candidatures': [],
            'total': 0
        }), 500

# Route pour récupérer les candidatures de startups
@admin_bp.route('/startup/candidatures', methods=['GET'])
def get_startup_candidatures():
    try:
        candidatures = Startup.objects()  # Récupérer toutes les candidatures
        data = []
        
        for candidature in candidatures:
            data.append({
                'id': str(candidature.id),
                'startup_name': candidature.startup_name,
                'website': candidature.website,
                'founding_date': candidature.founding_date,
                'sector': candidature.sector,
                'stage': candidature.stage,
                'team_size': candidature.team_size,
                'program': candidature.program,
                'founder_first_name': candidature.founder_first_name,
                'founder_last_name': candidature.founder_last_name,
                'founder_email': candidature.founder_email,
                'founder_phone': candidature.founder_phone,
                'founder_role': candidature.founder_role,
                'description': candidature.description,
                #'status': candidature.status or 'active',  # Statut par défaut
                'applicationDate': candidature.createdAt.isoformat() if candidature.createdAt else None,
                'cv_filename': candidature.cv_filename,
                'pitchdeck_filename': candidature.pitchdeck_filename
            })
        
        return jsonify({
            'success': True,
            'data': data,
            'total': len(data)
        }), 200

        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'data': [],
            'total': 0
        }), 500

# Route pour récupérer toutes les statistiques du dashboard
@admin_bp.route('/dashboard/statistics', methods=['GET'])
def get_dashboard_statistics():
    """Récupérer toutes les statistiques pour le dashboard administrateur"""
    try:
        # Définir la date actuelle dès le début
        now = datetime.utcnow()
        # Période configurable pour les tendances (par défaut 7 jours, bornée 1..90)
        try:
            days_param = int(request.args.get('days', 7))
        except Exception:
            days_param = 7
        days_window = max(1, min(days_param, 90))
        
        # ==================== STATISTIQUES GLOBALES ====================
        
        # Total candidatures (Candidature model pour compétences)
        # Utiliser count() directement pour éviter de charger toutes les données en mémoire
        total_competences = Candidature.objects().count()
        
        # Total startups (filtrer ceux sans startup_name pour éviter les erreurs d'index)
        candidatures_startups = Startup.objects(startup_name__ne=None)
        total_startups = candidatures_startups.count()
        
        # Total général
        total_candidatures = total_competences + total_startups
        
        # Calculer la croissance par rapport au mois dernier
        first_day_this_month = datetime(now.year, now.month, 1)
        if now.month == 1:
            first_day_last_month = datetime(now.year - 1, 12, 1)
            first_day_this_month_prev = datetime(now.year, 1, 1)
        else:
            first_day_last_month = datetime(now.year, now.month - 1, 1)
            first_day_this_month_prev = datetime(now.year, now.month, 1)
        
        # Candidatures ce mois
        candidatures_ce_mois = Candidature.objects(created_at__gte=first_day_this_month).count()
        candidatures_ce_mois += Startup.objects(startup_name__ne=None, createdAt__gte=first_day_this_month).count()
        
        # Candidatures mois dernier
        candidatures_mois_dernier = Candidature.objects(
            created_at__gte=first_day_last_month,
            created_at__lt=first_day_this_month
        ).count()
        candidatures_mois_dernier += Startup.objects(
            startup_name__ne=None,
            createdAt__gte=first_day_last_month,
            createdAt__lt=first_day_this_month
        ).count()
        
        # Calcul du pourcentage de croissance
        if candidatures_mois_dernier > 0:
            croissance = round(((candidatures_ce_mois - candidatures_mois_dernier) / candidatures_mois_dernier * 100), 0)
        else:
            croissance = 100 if candidatures_ce_mois > 0 else 0
        
        # Tests programmés (scheduled ou active)
        try:
            from app.models.test import Test
            from app.models.test_group import TestGroup
            try:
                tests = Test.objects(status__in=['scheduled', 'active'])
                tests_programmes = tests.count()
                tests_actifs = Test.objects(status='active').count()
            except Exception as e:
                print(f"Erreur lors de la récupération des tests: {str(e)}")
                tests_programmes = 0
                tests_actifs = 0
            
            # Groupes de tests
            try:
                test_groups = TestGroup.objects()
                total_test_groups = test_groups.count()
            except Exception as e:
                print(f"Erreur lors de la récupération des groupes de tests: {str(e)}")
                total_test_groups = 0
        except ImportError:
            # Les modèles Test ne sont pas disponibles
            tests_programmes = 0
            tests_actifs = 0
            total_test_groups = 0
        except Exception as e:
            # Gérer toute autre erreur
            print(f"Erreur lors de l'import des modèles de tests: {str(e)}")
            tests_programmes = 0
            tests_actifs = 0
            total_test_groups = 0
        
        # Événements à venir
        evenements_a_venir = Event.objects(date__gte=now).count()
        
        # Taux d'acceptation (basé sur les candidatures compétences)
        # Vérifier si le champ status existe dans le modèle
        try:
            # Essayer de filtrer par status si le champ existe
            accepted = Candidature.objects(status='accepted').count()
            taux_acceptation = round((accepted / total_competences * 100) if total_competences > 0 else 0, 0)
        except Exception as e:
            # Si le champ status n'existe pas encore dans certaines données, utiliser 0
            print(f"Note: Le champ status n'est pas encore disponible pour toutes les candidatures: {str(e)}")
            accepted = 0
            taux_acceptation = 0
        
        # ==================== TENDANCES DES CANDIDATURES (7 derniers jours) ====================
        
        applications_trend = []
        days_fr = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam']
        
        for i in range(days_window - 1, -1, -1):
            date = now - timedelta(days=i)
            start_of_day = datetime(date.year, date.month, date.day, 0, 0, 0)
            end_of_day = datetime(date.year, date.month, date.day, 23, 59, 59)
            
            # Compter les candidatures avec created_at dans la plage
            try:
                competences_count = Candidature.objects(
                    created_at__gte=start_of_day,
                    created_at__lte=end_of_day
                ).count()
            except Exception as e:
                # Si erreur avec created_at, compter toutes les candidatures
                print(f"Erreur lors du comptage des candidatures par date: {str(e)}")
                competences_count = 0
            
            # Pour les startups
            try:
                startups_count = Startup.objects(
                    startup_name__ne=None,
                    createdAt__gte=start_of_day,
                    createdAt__lte=end_of_day
                ).count()
            except Exception as e:
                print(f"Erreur lors du comptage des startups par date: {str(e)}")
                startups_count = 0
            
            day_name = days_fr[date.weekday()]
            date_label = date.strftime('%d/%m')
            applications_trend.append({
                'date': date_label,
                'day': day_name,
                'competences': competences_count,
                'startups': startups_count
            })
        
        # ==================== RÉPARTITION PAR GENRE ====================
        
        # Optimisation: Utiliser une agrégation MongoDB native pour calculer les genres en une seule requête
        try:
            from mongoengine import Q
            from mongoengine.connection import get_db
            
            # Utiliser count() avec des filtres Q (déjà optimisé par MongoEngine)
            # Cette méthode est plus simple et efficace que d'itérer
            femmes = Candidature.objects(
                Q(gender__iexact='femme') |
                Q(gender__iexact='f') |
                Q(gender__iexact='female') |
                Q(gender__iexact='féminin') |
                Q(gender__iexact='féminine')
            ).count()
            
            hommes = Candidature.objects(
                Q(gender__iexact='homme') |
                Q(gender__iexact='h') |
                Q(gender__iexact='male') |
                Q(gender__iexact='m') |
                Q(gender__iexact='masculin') |
                Q(gender__iexact='masculine')
            ).count()
            
            total_genre = total_competences
            non_specifie = total_genre - femmes - hommes
        except Exception as e:
            # Fallback: utiliser count() avec des filtres Q (plus rapide que d'itérer)
            print(f"Erreur lors de l'agrégation MongoDB pour les genres: {str(e)}, utilisation de count() avec filtres")
            try:
                femmes = Candidature.objects(
                    Q(gender__iexact='femme') |
                    Q(gender__iexact='f') |
                    Q(gender__iexact='female') |
                    Q(gender__iexact='féminin') |
                    Q(gender__iexact='féminine')
                ).count()
                
                hommes = Candidature.objects(
                    Q(gender__iexact='homme') |
                    Q(gender__iexact='h') |
                    Q(gender__iexact='male') |
                    Q(gender__iexact='m') |
                    Q(gender__iexact='masculin') |
                    Q(gender__iexact='masculine')
                ).count()
                
                total_genre = total_competences
                non_specifie = total_genre - femmes - hommes
            except Exception as e2:
                # Dernier recours: utiliser seulement un échantillon pour estimer (beaucoup plus rapide)
                print(f"Erreur lors du comptage par genre avec filtres: {str(e2)}, utilisation d'un échantillon")
                # Utiliser un échantillon de 1000 candidatures maximum pour estimer
                sample_size = min(1000, total_competences)
                femmes = 0
                hommes = 0
                non_specifie = 0
                
                for candidature in Candidature.objects().only('gender').limit(sample_size):
                    try:
                        gender_value = (candidature.gender or '').lower().strip() if hasattr(candidature, 'gender') else ''
                        if gender_value in ['femme', 'f', 'female', 'féminin', 'féminine']:
                            femmes += 1
                        elif gender_value in ['homme', 'h', 'male', 'm', 'masculin', 'masculine']:
                            hommes += 1
                        else:
                            non_specifie += 1
                    except Exception:
                        non_specifie += 1
                
                # Estimer les totaux en fonction de l'échantillon
                if sample_size > 0:
                    ratio = total_competences / sample_size
                    femmes = int(femmes * ratio)
                    hommes = int(hommes * ratio)
                    non_specifie = total_competences - femmes - hommes
                else:
                    non_specifie = total_competences
                
                total_genre = total_competences
        
        gender_distribution = []
        
        if femmes > 0:
            gender_distribution.append({
                'name': 'Femmes',
                'value': round((femmes / total_genre * 100), 0) if total_genre > 0 else 0,
                'count': femmes,
                'color': '#FF6384'
            })
        
        if hommes > 0:
            gender_distribution.append({
                'name': 'Hommes',
                'value': round((hommes / total_genre * 100), 0) if total_genre > 0 else 0,
                'count': hommes,
                'color': '#36A2EB'
            })
        
        if non_specifie > 0 and total_genre > 0:
            gender_distribution.append({
                'name': 'Non spécifié',
                'value': round((non_specifie / total_genre * 100), 0) if total_genre > 0 else 0,
                'count': non_specifie,
                'color': '#CCCCCC'
            })
        
        # Si aucune donnée de genre (total_genre == 0), retourner un tableau vide
        # Le frontend affichera le message approprié
        if total_genre == 0:
            gender_distribution = []
        
        # ==================== RÉPARTITION PAR STATUT ====================
        
        # Optimisation: Utiliser count() directement au lieu d'itérer
        try:
            acceptes = Candidature.objects(status='accepted').count()
            refuses = Candidature.objects(status='rejected').count()
            # Total en attente = total - acceptés - refusés (plus efficace)
            en_attente = total_competences - acceptes - refuses
        except Exception as e:
            # Fallback: méthode simple si le count échoue
            print(f"Erreur lors du comptage par statut: {str(e)}, utilisation de la méthode simple")
            acceptes = 0
            en_attente = 0
            refuses = 0
            # Utiliser seulement() pour ne charger que le champ status (optimisation mémoire)
            # Créer un nouveau queryset pour optimiser la mémoire
            for candidature in Candidature.objects().only('status'):
                try:
                    status_value = getattr(candidature, 'status', 'pending') or 'pending'
                    if status_value == 'accepted':
                        acceptes += 1
                    elif status_value == 'rejected':
                        refuses += 1
                    else:
                        en_attente += 1
                except Exception as e2:
                    print(f"Erreur lors de la lecture du statut: {str(e2)}")
                    en_attente += 1
        
        status_distribution = [
            {
                'name': 'Acceptés',
                'value': round((acceptes / total_competences * 100) if total_competences > 0 else 0, 0),
                'count': acceptes
            },
            {
                'name': 'En attente',
                'value': round((en_attente / total_competences * 100) if total_competences > 0 else 0, 0),
                'count': en_attente
            },
            {
                'name': 'Refusés',
                'value': round((refuses / total_competences * 100) if total_competences > 0 else 0, 0),
                'count': refuses
            }
        ]
        
        # ==================== ACTIVITÉS RÉCENTES ====================
        
        recent_activities = []
        
        # Récupérer les dernières candidatures compétences
        # Essayer d'abord avec tri par created_at, sinon récupérer les dernières par ID
        try:
            # Essayer avec tri par created_at
            recent_candidatures = Candidature.objects(created_at__ne=None).order_by('-created_at').limit(5)
        except Exception:
            try:
                # Si le tri échoue, essayer de récupérer les dernières par ID (les plus récentes)
                recent_candidatures = Candidature.objects().order_by('-id').limit(5)
            except Exception:
                # Si tout échoue, récupérer simplement les 5 dernières
                recent_candidatures = list(Candidature.objects().limit(5))
        
        for cand in recent_candidatures:
            try:
                # Utiliser created_at si disponible, sinon utiliser une date par défaut
                cand_date = None
                if hasattr(cand, 'created_at') and cand.created_at:
                    cand_date = cand.created_at
                elif hasattr(cand, 'id'):
                    # Utiliser l'ObjectId pour estimer une date (les ObjectId contiennent un timestamp)
                    try:
                        object_id_time = cand.id.generation_time
                        cand_date = object_id_time
                    except Exception:
                        cand_date = now
                else:
                    cand_date = now
                
                if cand_date:
                    time_diff = now - cand_date
                    if time_diff.days > 0:
                        time_str = f"Il y a {time_diff.days} jour(s)"
                    elif time_diff.seconds // 3600 > 0:
                        time_str = f"Il y a {time_diff.seconds // 3600}h"
                    else:
                        time_str = f"Il y a {time_diff.seconds // 60} min"
                    
                    first_name = getattr(cand, 'first_name', 'Inconnu')
                    last_name = getattr(cand, 'last_name', '')
                    
                    recent_activities.append({
                        'type': 'candidature',
                        'module': 'Compétences',
                        'action': f"Nouvelle candidature - {first_name} {last_name}",
                        'time': time_str
                    })
            except Exception as e:
                print(f"Erreur lors du traitement d'une candidature pour l'activité récente: {str(e)}")
                continue
        
        # Récupérer les derniers groupes de tests créés
        try:
            from app.models.test_group import TestGroup
            # Essayer de récupérer avec tri par created_at, sinon sans tri
            try:
                # Essayer d'abord avec un tri simple
                recent_groups = TestGroup.objects(created_at__ne=None).only('name', 'candidate_ids', 'created_at').order_by('-created_at').limit(2)
            except Exception as e1:
                # Si le tri échoue, essayer sans tri
                try:
                    recent_groups = TestGroup.objects().only('name', 'candidate_ids', 'created_at').limit(2)
                except Exception as e2:
                    # Si même ça échoue, récupérer sans spécifier les champs
                    print(f"Erreur lors de la récupération des groupes de tests (sans only): {str(e2)}")
                    recent_groups = []
            
            for group in recent_groups:
                try:
                    if not hasattr(group, 'created_at') or not group.created_at:
                        continue
                    time_diff = now - group.created_at
                    if time_diff.days > 0:
                        time_str = f"Il y a {time_diff.days} jour(s)"
                    elif time_diff.seconds // 3600 > 0:
                        time_str = f"Il y a {time_diff.seconds // 3600}h"
                    else:
                        time_str = f"Il y a {time_diff.seconds // 60} min"
                    
                    candidate_count = len(group.candidate_ids) if hasattr(group, 'candidate_ids') and group.candidate_ids else 0
                    group_name = group.name if hasattr(group, 'name') else 'Groupe de test'
                    recent_activities.append({
                        'type': 'test',
                        'module': 'Tests',
                        'action': f"{group_name} - {candidate_count} candidats",
                        'time': time_str
                    })
                except Exception as e:
                    print(f"Erreur lors du traitement d'un groupe de test: {str(e)}")
                    continue
        except ImportError:
            # Les modèles Test ne sont pas disponibles, ignorer
            pass
        except Exception as e:
            # Gérer toute autre erreur (comme Cannot resolve field)
            print(f"Erreur lors de la récupération des groupes de tests: {str(e)}")
            pass
        
        # Récupérer les dernières startups
        recent_startups = Startup.objects(startup_name__ne=None).order_by('-createdAt').limit(2)
        for startup in recent_startups:
            if startup.createdAt:
                time_diff = now - startup.createdAt
                if time_diff.days > 0:
                    time_str = f"Il y a {time_diff.days} jour(s)"
                elif time_diff.seconds // 3600 > 0:
                    time_str = f"Il y a {time_diff.seconds // 3600}h"
                else:
                    time_str = f"Il y a {time_diff.seconds // 60} min"
                
                recent_activities.append({
                    'type': 'startup',
                    'module': 'Startups',
                    'action': f"{startup.program or 'Programme'} - {startup.startup_name}",
                    'time': time_str
                })
        
        # Récupérer les derniers événements
        try:
            recent_events = Event.objects(created_at__ne=None).order_by('-created_at').limit(2)
        except Exception:
            # Si le tri échoue, récupérer sans tri
            recent_events = Event.objects(created_at__ne=None).limit(2)
        
        for event in recent_events:
            if not hasattr(event, 'created_at') or not event.created_at:
                continue
            time_diff = now - event.created_at
            if time_diff.days > 0:
                time_str = f"Il y a {time_diff.days} jour(s)"
            elif time_diff.seconds // 3600 > 0:
                time_str = f"Il y a {time_diff.seconds // 3600}h"
            else:
                time_str = f"Il y a {time_diff.seconds // 60} min"
            
            # Compter les inscriptions
            from app.models.event import Registration
            registrations_count = Registration.objects(event_id=event.id).count()
            
            recent_activities.append({
                'type': 'event',
                'module': 'Événements',
                'action': f"{event.title} - {registrations_count} inscriptions",
                'time': time_str
            })
        
        # Trier par le plus récent
        recent_activities = sorted(recent_activities, key=lambda x: x['time'])[:5]
        
        # ==================== STATISTIQUES DES MODULES ====================
        
        # Compétences - compter par formation (optimisé avec une seule requête d'agrégation)
        formations_list = ['Dev Web', 'Data', 'Hackeuse', 'AWS', 'Design UX/UI', 'Cyber security', 'Intelligence Artificielle']
        formations_count = {}
        # Utiliser une seule requête avec $in au lieu de plusieurs requêtes séparées
        try:
            from mongoengine.connection import get_db
            db = get_db()
            pipeline = [
                {
                    '$match': {
                        'desired_training': {'$in': formations_list}
                    }
                },
                {
                    '$group': {
                        '_id': '$desired_training',
                        'count': {'$sum': 1}
                    }
                }
            ]
            results = list(db.candidature.aggregate(pipeline))
            # Initialiser toutes les formations à 0
            for formation in formations_list:
                formations_count[formation] = 0
            # Remplir avec les résultats
            for result in results:
                formation_name = result['_id']
                if formation_name in formations_list:
                    formations_count[formation_name] = result['count']
        except Exception as e:
            # Fallback: utiliser count() pour chaque formation (plus lent mais fonctionne)
            print(f"Erreur lors de l'agrégation pour les formations: {str(e)}, utilisation de count()")
            for formation in formations_list:
                formations_count[formation] = Candidature.objects(desired_training=formation).count()
        
        # Startups - compter par programme
        orange_fab_count = Startup.objects(startup_name__ne=None, program='Orange Fab').count()
        startup_lab_count = Startup.objects(startup_name__ne=None, program='Startup Lab').count()
        
        # Événements - participants totaux
        from app.models.event import Registration
        total_participants = Registration.objects().count()
        events_ce_mois = Event.objects(
            date__gte=datetime(now.year, now.month, 1)
        ).count()
        
        # Tests - taux de réussite
        try:
            from app.models.test_result import TestResult
            # Utiliser la collection MongoDB directement pour éviter les problèmes d'index MongoEngine
            try:
                # Utiliser _get_collection() pour obtenir la collection brute de MongoEngine
                collection = TestResult._get_collection()
                total_count = collection.count_documents({})
                admis_count = collection.count_documents({'status': 'admis'})
                
                if total_count > 0:
                    taux_reussite = round((admis_count / total_count * 100), 0)
                    candidats_testes = total_count
                else:
                    taux_reussite = 0
                    candidats_testes = 0
            except Exception as e:
                print(f"Erreur lors du comptage avec _get_collection: {str(e)}")
                # Fallback: valeurs par défaut si l'accès à la collection échoue
                taux_reussite = 0
                candidats_testes = 0
        except ImportError:
            # Les modèles Test ne sont pas disponibles
            taux_reussite = 0
            candidats_testes = 0
        except Exception as e:
            # Gérer les erreurs de résolution de champ (comme submitted_at)
            print(f"Erreur lors de la récupération des résultats de tests: {str(e)}")
            taux_reussite = 0
            candidats_testes = 0
        
        # ==================== RÉPARTITION PAR NATIONALITÉ ====================
        
        nationality_distribution = []
        nationality_counts = {}
        
        try:
            # Compter d'abord le total pour vérifier qu'il y a des candidatures
            total_candidatures_with_nationality = Candidature.objects().count()
            print(f"DEBUG: Total candidatures dans la base: {total_candidatures_with_nationality}")
            
            # Charger uniquement le champ nationality (optimisation mémoire)
            candidatures_with_nationality = Candidature.objects.only('nationality')
            count_with_nationality = candidatures_with_nationality.count()
            print(f"DEBUG: Candidatures chargées pour la nationalité: {count_with_nationality}")
            
            for candidature in candidatures_with_nationality:
                try:
                    nationality_value = getattr(candidature, 'nationality', None)
                    if not nationality_value:
                        continue
                    nationality_value = str(nationality_value).strip()
                    if not nationality_value:
                        continue

                    if nationality_value not in nationality_counts:
                        nationality_counts[nationality_value] = 0
                    nationality_counts[nationality_value] += 1
                except Exception as e2:
                    print(f"Erreur lors de la lecture de la nationalité pour une candidature: {str(e2)}")
                    continue
            
            print(f"DEBUG: Nombre de nationalités différentes trouvées: {len(nationality_counts)}")
            print(f"DEBUG: Nationalités: {nationality_counts}")
            
            # Calculer le total pour les pourcentages
            total_nationalities = sum(nationality_counts.values())
            
            if total_nationalities > 0:
                # Trier par nombre de candidatures (décroissant) et prendre les 20 premières
                sorted_nationalities = sorted(nationality_counts.items(), key=lambda x: x[1], reverse=True)[:20]
                
                # Générer les couleurs pour le graphique
                colors_list = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384',
                              '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384', '#36A2EB']
                
                for index, (nationality, count) in enumerate(sorted_nationalities):
                    percentage = round((count / total_nationalities * 100), 1) if total_nationalities > 0 else 0
                    nationality_distribution.append({
                        'name': nationality,
                        'value': percentage,
                        'count': count,
                        'color': colors_list[index % len(colors_list)]
                    })
                
                print(f"DEBUG: Répartition par nationalité créée avec {len(nationality_distribution)} entrées")
            else:
                print("DEBUG: Aucune nationalité trouvée dans les candidatures")
                nationality_distribution = []
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Erreur lors du calcul de la répartition par nationalité: {str(e)}")
            print(f"Traceback: {error_trace}")
            nationality_distribution = []
        
        # ==================== RETOURNER TOUTES LES DONNÉES ====================
        
        return jsonify({
            'success': True,
            'data': {
                'globalStats': {
                    'totalCandidatures': total_candidatures,
                    'candidaturesCompetences': total_competences,
                    'candidaturesStartups': total_startups,
                    'testsProgrammes': tests_programmes,
                    'evenementsAVenir': evenements_a_venir,
                    'tauxAcceptation': int(taux_acceptation),
                    'croissance': int(croissance)
                },
                'applicationsTrend': applications_trend,
                'genderDistribution': gender_distribution,
                'statusDistribution': status_distribution,
                'nationalityDistribution': nationality_distribution,
                'recentActivities': recent_activities,
                'moduleStats': {
                    'competences': {
                        'total': total_competences,
                        'formations': formations_count,
                        'testsActifs': tests_actifs
                    },
                    'startups': {
                        'total': total_startups,
                        'orangeFab': orange_fab_count,
                        'startupLab': startup_lab_count
                    },
                    'events': {
                        'aVenir': evenements_a_venir,
                        'participants': total_participants,
                        'ceMois': events_ce_mois
                    },
                    'tests': {
                        'actifs': tests_actifs,
                        'candidatsTestes': candidats_testes,
                        'tauxReussite': int(taux_reussite)
                    }
                }
            }
        }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Erreur dans get_dashboard_statistics: {str(e)}")
        print(f"Traceback: {error_trace}")
        # Retourner des données partielles si possible
        try:
            # Essayer de retourner au moins les statistiques de base
            total_competences = Candidature.objects().count()
            candidatures_startups = Startup.objects(startup_name__ne=None)
            total_startups = candidatures_startups.count()
            total_candidatures = total_competences + total_startups
            
            return jsonify({
                'success': True,
                'data': {
                    'globalStats': {
                        'totalCandidatures': total_candidatures,
                        'candidaturesCompetences': total_competences,
                        'candidaturesStartups': total_startups,
                        'testsProgrammes': 0,
                        'evenementsAVenir': 0,
                        'tauxAcceptation': 0,
                        'croissance': 0
                    },
                    'applicationsTrend': [],
                    'genderDistribution': [],
                    'statusDistribution': [],
                    'nationalityDistribution': [],
                    'recentActivities': [],
                    'moduleStats': {
                        'competences': {'total': total_competences, 'formations': {}, 'testsActifs': 0},
                        'startups': {'total': total_startups, 'orangeFab': 0, 'startupLab': 0},
                        'events': {'aVenir': 0, 'participants': 0, 'ceMois': 0},
                        'tests': {'actifs': 0, 'candidatsTestes': 0, 'tauxReussite': 0}
                    }
                },
                'warning': f"Certaines statistiques n'ont pas pu être récupérées: {str(e)}"
            }), 200
        except Exception as e2:
            return jsonify({
                'success': False,
                'error': f"Erreur lors de la récupération des statistiques : {str(e)}"
            }), 500
