#!/usr/bin/env python
"""
Script pour analyser pourquoi certains candidats n'ont pas pu se connecter
"""

from app import create_app
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.candidature import Candidature
from app.models.test_result import TestResult
from bson import ObjectId
import re

app = create_app()
with app.app_context():
    # Demander l'ID du test
    test_id = input("Entrez l'ID du test: ").strip()
    
    test = Test.objects(id=test_id).first()
    if not test:
        print(f"❌ Test {test_id} non trouvé")
        exit()
    
    print(f"\n{'='*70}")
    print(f"ANALYSE DES ÉCHECS DE CONNEXION")
    print(f"Test: {test.title}")
    print(f"{'='*70}\n")
    
    # Récupérer le groupe assigné
    if not test.candidatesGroup:
        print("❌ Ce test n'a pas de groupe assigné")
        exit()
    
    group = TestGroup.objects(id=test.candidatesGroup).first()
    if not group:
        print(f"❌ Groupe {test.candidatesGroup} non trouvé")
        exit()
    
    print(f"Groupe: {group.name}")
    print(f"Formation du groupe: {group.formation}")
    print(f"Candidats dans le groupe: {len(group.candidate_ids) if group.candidate_ids else 0}\n")
    
    # Convertir les IDs en ObjectId
    group_candidate_ids = [ObjectId(str(cid).strip()) for cid in (group.candidate_ids or [])]
    
    # Récupérer tous les candidats du groupe
    candidates = Candidature.objects(id__in=group_candidate_ids)
    existing_count = candidates.count()
    
    print(f"📊 STATISTIQUES:")
    print(f"   - Candidats dans le groupe: {len(group_candidate_ids)}")
    print(f"   - Candidats trouvés dans la base: {existing_count}\n")
    
    # Candidats qui ont réussi à se connecter
    connected_emails = set()
    if test.connectionLogs:
        for log in test.connectionLogs:
            if log.email:
                connected_emails.add(log.email.lower().strip())
    
    print(f"✅ CONNEXIONS RÉUSSIES: {len(connected_emails)}\n")
    
    # Candidats qui ont soumis (utiliser MongoDB directement pour éviter les problèmes d'index)
    from app import db
    from app.config import Config
    submitted_emails = set()
    try:
        # Utiliser la connexion MongoDB directement
        db_name = Config.MONGODB_SETTINGS.get('db', 'odcdb')
        database = db.connection[db_name]
        test_results_collection = database['test_results']
        results = test_results_collection.find({'testId': str(test.id)})
        for result in results:
            if result.get('candidate') and result['candidate'].get('email'):
                submitted_emails.add(result['candidate']['email'].lower().strip())
    except Exception as e:
        print(f"⚠️  Impossible de récupérer les résultats soumis: {e}")
        print("   Continuons l'analyse sans cette information...\n")
    
    print(f"📝 SOUMISSIONS: {len(submitted_emails)}\n")
    
    # Analyser les échecs
    print(f"{'='*70}")
    print(f"ANALYSE DES RAISONS D'ÉCHEC")
    print(f"{'='*70}\n")
    
    failed_reasons = {
        'no_phone': [],
        'no_email': [],
        'wrong_phone_format': [],
        'wrong_formation': [],
        'already_passed': [],
        'not_in_group': [],
        'test_not_started': [],
        'test_expired': [],
        'other': []
    }
    
    # Normaliser la formation du groupe
    def normalize_formation(f):
        if not f:
            return ''
        return f.lower().strip().replace(' ', '').replace('-', '').replace('_', '')
    
    group_formation_norm = normalize_formation(group.formation)
    
    # Analyser chaque candidat du groupe
    for candidate in candidates:
        email = (candidate.email or '').lower().strip()
        
        # Si déjà connecté, passer
        if email in connected_emails:
            continue
        
        # Raison 1: Pas de téléphone
        if not candidate.phone or not candidate.phone.strip():
            failed_reasons['no_phone'].append({
                'email': email,
                'id': str(candidate.id),
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 2: Pas d'email
        if not email:
            failed_reasons['no_email'].append({
                'id': str(candidate.id),
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 3: Formation différente
        candidate_formation_norm = normalize_formation(candidate.desired_training)
        if candidate_formation_norm != group_formation_norm:
            failed_reasons['wrong_formation'].append({
                'email': email,
                'candidate_formation': candidate.desired_training,
                'group_formation': group.formation,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 4: Déjà passé le test
        if email in submitted_emails:
            failed_reasons['already_passed'].append({
                'email': email,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 5: Vérifier le format du téléphone (peut causer des problèmes)
        phone_normalized = re.sub(r'\D', '', str(candidate.phone))
        if len(phone_normalized) < 7:
            failed_reasons['wrong_phone_format'].append({
                'email': email,
                'phone': candidate.phone,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Vérifier si l'ID du candidat est bien dans le groupe (normalisé)
        candidate_id_str = str(candidate.id).strip()
        normalized_group_ids = [str(cid).strip() for cid in (group.candidate_ids or [])]
        
        # Vérifier avec différentes variantes de l'ID
        candidate_id_variants = [
            candidate_id_str,
            str(candidate.id),  # Sans strip
            candidate_id_str.lower(),  # En minuscules
            candidate_id_str.upper(),  # En majuscules
        ]
        
        is_in_group = False
        matching_id_in_group = None
        
        for variant in candidate_id_variants:
            if variant in normalized_group_ids:
                is_in_group = True
                matching_id_in_group = variant
                break
        
        if not is_in_group:
            # Vérifier si c'est un problème de format (ObjectId vs string)
            try:
                from bson import ObjectId
                candidate_oid = ObjectId(candidate_id_str)
                # Chercher avec ObjectId converti en string
                if str(candidate_oid) in normalized_group_ids:
                    is_in_group = True
                    matching_id_in_group = str(candidate_oid)
            except:
                pass
            
            if not is_in_group:
                failed_reasons['not_in_group'].append({
                    'email': email,
                    'id': candidate_id_str,
                    'name': f"{candidate.first_name} {candidate.last_name}".strip(),
                    'phone': candidate.phone,
                    'group_ids_sample': normalized_group_ids[:3] if normalized_group_ids else []
                })
                continue
        
        # Vérifier la date/heure du test
        from datetime import datetime
        try:
            test_datetime = datetime.strptime(f"{test.scheduledDate} {test.scheduledTime}", "%Y-%m-%d %H:%M")
            from datetime import timedelta
            test_end_datetime = test_datetime + timedelta(minutes=test.duration)
            now = datetime.now()
            
            if now < test_datetime:
                failed_reasons['test_not_started'].append({
                    'email': email,
                    'name': f"{candidate.first_name} {candidate.last_name}".strip(),
                    'test_start': test_datetime.strftime("%Y-%m-%d %H:%M")
                })
                continue
            
            if now > test_end_datetime:
                failed_reasons['test_expired'].append({
                    'email': email,
                    'name': f"{candidate.first_name} {candidate.last_name}".strip(),
                    'test_end': test_end_datetime.strftime("%Y-%m-%d %H:%M")
                })
                continue
        except Exception as e:
            pass  # Ignorer les erreurs de date
        
        # Autre raison (vérifier manuellement - probablement problème de téléphone qui ne correspond pas exactement)
        failed_reasons['other'].append({
            'email': email,
            'id': candidate_id_str,
            'name': f"{candidate.first_name} {candidate.last_name}".strip(),
            'phone': candidate.phone,
            'phone_normalized': phone_normalized
        })
    
    # Afficher les résultats
    total_failed = sum(len(v) for v in failed_reasons.values())
    
    print(f"📋 RÉPARTITION DES ÉCHECS ({total_failed} candidat(s)):\n")
    
    reason_labels = {
        'no_phone': '❌ Pas de téléphone',
        'no_email': '❌ Pas d\'email',
        'wrong_phone_format': '⚠️ Format de téléphone invalide',
        'wrong_formation': '⚠️ Formation différente du groupe',
        'already_passed': '✅ Déjà passé le test',
        'not_in_group': '❌ ID pas dans le groupe (normalisé)',
        'test_not_started': '⏰ Test pas encore commencé',
        'test_expired': '⏰ Test expiré',
        'other': '❓ Autre raison (probablement téléphone ne correspond pas)'
    }
    
    for reason, candidates_list in failed_reasons.items():
        if candidates_list:
            label = reason_labels.get(reason, reason)
            print(f"   {label}: {len(candidates_list)} candidat(s)")
            
            # Afficher quelques exemples
            if len(candidates_list) <= 5:
                for c in candidates_list:
                    name = c.get('name', 'N/A')
                    email = c.get('email', 'N/A')
                    print(f"      - {name} ({email})")
            else:
                for c in candidates_list[:5]:
                    name = c.get('name', 'N/A')
                    email = c.get('email', 'N/A')
                    print(f"      - {name} ({email})")
                print(f"      ... et {len(candidates_list) - 5} autres")
            
            # Afficher des détails supplémentaires pour certaines raisons
            if reason == 'wrong_formation' and candidates_list:
                print(f"      Détails formation:")
                for c in candidates_list[:3]:
                    print(f"         - {c.get('candidate_formation')} vs {c.get('group_formation')}")
            
            if reason == 'not_in_group' and candidates_list:
                print(f"      Exemples d'IDs non trouvés dans le groupe:")
                for c in candidates_list[:3]:
                    print(f"         - ID candidat: {c.get('id')}")
                    if c.get('group_ids_sample'):
                        print(f"           IDs du groupe (échantillon): {c.get('group_ids_sample')}")
            
            print()
    
    print(f"{'='*70}")
    print(f"RÉSUMÉ:")
    print(f"   Total dans le groupe: {len(group_candidate_ids)}")
    print(f"   Connectés avec succès: {len(connected_emails)}")
    print(f"   Non connectés: {total_failed}")
    print(f"   Taux de connexion: {(len(connected_emails) / existing_count * 100) if existing_count > 0 else 0:.1f}%")
    print(f"{'='*70}\n")
    
    # Suggestions
    if failed_reasons['wrong_formation']:
        print("💡 SUGGESTION: Certains candidats ont une formation différente.")
        print("   Vérifiez si ces candidats devraient être dans ce groupe.\n")
    
    if failed_reasons['no_phone'] or failed_reasons['wrong_phone_format']:
        print("💡 SUGGESTION: Problèmes de téléphone détectés.")
        print("   Les candidats doivent entrer leur téléphone exactement comme dans la base.\n")
    
    if failed_reasons['other']:
        print("💡 SUGGESTION: Pour les 'Autre raison' (probablement téléphone):")
        print("   - Le téléphone saisi par le candidat ne correspond pas exactement à celui en base")
        print("   - Vérifiez les formats: +221 77 123 45 67 vs 221771234567 vs 771234567")
        print("   - Les candidats doivent entrer leur téléphone EXACTEMENT comme dans la base\n")
    
    if failed_reasons['not_in_group']:
        print("💡 PROBLÈME IDENTIFIÉ: Candidats avec ID pas dans le groupe")
        print("   C'est LA RAISON du message 'Accès refusé. Seuls les candidats du groupe peuvent passer ce test'")
        print("   - Ces candidats sont dans la base mais leur ID n'est pas dans group.candidate_ids")
        print("   - Solutions possibles:")
        print("     1. Vérifier si les IDs ont été correctement ajoutés lors de la création du groupe")
        print("     2. Ajouter manuellement les IDs manquants au groupe")
        print("     3. Vérifier s'il y a eu un problème lors de la création du groupe (troncature, erreur)\n")
        
        # Afficher un échantillon pour vérification manuelle
        if len(failed_reasons['not_in_group']) > 0:
            print("   📋 Échantillon pour vérification manuelle (premiers 5):")
            for c in failed_reasons['not_in_group'][:5]:
                print(f"      - {c.get('name')} ({c.get('email')}) - ID: {c.get('id')}")
            print()

