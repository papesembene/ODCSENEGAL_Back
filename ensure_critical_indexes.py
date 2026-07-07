"""Synchronise les index MongoDB critiques pour la plateforme.

Usage:
    .venv/bin/python ensure_critical_indexes.py

Cette commande ne supprime aucune donnée. Elle crée seulement les index
MongoDB manquants déclarés dans les modèles critiques.
"""

from app import create_app
from app.utils.fix_indexes import ensure_critical_indexes


def main():
    app = create_app()
    with app.app_context():
        collections = ensure_critical_indexes()
        print("Index critiques synchronisés:")
        for collection in collections:
            print(f"- {collection}")


if __name__ == "__main__":
    main()
