import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app, url_for
from werkzeug.exceptions import BadRequest

class FileService:
    # Configuration par défaut
    DEFAULT_ALLOWED_EXTENSIONS = {
        'image': ['png', 'jpg', 'jpeg', 'gif', 'svg'],
        'document': ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'],
        'archive': ['zip', 'rar']
    }
    
    @staticmethod
    def get_file_url(relative_path):
        """Génère l'URL complète pour accéder au fichier"""
        if current_app.config.get('USE_S3', False):
            return f"{current_app.config['S3_BUCKET_URL']}/{relative_path}"
        return url_for('static', filename=relative_path, _external=True)
    
    @staticmethod
    def save_file(file, folder, file_type='document'):
        """
        Sauvegarde un fichier avec validation
        :param file: Fichier à sauvegarder
        :param folder: Dossier de destination (relatif)
        :param file_type: Type de fichier ('image', 'document', 'archive' ou liste personnalisée)
        """
        if not file or file.filename.strip() == '':
            raise BadRequest("Aucun fichier fourni.")

        # Déterminer les extensions autorisées
        if isinstance(file_type, list):
            allowed_extensions = file_type
        else:
            allowed_extensions = FileService.DEFAULT_ALLOWED_EXTENSIONS.get(
                file_type, 
                FileService.DEFAULT_ALLOWED_EXTENSIONS['document']
            )

        if not FileService.allowed_file(file.filename, allowed_extensions):
            raise BadRequest(
                f"Type de fichier non autorisé. Extensions acceptées : {', '.join(allowed_extensions)}"
            )

        # Nettoyer le nom de fichier et générer un nom unique
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"

        # Construire le chemin complet
        upload_base = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        upload_folder = os.path.join(upload_base, folder)
        os.makedirs(upload_folder, exist_ok=True)

        # Chemin relatif (pour la DB) et absolu (pour le système de fichiers)
        relative_path = os.path.join(folder, unique_filename)
        absolute_path = os.path.join(upload_base, relative_path)

        try:
            file.save(absolute_path)
            file_stats = os.stat(absolute_path)
            
            return {
                "filename": filename,
                "path": relative_path,
                "content_type": file.content_type,
                "size": file_stats.st_size
            }
        except Exception as e:
            raise BadRequest(f"Erreur lors de la sauvegarde du fichier : {str(e)}")

    @staticmethod
    def allowed_file(filename, allowed_extensions):
        return (
            '.' in filename and 
            filename.rsplit('.', 1)[1].lower() in {ext.lower() for ext in allowed_extensions}
        )
    
    @staticmethod
    def delete_file(file_path):
        """Supprime un fichier du système de fichiers"""
        if not file_path:
            return False
            
        try:
            full_path = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                return True
            return False
        except Exception as e:
            current_app.logger.error(f"Erreur suppression fichier {file_path}: {str(e)}")
            return False