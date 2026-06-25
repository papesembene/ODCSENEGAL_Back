"""OAuth provider clients with bounded network calls."""

import secrets
from urllib.parse import urlencode

import requests
from flask import current_app, request, session
from werkzeug.exceptions import BadRequest, InternalServerError


REQUEST_TIMEOUT = (5, 15)


def _request_json(method, url, **kwargs):
    try:
        response = requests.request(
            method,
            url,
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Réponse JSON inattendue")
        return payload
    except (requests.RequestException, ValueError) as error:
        current_app.logger.warning(
            "Échec OAuth vers %s: %s",
            url,
            error,
        )
        raise InternalServerError(
            "Erreur de communication avec le fournisseur OAuth"
        ) from error


class GoogleOAuthService:
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    @staticmethod
    def get_auth_url(redirect_uri=None):
        redirect_uri = (
            redirect_uri or current_app.config["GOOGLE_REDIRECT_URI"]
        )
        state = secrets.token_urlsafe(32)
        session["google_oauth_state"] = state
        return f"{GoogleOAuthService.AUTHORIZE_URL}?{urlencode({
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'email profile',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
        })}"

    @staticmethod
    def validate_state():
        expected = session.pop("google_oauth_state", None)
        if not expected or request.args.get("state") != expected:
            raise BadRequest("Paramètre state Google invalide")

    @staticmethod
    def get_token(code, redirect_uri=None):
        if not code:
            raise BadRequest("Code manquant")
        redirect_uri = (
            redirect_uri or current_app.config["GOOGLE_REDIRECT_URI"]
        )
        payload = _request_json(
            "POST",
            GoogleOAuthService.TOKEN_URL,
            data={
                "code": code,
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config[
                    "GOOGLE_CLIENT_SECRET"
                ],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if not payload.get("access_token"):
            raise InternalServerError(
                "Access token absent de la réponse Google"
            )
        return payload

    @staticmethod
    def get_user_info(access_token):
        payload = _request_json(
            "GET",
            GoogleOAuthService.USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return {
            "oauth_id": payload.get("sub"),
            "email": payload.get("email"),
            "first_name": payload.get("given_name", ""),
            "last_name": payload.get("family_name", ""),
            "picture": payload.get("picture", ""),
            "locale": payload.get("locale", ""),
            "email_verified": payload.get("email_verified", False),
        }


class LinkedInOAuthService:
    AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    USER_INFO_URL = "https://api.linkedin.com/v2/userinfo"

    @staticmethod
    def get_auth_url(redirect_uri=None):
        redirect_uri = (
            redirect_uri or current_app.config["LINKEDIN_REDIRECT_URI"]
        )
        if not redirect_uri:
            raise BadRequest(
                "LINKEDIN_REDIRECT_URI n'est pas configuré"
            )
        state = secrets.token_urlsafe(32)
        session["linkedin_oauth_state"] = state
        return f"{LinkedInOAuthService.AUTHORIZE_URL}?{urlencode({
            'client_id': current_app.config['LINKEDIN_CLIENT_ID'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid profile email',
            'state': state,
        })}"

    @staticmethod
    def get_token(code):
        if not code:
            raise BadRequest("Code manquant")
        expected = session.pop("linkedin_oauth_state", None)
        if not expected or request.args.get("state") != expected:
            raise BadRequest("Paramètre state LinkedIn invalide")
        return _request_json(
            "POST",
            LinkedInOAuthService.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": current_app.config["LINKEDIN_CLIENT_ID"],
                "client_secret": current_app.config[
                    "LINKEDIN_CLIENT_SECRET"
                ],
                "redirect_uri": current_app.config[
                    "LINKEDIN_REDIRECT_URI"
                ],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
        )

    @staticmethod
    def get_user_info(token):
        access_token = (
            token.get("access_token")
            if isinstance(token, dict)
            else None
        )
        if not access_token:
            raise InternalServerError("Token LinkedIn invalide")
        payload = _request_json(
            "GET",
            LinkedInOAuthService.USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if not payload.get("email"):
            raise InternalServerError(
                "LinkedIn n'a pas fourni d'adresse email"
            )
        return {
            "oauth_id": payload.get("sub"),
            "email": payload.get("email"),
            "first_name": payload.get("given_name", ""),
            "last_name": payload.get("family_name", ""),
            "picture": payload.get("picture", ""),
        }
