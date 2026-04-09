#!/usr/bin/env python3
"""
Script pour créer un compte administrateur dans la base de données MongoDB
Usage: python create_admin.py
"""

import sys
import os

# Ajouter le dossier parent au path pour pouvoir importer les modules de l'app
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.models.user import User
from werkzeug.security import generate_password_hash

def create_admin():
    """Créer un compte administrateur"""
    app = create_app()
    
    with app.app_context():
        print("\n=== Création d'un compte administrateur ===\n")
        
        # Demander les informations
        email = input("Email de l'administrateur: ").strip()
        
        # Vérifier si l'utilisateur existe déjà
        existing_user = User.objects(email=email).first()
        if existing_user:
            print(f"\n⚠️  Un utilisateur avec l'email {email} existe déjà.")
            update = input("Voulez-vous le mettre à jour en tant qu'admin? (o/n): ").strip().lower()
            if update != 'o':
                print("Opération annulée.")
                return
            user = existing_user
        else:
            user = User()
            user.email = email
            user.first_name = input("Prénom: ").strip()
            user.last_name = input("Nom: ").strip()
        
        # Mot de passe
        password = input("Mot de passe: ").strip()
        if len(password) < 6:
            print("❌ Le mot de passe doit contenir au moins 6 caractères")
            return
        
        user.password_hash = generate_password_hash(password)
        
        # Type d'administrateur
        print("\nType d'administrateur:")
        print("1. Compétences (gestion des formations et tests)")
        print("2. Startups (gestion des startups et programmes)")
        print("3. Super Admin (accès complet)")
        
        admin_type_choice = input("Votre choix (1/2/3): ").strip()
        
        admin_type_map = {
            '1': 'competences',
            '2': 'startups',
            '3': 'super_admin'
        }
        
        if admin_type_choice not in admin_type_map:
            print("❌ Choix invalide")
            return
        
        user.admin_type = admin_type_map[admin_type_choice]
        user.is_admin = True
        user.is_active = True
        user.email_verified = True
        user.profile_type = 'student'  # Valeur par défaut requise
        
        try:
            user.save()
            print(f"\n✅ Administrateur créé avec succès!")
            print(f"   Email: {user.email}")
            print(f"   Type: {user.admin_type}")
            print(f"   ID: {user.id}")
        except Exception as e:
            print(f"\n❌ Erreur lors de la création: {str(e)}")

def list_admins():
    """Lister tous les administrateurs"""
    app = create_app()
    
    with app.app_context():
        admins = User.objects(is_admin=True)
        
        if not admins:
            print("\n📋 Aucun administrateur trouvé dans la base de données.\n")
            return
        
        print("\n=== Liste des administrateurs ===\n")
        for admin in admins:
            print(f"📧 {admin.email}")
            print(f"   Nom: {admin.first_name} {admin.last_name}")
            print(f"   Type: {admin.admin_type or 'Non défini'}")
            print(f"   Actif: {'Oui' if admin.is_active else 'Non'}")
            print(f"   ID: {admin.id}")
            print()

def delete_admin():
    """Supprimer un compte administrateur"""
    app = create_app()
    
    with app.app_context():
        email = input("Email de l'administrateur à supprimer: ").strip()
        
        user = User.objects(email=email, is_admin=True).first()
        
        if not user:
            print(f"\n❌ Aucun administrateur trouvé avec l'email {email}\n")
            return
        
        confirm = input(f"Êtes-vous sûr de vouloir supprimer {user.email}? (o/n): ").strip().lower()
        
        if confirm == 'o':
            user.delete()
            print(f"\n✅ Administrateur {email} supprimé avec succès!\n")
        else:
            print("\nOpération annulée.\n")

def main():
    """Menu principal"""
    while True:
        print("\n=== Gestion des Administrateurs ===")
        print("1. Créer un administrateur")
        print("2. Lister les administrateurs")
        print("3. Supprimer un administrateur")
        print("4. Quitter")
        
        choice = input("\nVotre choix: ").strip()
        
        if choice == '1':
            create_admin()
        elif choice == '2':
            list_admins()
        elif choice == '3':
            delete_admin()
        elif choice == '4':
            print("\nAu revoir! 👋\n")
            break
        else:
            print("\n❌ Choix invalide\n")

if __name__ == '__main__':
    main()


