"""Read-only deployment checks. Never seeds data or changes indexes."""

import sys
from urllib.parse import urlsplit

from mongoengine.connection import get_db

from app import create_app
from app.runtime_config import redis_client
from app.services.email_transport import EmailTransport


def main():
    app = create_app()
    settings = app.config["MONGODB_SETTINGS"]
    host = urlsplit(settings["host"]).hostname or "configured MongoDB"
    print(f"MongoDB: {host}; base: {settings['db']}")
    with app.app_context():
        try:
            get_db().command("ping")
            print("MongoDB: accessible")
        except Exception:
            print("ECHEC: MongoDB inaccessible. Verifier reseau et identifiants.")
            return 1
        if app.config.get("SESSION_TYPE") == "redis":
            try:
                with redis_client() as client:
                    client.ping()
                print("Redis: accessible")
            except Exception:
                print("ECHEC: Redis inaccessible")
                return 1
        transport = EmailTransport()
        print(f"Email: {transport.selected_provider}; configuration presente: {transport.is_configured}")
        if not transport.is_configured:
            return 1
    print("Controles techniques OK. Aucun email envoye, aucune donnee modifiee.")
    print("Il reste a tester un vrai email et les parcours depuis l'adresse HTTPS de test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
