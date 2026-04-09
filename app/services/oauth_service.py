import os
import secrets
import requests
from flask import url_for, current_app, session, request
from werkzeug.exceptions import BadRequest, InternalServerError

class GoogleOAuthService:
    @staticmethod
    def get_auth_url(redirect_uri=None):
        if not redirect_uri:
            redirect_uri = current_app.config['GOOGLE_REDIRECT_URI']
        
        params = {
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'email profile',
            'access_type': 'offline',
            'prompt': 'consent'
        }
        
        auth_url = 'https://accounts.google.com/o/oauth2/auth'
        return f"{auth_url}?{'&'.join([f'{k}={v}' for k,v in params.items()])}"

    @staticmethod
    def get_token(code, redirect_uri=None):
        if not code:
            raise BadRequest("Code manquant")

        if not redirect_uri:
            redirect_uri = current_app.config['GOOGLE_REDIRECT_URI']

        token_url = 'https://oauth2.googleapis.com/token'
        payload = {
            'code': code,
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        try:
            response = requests.post(token_url, data=payload)
            response.raise_for_status()
            token_data = response.json()
            
            current_app.logger.debug(f"Token data: {token_data}")
            
            if not isinstance(token_data, dict):
                raise ValueError("Réponse inattendue de Google")
                
            if 'access_token' not in token_data:
                raise ValueError("Access token manquant dans la réponse")
                
            return token_data
            
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erreur de requête: {str(e)}")
            raise InternalServerError("Erreur de communication avec Google")
        except ValueError as e:
            current_app.logger.error(f"Erreur de parsing JSON: {str(e)}")
            raise InternalServerError("Réponse invalide de Google")

    @staticmethod
    def get_user_info(access_token):
        """
        Récupère les informations de l'utilisateur à partir du token d'accès Google.
        
        Args:
            access_token (str): Le token d'accès Google (pas le dictionnaire complet)
        """
        user_info_url = 'https://www.googleapis.com/oauth2/v3/userinfo'
        headers = {'Authorization': f"Bearer {access_token}"}

        try:
            response = requests.get(user_info_url, headers=headers)
            response.raise_for_status()
            
            user_data = response.json()
            current_app.logger.debug(f"Google user info: {user_data}")
            
            return {
                'oauth_id': user_data.get('sub'),
                'email': user_data.get('email'),
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
                'picture': user_data.get('picture', ''),
                'locale': user_data.get('locale', ''),
                'email_verified': user_data.get('email_verified', False)
            }
        except Exception as e:
            current_app.logger.error(f"Erreur lors de la récupération des infos utilisateur Google: {str(e)}")
            raise InternalServerError(f"Erreur de communication avec Google API: {str(e)}")

class LinkedInOAuthService:
    @staticmethod
    def get_auth_url(redirect_uri=None):
        if not redirect_uri:
            if not current_app.config.get('LINKEDIN_REDIRECT_URI'):
                raise ValueError("LINKEDIN_REDIRECT_URI n'est pas configuré")
            redirect_uri = current_app.config['LINKEDIN_REDIRECT_URI']
        state = secrets.token_urlsafe(16)
        session['linkedin_oauth_state'] = state  # Stockage spécifique à LinkedIn

        # Utiliser les nouveaux scopes LinkedIn
        params = {
            'client_id': current_app.config['LINKEDIN_CLIENT_ID'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid profile email',  # Nouveaux scopes au lieu de r_liteprofile r_emailaddress
            'state': state
        }

        auth_url = 'https://www.linkedin.com/oauth/v2/authorization'
        return f"{auth_url}?{'&'.join([f'{k}={v}' for k,v in params.items()])}"

    @staticmethod
    def get_token(code):
        if not code:
            raise BadRequest("Code manquant")
            
        # Vérification du state
        if request.args.get('state') != session.pop('linkedin_oauth_state', None):
            raise BadRequest("Invalid state parameter")

        token_url = 'https://www.linkedin.com/oauth/v2/accessToken'
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': current_app.config['LINKEDIN_CLIENT_ID'],
            'client_secret': current_app.config['LINKEDIN_CLIENT_SECRET'],
            'redirect_uri': current_app.config['LINKEDIN_REDIRECT_URI']
        }

        response = requests.post(token_url, data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })

        if response.status_code != 200:
            current_app.logger.error(f"LinkedIn token error: {response.text}")
            raise BadRequest("Échec de l'obtention du token LinkedIn")

        return response.json()
    @staticmethod
    def get_user_info(token):
        try:
            # Log du token pour débogage
            current_app.logger.debug(f"LinkedIn token: {token}")
            
            # Vérifier que le token contient access_token
            if not isinstance(token, dict) or 'access_token' not in token:
                current_app.logger.error(f"Token LinkedIn invalide: {token}")
                raise ValueError("Token LinkedIn invalide ou mal formaté")
            
            access_token = token['access_token']
            
            # Avec les nouveaux scopes, nous pouvons utiliser l'endpoint userinfo d'OpenID Connect
            userinfo_url = 'https://api.linkedin.com/v2/userinfo'  # Endpoint userinfo correct
            headers = {
                'Authorization': f"Bearer {access_token}"
            }
            
            current_app.logger.debug(f"Appel à l'API LinkedIn userinfo avec URL: {userinfo_url}")
            
            userinfo_response = requests.get(userinfo_url, headers=headers)
            
            # Log de la réponse complète
            current_app.logger.debug(f"LinkedIn userinfo response status: {userinfo_response.status_code}")
            current_app.logger.debug(f"LinkedIn userinfo response headers: {userinfo_response.headers}")
            current_app.logger.debug(f"LinkedIn userinfo response body: {userinfo_response.text}")
            
            if userinfo_response.status_code != 200:
                # Essayer une approche alternative si userinfo échoue
                return LinkedInOAuthService._get_user_info_alternative(access_token)
            
            user_data = userinfo_response.json()
            
            # Extraire les informations nécessaires
            return {
                'oauth_id': user_data.get('sub'),
                'email': user_data.get('email', ''),
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
                'picture': user_data.get('picture', '')
            }
            
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erreur de requête LinkedIn: {str(e)}")
            raise InternalServerError(f"Erreur de communication avec LinkedIn: {str(e)}")
        except ValueError as e:
            current_app.logger.error(f"Erreur de valeur LinkedIn: {str(e)}")
            raise InternalServerError(f"Erreur de format LinkedIn: {str(e)}")
        except Exception as e:
            current_app.logger.error(f"LinkedIn user info error: {str(e)}", exc_info=True)
            raise InternalServerError(f"Erreur lors de la récupération des infos LinkedIn: {str(e)}")

    @staticmethod
    def _get_user_info_alternative(access_token):
        """Méthode alternative pour récupérer les informations utilisateur LinkedIn"""
        current_app.logger.debug("Utilisation de la méthode alternative pour récupérer les infos LinkedIn")
        
        try:
            # 1. Récupérer le profil de base
            profile_url = 'https://api.linkedin.com/v2/me'
            headers = {
                'Authorization': f"Bearer {access_token}",
                'X-Restli-Protocol-Version': '2.0.0'
            }
            
            profile_response = requests.get(profile_url, headers=headers)
            profile_response.raise_for_status()
            profile_data = profile_response.json()
            
            current_app.logger.debug(f"LinkedIn profile data: {profile_data}")
            
            # 2. Essayer de récupérer l'email
            email = None
            try:
                email_url = 'https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))'
                email_response = requests.get(email_url, headers=headers)
                
                if email_response.status_code == 200:
                    email_data = email_response.json()
                    current_app.logger.debug(f"LinkedIn email data: {email_data}")
                    email = email_data.get('elements', [{}])[0].get('handle~', {}).get('emailAddress', '')
            except Exception as e:
                current_app.logger.warning(f"Impossible de récupérer l'email LinkedIn: {str(e)}")
            
            # 3. Si pas d'email, générer un email temporaire
            if not email:
                linkedin_id = profile_data.get('id')
                email = f"linkedin_{linkedin_id}@example.com"
                current_app.logger.warning(f"Email LinkedIn non disponible, utilisation d'un email temporaire: {email}")
            
            # 4. Construire la réponse
            return {
                'oauth_id': profile_data.get('id'),
                'email': email,
                'first_name': profile_data.get('localizedFirstName', ''),
                'last_name': profile_data.get('localizedLastName', ''),
                'picture': ''  # Pas de photo disponible dans cette méthode alternative
            }
        except Exception as e:
            current_app.logger.error(f"Erreur méthode alternative LinkedIn: {str(e)}", exc_info=True)
            raise InternalServerError(f"Erreur lors de la récupération alternative des infos LinkedIn: {str(e)}")
    @staticmethod
    def _extract_profile_picture(profile_data):
        try:
            elements = profile_data.get('profilePicture', {}).get('displayImage~', {}).get('elements', [])
            if elements:
                return elements[0].get('identifiers', [{}])[0].get('identifier', '')
        except Exception:
            return ''
# 💡 Cette méthode est à adapter selon ton système (base PostgreSQL, JWT, session...)
def handle_oauth_login(provider, oauth_id, user_info):
    """
    Fonction de gestion de connexion ou création utilisateur à partir des infos OAuth.
    À adapter selon ton système d'authentification.
    """
    # Exemple : recherche ou création d'utilisateur dans la base
    # user = db.get_user_by_oauth(provider, oauth_id)
    # if not user:
    #     user = db.create_user_from_oauth(provider, oauth_id, user_info)
    # token = generate_jwt_for_user(user)
    # return token
    raise NotImplementedError("Intègre ici la logique de création/connexion utilisateur.")
