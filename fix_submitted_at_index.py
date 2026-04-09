"""
Script pour identifier et supprimer l'index submitted_at problématique de MongoDB
À exécuter une seule fois pour corriger le problème d'index

Usage:
    python fix_submitted_at_index.py
"""
from app import create_app, db
from pymongo import MongoClient
import os
from dotenv import load_dotenv

def fix_indexes():
    """Supprime l'index submitted_at des collections MongoDB"""
    load_dotenv()
    
    app = create_app()
    with app.app_context():
        # Récupérer l'URI de connexion MongoDB depuis la config
        mongo_uri = os.getenv('MONGO_URI', os.getenv('MONGODB_URI', 'mongodb://localhost:27017/odcdb'))
        
        # Extraire le nom de la base de données
        if '/' in mongo_uri:
            db_name = mongo_uri.split('/')[-1].split('?')[0]
            if not db_name or db_name == mongo_uri:
                db_name = os.getenv('MONGO_DBNAME', 'odcdb')
        else:
            db_name = os.getenv('MONGO_DBNAME', 'odcdb')
        
        # Connexion directe à MongoDB
        if '?' in mongo_uri:
            base_uri = mongo_uri.split('?')[0]
        else:
            base_uri = mongo_uri
        
        client = MongoClient(base_uri)
        database = client[db_name]
        
        print(f"\n=== Connexion à la base de données: {db_name} ===")
        
        # Collections à vérifier
        collections_to_check = ['test_results', 'test_groups', 'tests']
        
        total_dropped = 0
        
        for collection_name in collections_to_check:
            collection = database[collection_name]
            
            try:
                indexes = list(collection.list_indexes())
                
                print(f"\n=== Vérification des index pour '{collection_name}' ===")
                
                if not indexes:
                    print(f"  Aucun index trouvé")
                    continue
                
                indexes_to_drop = []
                
                for index in indexes:
                    index_info = dict(index)
                    index_name = index_info.get('name', '')
                    index_keys = index_info.get('key', {})
                    
                    print(f"  Index: {index_name}")
                    print(f"    Clés: {index_keys}")
                    
                    # Chercher les index qui contiennent submitted_at
                    if isinstance(index_keys, dict):
                        if 'submitted_at' in index_keys:
                            indexes_to_drop.append(index_name)
                            print(f"    ⚠️  INDEX PROBLÉMATIQUE TROUVÉ!")
                    elif isinstance(index_keys, (list, str)):
                        if 'submitted_at' in str(index_keys):
                            indexes_to_drop.append(index_name)
                            print(f"    ⚠️  INDEX PROBLÉMATIQUE TROUVÉ!")
                
                # Supprimer les index problématiques
                for index_name in indexes_to_drop:
                    try:
                        collection.drop_index(index_name)
                        print(f"    ✅ Index '{index_name}' supprimé avec succès")
                        total_dropped += 1
                    except Exception as e:
                        print(f"    ❌ Erreur lors de la suppression de '{index_name}': {str(e)}")
                
                if not indexes_to_drop:
                    print(f"  ✅ Aucun index problématique trouvé")
                    
            except Exception as e:
                print(f"  ❌ Erreur lors de la vérification de '{collection_name}': {str(e)}")
        
        print(f"\n=== Résumé ===")
        print(f"Total d'index supprimés: {total_dropped}")
        print(f"✅ Correction terminée")
        
        client.close()

if __name__ == '__main__':
    print("🔍 Recherche des index problématiques 'submitted_at'...")
    fix_indexes()
    print("\n💡 Redémarrez le serveur backend pour que les changements prennent effet.")

