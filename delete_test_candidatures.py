"""
Script pour supprimer des candidatures de test de la base de données
Usage: python delete_test_candidatures.py
"""

import os
import sys
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Ajouter le répertoire app au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models.candidature import Candidature
from app.config import Config

def delete_by_email(email):
    """Supprimer une candidature par email"""
    try:
        candidature = Candidature.objects(email=email).first()
        if candidature:
            print(f"Trouvée: {candidature.first_name} {candidature.last_name} - {candidature.email}")
            candidature.delete()
            print(f"✓ Candidature supprimée avec succès (email: {email})")
            return True
        else:
            print(f"✗ Aucune candidature trouvée avec l'email: {email}")
            return False
    except Exception as e:
        print(f"✗ Erreur lors de la suppression: {str(e)}")
        return False

def delete_by_cni(cni_number):
    """Supprimer une candidature par numéro CNI/passeport"""
    try:
        candidature = Candidature.objects(cni_or_passport_number=cni_number).first()
        if candidature:
            print(f"Trouvée: {candidature.first_name} {candidature.last_name} - CNI: {cni_number}")
            candidature.delete()
            print(f"✓ Candidature supprimée avec succès (CNI: {cni_number})")
            return True
        else:
            print(f"✗ Aucune candidature trouvée avec le CNI: {cni_number}")
            return False
    except Exception as e:
        print(f"✗ Erreur lors de la suppression: {str(e)}")
        return False

def list_recent_candidatures(limit=10):
    """Lister les candidatures les plus récentes"""
    try:
        candidatures = Candidature.objects().order_by('-created_at').limit(limit)
        print(f"\n📋 Les {limit} candidatures les plus récentes:")
        print("-" * 80)
        for i, cand in enumerate(candidatures, 1):
            print(f"{i}. {cand.first_name} {cand.last_name}")
            print(f"   Email: {cand.email}")
            print(f"   CNI/Passeport: {cand.cni_or_passport_number}")
            print(f"   Date: {cand.created_at}")
            print(f"   ID: {cand.id}")
            print("-" * 80)
    except Exception as e:
        print(f"✗ Erreur lors de la récupération: {str(e)}")

def main():
    print("=" * 80)
    print("Script de suppression de candidatures de test")
    print("=" * 80)
    
    # Créer l'application Flask pour initialiser MongoDB
    app = create_app()
    app.config.from_object(Config)
    
    with app.app_context():
        # Afficher les candidatures récentes pour aider l'utilisateur
        list_recent_candidatures(10)
        
        print("\n" + "=" * 80)
        print("Options de suppression:")
        print("1. Supprimer par email")
        print("2. Supprimer par numéro CNI/Passeport")
        print("3. Supprimer plusieurs candidatures (séparées par des virgules)")
        print("=" * 80)
        
        choice = input("\nVotre choix (1/2/3): ").strip()
        
        if choice == "1":
            email = input("Entrez l'email de la candidature à supprimer: ").strip()
            if email:
                delete_by_email(email)
            else:
                print("✗ Email vide")
        
        elif choice == "2":
            cni = input("Entrez le numéro CNI/Passeport à supprimer: ").strip()
            if cni:
                delete_by_cni(cni)
            else:
                print("✗ Numéro CNI vide")
        
        elif choice == "3":
            print("\nEntrez les emails ou CNI séparés par des virgules (ex: email1@test.com, email2@test.com)")
            values = input("Valeurs: ").strip()
            if values:
                items = [item.strip() for item in values.split(",")]
                deleted_count = 0
                for item in items:
                    # Détecter si c'est un email ou un CNI
                    if "@" in item:
                        if delete_by_email(item):
                            deleted_count += 1
                    else:
                        if delete_by_cni(item):
                            deleted_count += 1
                print(f"\n✓ {deleted_count} candidature(s) supprimée(s) sur {len(items)}")
            else:
                print("✗ Aucune valeur fournie")
        
        else:
            print("✗ Choix invalide")

if __name__ == "__main__":
    main()

