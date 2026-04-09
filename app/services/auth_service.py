from app.models.user import User, StudentProfile, StartupProfile, CorporateInvestorProfile
from datetime import datetime, timedelta
from flask import current_app
from werkzeug.exceptions import Unauthorized, BadRequest
import jwt
import logging
import secrets
import string
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

class AuthService:
    @staticmethod
    def login_with_email(email, password):
        user = User.objects(email=email).first()

        if not user or not user.check_password(password):
            raise Unauthorized("Email ou mot de passe incorrect")

        if not user.is_active:
            raise Unauthorized("Compte désactivé. Veuillez contacter l'administrateur.")

        user.last_login = datetime.utcnow()
        user.save()

        logger.info(f"Connexion réussie pour l'utilisateur {user.email}")
        return AuthService.generate_token(user)

    @staticmethod
    def login_admin(email, password):
        """
        Authentifie un administrateur
        """
        user = User.objects(email=email).first()

        if not user or not user.check_password(password):
            raise Unauthorized("Email ou mot de passe incorrect")

        if not user.is_active:
            raise Unauthorized("Compte désactivé. Veuillez contacter l'administrateur.")

        # Vérifier que l'utilisateur est bien un admin
        if not user.is_admin:
            raise Unauthorized("Accès non autorisé. Cette page est réservée aux administrateurs.")

        user.last_login = datetime.utcnow()
        user.save()

        logger.info(f"Connexion admin réussie pour {user.email} (type: {user.admin_type})")
        return AuthService.generate_token(user)

    
    @staticmethod
    def login_with_oauth(provider, oauth_id, oauth_data):
        """
        Authentifie un utilisateur via OAuth.
        
        Args:
            provider (str): Le fournisseur OAuth ('google', 'linkedin', etc.)
            oauth_id (str): L'identifiant unique de l'utilisateur chez le fournisseur
            oauth_data (dict): Les données utilisateur fournies par le fournisseur OAuth
        
        Returns:
            dict: Contient le token JWT et les informations utilisateur
        """
        user = User.objects(oauth_provider=provider, oauth_id=oauth_id).first()

        if not user:
            email = oauth_data.get('email')
            if not email:
                raise BadRequest("L'email est requis pour l'authentification OAuth")

            user = User.objects(email=email).first()
            if user:
                # Associer un compte existant à OAuth
                user.oauth_provider = provider
                user.oauth_id = oauth_id
                user.oauth_data = oauth_data
            else:
                # Générer un mot de passe aléatoire pour les utilisateurs OAuth
                # (ils n'auront jamais besoin de s'en servir, c'est juste pour satisfaire la contrainte du modèle)
                random_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
                password_hash = generate_password_hash(random_password)
                
                # Créer un nouvel utilisateur
                user = User(
                    email=email,
                    password_hash=password_hash,  # Ajout du password_hash
                    first_name=oauth_data.get('first_name', ''),
                    last_name=oauth_data.get('last_name', ''),
                    profile_picture=oauth_data.get('picture', ''),
                    oauth_provider=provider,
                    oauth_id=oauth_id,
                    oauth_data=oauth_data,
                    is_active=True,
                    profile_type='student'  # Valeur par défaut pour les utilisateurs OAuth
                )

        # Mise à jour de la photo si elle a changé
        picture = oauth_data.get('picture')
        if picture and picture != user.profile_picture:
            user.profile_picture = picture

        user.last_login = datetime.utcnow()
        user.save()

        logger.info(f"Connexion OAuth réussie pour l'utilisateur {user.email}")
        return AuthService.generate_token(user)
    @staticmethod
    def generate_token(user):
        secret_key = current_app.config['JWT_SECRET_KEY']
        expiration_delta = current_app.config.get('JWT_EXPIRATION_DELTA', timedelta(days=1))

        if not isinstance(expiration_delta, timedelta):
            expiration_delta = timedelta(days=1)

        payload = {
        'sub': str(user.id),  # Claim standard JWT pour le subject
        'user_id': str(user.id),
        'email': user.email,
        'profile_type': user.profile_type,
        'is_admin': user.is_admin if hasattr(user, 'is_admin') else False,
        'admin_type': user.admin_type if hasattr(user, 'admin_type') else None,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + current_app.config['JWT_EXPIRATION_DELTA'],
        'iss': current_app.config.get('JWT_ISSUER', 'your-app-name')
    }

        token = jwt.encode(payload, secret_key, algorithm='HS256')

        return {
            'token': token,
            'user': AuthService.user_to_safe_json(user)
        }

    @staticmethod
    def verify_token(token):
        try:
            payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=['HS256'],
            options={
                "verify_signature": True,
                "require": ["exp", "iat", "sub"]
            }
        )

            user = User.objects(id=payload['user_id']).first()

            if not user or not user.is_active:
                raise Unauthorized("Utilisateur non trouvé ou inactif")

            return user

        except jwt.ExpiredSignatureError:
            raise Unauthorized("Token expiré")
        except jwt.InvalidTokenError:
            raise Unauthorized("Token invalide")

    @staticmethod
    def get_current_user():
        """Obtient l'utilisateur actuel à partir du token JWT dans le contexte"""
        from flask_jwt_extended import get_jwt_identity
        user_id = get_jwt_identity()
        return User.objects(id=user_id).first()

    @staticmethod
    def user_to_safe_json(user):
        """Convertit un objet User en JSON sécurisé (sans données sensibles)"""
        base_data = {
            'id': str(user.id),
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'profile_picture': user.profile_picture,
            'profile_type': user.profile_type,
            'oauth_provider': user.oauth_provider,
            'is_active': user.is_active,
            'email_verified': user.email_verified,
            'is_admin': user.is_admin if hasattr(user, 'is_admin') else False,
            'admin_type': user.admin_type if hasattr(user, 'admin_type') else None
        }

        # Ajouter les données de profil spécifiques
        if user.profile_type == 'student' and user.student_profile:
            base_data['profile_data'] = {
                'institution': user.student_profile.institution,
                'education_level': user.student_profile.education_level,
                'sector': user.student_profile.sector,
                'motivations': user.student_profile.motivations,
                'interests': user.student_profile.interests,
                'has_cv': user.student_profile.cv_file is not None,
                'has_cover_letter': user.student_profile.cover_letter_file is not None
            }
        elif user.profile_type == 'startup' and user.startup_profile:
            base_data['profile_data'] = {
                'company_name': user.startup_profile.company_name,
                'company_sector': user.startup_profile.company_sector,
                'location': user.startup_profile.location,
                'value_proposition': user.startup_profile.value_proposition,
                'maturity_stage': user.startup_profile.maturity_stage,
                'founding_team': user.startup_profile.founding_team,
                'needs': user.startup_profile.needs,
                'has_logo': user.startup_profile.logo_file is not None,
                'has_pitch_deck': user.startup_profile.pitch_deck_file is not None,
                'has_business_plan': user.startup_profile.business_plan_file is not None
            }
        elif user.profile_type in ['corporate', 'investor'] and user.corporate_investor_profile:
            base_data['profile_data'] = {
                'organization_name': user.corporate_investor_profile.organization_name,
                'activities': user.corporate_investor_profile.activities,
                'interest_sectors': user.corporate_investor_profile.interest_sectors,
                'cooperation_objectives': user.corporate_investor_profile.cooperation_objectives,
                'has_brochure': user.corporate_investor_profile.brochure_file is not None
            }

        return base_data

    @staticmethod
    def verify_email(token):
        """Vérifie l'email d'un utilisateur à partir d'un token"""
        try:
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256'],
                options={"require": ["exp", "iat", "iss"]},
                issuer=current_app.config.get('JWT_ISSUER', 'your-app-name')
            )

            user = User.objects(id=payload['user_id']).first()

            if not user:
                raise Unauthorized("Utilisateur non trouvé")

            if user.email_verified:
                return {"success": True, "message": "Email déjà vérifié"}

            user.email_verified = True
            user.save()

            return {"success": True, "message": "Email vérifié avec succès"}

        except jwt.ExpiredSignatureError:
            raise Unauthorized("Token de vérification expiré")
        except jwt.InvalidTokenError:
            raise Unauthorized("Token de vérification invalide")