#!/usr/bin/env python
"""
Script pour analyser pourquoi les candidats qui sont dans le groupe mais n'ont pas réussi à se connecter
"""

from app import create_app
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.candidature import Candidature
from app.models.test_result import TestResult
from bson import ObjectId
import re
from datetime import datetime, timedelta

app = create_app()
with app.app_context():
    test_id = input("Entrez l'ID du test: ").strip()
    
    test = Test.objects(id=test_id).first()
    if not test:
        print(f"❌ Test {test_id} non trouvé")
        exit()
    
    if not test.candidatesGroup:
        print("❌ Le test n'a pas de groupe assigné")
        exit()
    
    group = TestGroup.objects(id=test.candidatesGroup).first()
    if not group:
        print(f"❌ Groupe {test.candidatesGroup} non trouvé")
        exit()
    
    print(f"\n{'='*70}")
    print(f"ANALYSE DES AUTRES ÉCHECS (candidats dans le groupe)")
    print(f"{'='*70}\n")
    print(f"Test: {test.title}")
    print(f"Groupe: {group.name}\n")
    
    # Normaliser les IDs du groupe
    normalized_group_ids = [str(cid).strip() for cid in (group.candidate_ids or [])]
    group_candidate_ids = [ObjectId(str(cid).strip()) for cid in (group.candidate_ids or [])]
    
    # Récupérer tous les candidats du groupe
    candidates = Candidature.objects(id__in=group_candidate_ids)
    
    # Candidats qui ont réussi à se connecter
    connected_emails = set()
    if test.connectionLogs:
        for log in test.connectionLogs:
            if log.email:
                connected_emails.add(log.email.lower().strip())
    
    # Candidats qui ont soumis
    submitted_emails = set()
    try:
        from app import db
        from app.config import Config
        db_name = Config.MONGODB_SETTINGS.get('db', 'odcdb')
        database = db.connection[db_name]
        test_results_collection = database['test_results']
        results = test_results_collection.find({'testId': str(test.id)})
        for result in results:
            if result.get('candidate') and result['candidate'].get('email'):
                submitted_emails.add(result['candidate']['email'].lower().strip())
    except Exception as e:
        print(f"⚠️  Impossible de récupérer les résultats: {e}\n")
    
    print(f"📊 STATISTIQUES:")
    print(f"   - Candidats dans le groupe: {len(normalized_group_ids)}")
    print(f"   - Candidats connectés: {len(connected_emails)}")
    print(f"   - Candidats non connectés: {len(normalized_group_ids) - len(connected_emails)}\n")
    
    # Analyser les candidats qui sont dans le groupe mais n'ont pas réussi
    failed_reasons = {
        'no_phone': [],
        'no_email': [],
        'wrong_phone_format': [],
        'wrong_formation': [],
        'already_passed': [],
        'test_not_started': [],
        'test_expired': [],
        'phone_mismatch_likely': [],
        'other': []
    }
    
    def normalize_formation(f):
        if not f:
            return ''
        return f.lower().strip().replace(' ', '').replace('-', '').replace('_', '')
    
    group_formation_norm = normalize_formation(group.formation)
    
    # Vérifier la date/heure du test
    test_accessible = True
    test_started = True
    test_expired = False
    try:
        test_datetime = datetime.strptime(f"{test.scheduledDate} {test.scheduledTime}", "%Y-%m-%d %H:%M")
        test_end_datetime = test_datetime + timedelta(minutes=test.duration)
        now = datetime.now()
        
        if now < test_datetime:
            test_accessible = False
            test_started = False
        elif now > test_end_datetime:
            test_accessible = False
            test_expired = True
    except:
        pass
    
    print(f"{'='*70}")
    print(f"ANALYSE DÉTAILLÉE DES CANDIDATS NON CONNECTÉS")
    print(f"{'='*70}\n")
    
    for candidate in candidates:
        email = (candidate.email or '').lower().strip()
        
        # Si déjà connecté, passer
        if email in connected_emails:
            continue
        
        # Raison 1: Pas de téléphone
        if not candidate.phone or not candidate.phone.strip():
            failed_reasons['no_phone'].append({
                'email': email,
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
        
        # Raison 5: Format de téléphone invalide
        phone_normalized = re.sub(r'\D', '', str(candidate.phone))
        if len(phone_normalized) < 7:
            failed_reasons['wrong_phone_format'].append({
                'email': email,
                'phone': candidate.phone,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 6: Test pas encore commencé
        if not test_started:
            failed_reasons['test_not_started'].append({
                'email': email,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison 7: Test expiré
        if test_expired:
            failed_reasons['test_expired'].append({
                'email': email,
                'name': f"{candidate.first_name} {candidate.last_name}".strip()
            })
            continue
        
        # Raison probable: Téléphone ne correspond pas (le candidat saisit un format différent)
        # C'est la raison la plus probable pour les candidats qui sont dans le groupe
        failed_reasons['phone_mismatch_likely'].append({
            'email': email,
            'phone': candidate.phone,
            'phone_normalized': phone_normalized,
            'name': f"{candidate.first_name} {candidate.last_name}".strip(),
            'id': str(candidate.id)
        })
    
    # Afficher les résultats
    total_failed = sum(len(v) for v in failed_reasons.values())
    
    print(f"📋 RÉPARTITION DES ÉCHECS ({total_failed} candidat(s)):\n")
    
    reason_labels = {
        'no_phone': '❌ Pas de téléphone',
        'no_email': '❌ Pas d\'email',
        'wrong_phone_format': '⚠️ Format de téléphone invalide (< 7 chiffres)',
        'wrong_formation': '⚠️ Formation différente du groupe',
        'already_passed': '✅ Déjà passé le test',
        'test_not_started': '⏰ Test pas encore commencé',
        'test_expired': '⏰ Test expiré',
        'phone_mismatch_likely': '📱 Téléphone ne correspond probablement pas (format saisi différent)',
        'other': '❓ Autre raison'
    }
    
    for reason, candidates_list in failed_reasons.items():
        if candidates_list:
            label = reason_labels.get(reason, reason)
            print(f"   {label}: {len(candidates_list)} candidat(s)")
            
            # Afficher des exemples
            if len(candidates_list) <= 5:
                for c in candidates_list:
                    name = c.get('name', 'N/A')
                    email = c.get('email', 'N/A')
                    phone = c.get('phone', '')
                    if phone:
                        print(f"      - {name} ({email}) - Tél: {phone}")
                    else:
                        print(f"      - {name} ({email})")
            else:
                for c in candidates_list[:5]:
                    name = c.get('name', 'N/A')
                    email = c.get('email', 'N/A')
                    phone = c.get('phone', '')
                    if phone:
                        print(f"      - {name} ({email}) - Tél: {phone}")
                    else:
                        print(f"      - {name} ({email})")
                print(f"      ... et {len(candidates_list) - 5} autres")
            
            # Détails supplémentaires
            if reason == 'wrong_formation' and candidates_list:
                print(f"      Détails formation:")
                for c in candidates_list[:3]:
                    print(f"         - {c.get('candidate_formation')} vs {c.get('group_formation')}")
            
            if reason == 'phone_mismatch_likely' and candidates_list:
                print(f"      Formats de téléphone (exemples):")
                for c in candidates_list[:5]:
                    phone = c.get('phone', '')
                    phone_norm = c.get('phone_normalized', '')
                    print(f"         - {phone} (normalisé: {phone_norm})")
                    print(f"           Le candidat doit saisir EXACTEMENT: {phone}")
                    print(f"           Ou essayer: {phone_norm}, +{phone_norm}, {phone_norm[-9:]}")
            
            print()
    
    print(f"{'='*70}")
    print(f"RÉSUMÉ")
    print(f"{'='*70}\n")
    
    print(f"Total candidats dans le groupe: {len(normalized_group_ids)}")
    print(f"Connectés avec succès: {len(connected_emails)}")
    print(f"Non connectés: {total_failed}")
    print(f"Taux de connexion: {(len(connected_emails) / len(normalized_group_ids) * 100) if normalized_group_ids else 0:.1f}%\n")
    
    # Recommandations
    print(f"{'='*70}")
    print(f"RECOMMANDATIONS")
    print(f"{'='*70}\n")
    
    if failed_reasons['phone_mismatch_likely']:
        print("💡 PROBLÈME PRINCIPAL: Téléphone ne correspond pas")
        print(f"   {len(failed_reasons['phone_mismatch_likely'])} candidat(s) ont probablement saisi")
        print(f"   leur téléphone dans un format différent de celui en base.")
        print(f"\n   Solutions:")
        print(f"   1. Informer les candidats du format exact de leur téléphone")
        print(f"   2. Améliorer la fonction de comparaison de téléphone dans le backend")
        print(f"   3. Permettre plusieurs formats de saisie (avec/sans indicatif, espaces, etc.)\n")
    
    if failed_reasons['wrong_formation']:
        print("💡 PROBLÈME: Formation différente")
        print(f"   {len(failed_reasons['wrong_formation'])} candidat(s) ont une formation différente")
        print(f"   Vérifiez si ces candidats devraient être dans ce groupe.\n")
    
    if failed_reasons['no_phone']:
        print("💡 PROBLÈME: Pas de téléphone")
        print(f"   {len(failed_reasons['no_phone'])} candidat(s) n'ont pas de téléphone en base.")
        print(f"   Ajoutez leur téléphone dans la base de données.\n")
    
    if failed_reasons['test_not_started'] or failed_reasons['test_expired']:
        print("💡 PROBLÈME: Test pas accessible")
        if failed_reasons['test_not_started']:
            print(f"   {len(failed_reasons['test_not_started'])} candidat(s) ont essayé avant le début du test")
        if failed_reasons['test_expired']:
            print(f"   {len(failed_reasons['test_expired'])} candidat(s) ont essayé après la fin du test")
        print()
    
    print()

