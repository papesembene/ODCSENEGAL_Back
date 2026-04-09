"""
Utilitaire pour corriger les index MongoDB problématiques
Supprime automatiquement les index obsolètes qui référencent des champs inexistants

⚠️ IMPORTANT : Cette fonction supprime UNIQUEMENT les INDEX, PAS les données !
- drop_index() : Supprime seulement la structure d'index (sûr, ne touche pas aux données)
- Les documents (vos données) restent intacts
- Les index sont juste des structures de référencement pour accélérer les recherches
"""
from app import db
import logging

logger = logging.getLogger(__name__)

def fix_problematic_indexes():
    """
    Supprime les index MongoDB qui référencent des champs inexistants
    Appelé au démarrage de l'application pour éviter les erreurs
    """
    try:
        # Récupérer la connexion MongoDB via MongoEngine
        # MongoEngine stocke la connexion dans db.connection
        from flask import current_app
        from app import db
        
        # Accéder à la base de données via MongoEngine
        # db.connection est un MongoClient, on peut obtenir la base de données de plusieurs façons
        try:
            # Méthode 1: Via get_database() si disponible
            if hasattr(db.connection, 'get_database'):
                database = db.connection.get_database()
            else:
                # Méthode 2: Accéder directement via la configuration
                from app.config import Config
                db_name = Config.MONGODB_SETTINGS.get('db', 'odcdb')
                database = db.connection[db_name]
        except Exception:
            # Méthode 3: Via le nom de la base dans la config
            db_name = current_app.config.get('MONGODB_SETTINGS', {}).get('db', 'odcdb')
            database = db.connection[db_name]
        
        # Collections à vérifier
        collections_to_check = {
            'test_results': ['submitted_at'],
            'test_groups': ['submitted_at'],
            'tests': ['submitted_at'],
            'candidatures': ['submitted_at']
        }
        
        total_dropped = 0
        
        for collection_name, problematic_fields in collections_to_check.items():
            try:
                collection = database[collection_name]
                indexes = list(collection.list_indexes())
                
                for index in indexes:
                    index_info = dict(index)
                    index_name = index_info.get('name', '')
                    index_keys = index_info.get('key', {})
                    
                    # Vérifier si l'index contient un champ problématique
                    should_drop = False
                    if isinstance(index_keys, dict):
                        for field in problematic_fields:
                            if field in index_keys:
                                should_drop = True
                                logger.warning(
                                    f"Index problématique trouvé dans {collection_name}: "
                                    f"'{index_name}' référence le champ '{field}' qui n'existe plus"
                                )
                                break
                    
                    if should_drop:
                        try:
                            # ⚠️ SÉCURITÉ : drop_index() supprime UNIQUEMENT l'index, PAS les données
                            # Les documents (données réelles) restent intacts
                            collection.drop_index(index_name)
                            logger.info(
                                f"✅ Index '{index_name}' supprimé de la collection '{collection_name}' "
                                f"(les données sont intactes)"
                            )
                            total_dropped += 1
                        except Exception as e:
                            logger.error(
                                f"❌ Erreur lors de la suppression de l'index '{index_name}' "
                                f"dans '{collection_name}': {str(e)}"
                            )
                            
            except Exception as e:
                logger.warning(f"Impossible de vérifier les index pour '{collection_name}': {str(e)}")
                continue
        
        if total_dropped > 0:
            logger.info(f"🎯 Total d'index problématiques supprimés: {total_dropped}")
        else:
            logger.debug("✅ Aucun index problématique trouvé")
            
        return total_dropped
        
    except Exception as e:
        logger.error(f"Erreur lors de la correction des index: {str(e)}")
        return 0

