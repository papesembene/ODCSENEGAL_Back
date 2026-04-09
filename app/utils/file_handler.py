# # backend\app\utils\file_handler.py

# import os
# import uuid
# from werkzeug.utils import secure_filename
# from flask import current_app

# class FileHandler:
#     @staticmethod
#     def allowed_file(filename, file_type):
#         """Vérifier si le fichier est autorisé"""
#         if '.' not in filename:
#             return False
        
#         extension = filename.rsplit('.', 1)[1].lower()
#         allowed_extensions = current_app.config['ALLOWED_EXTENSIONS'].get(file_type, set())
#         return extension in allowed_extensions
    
#     @staticmethod
#     def save_file(file, file_type, subfolder='orangefab'):
#         """Sauvegarder un fichier et retourner le chemin"""
#         if not file or file.filename == '':
#             return None
        
#         if not FileHandler.allowed_file(file.filename, file_type):
#             raise ValueError(f"Type de fichier non autorisé pour {file_type}")
        
#         # Créer un nom de fichier unique
#         filename = secure_filename(file.filename)
#         unique_filename = f"{uuid.uuid4().hex}_{filename}"
        
#         # Créer le dossier de destination
#         upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
#         os.makedirs(upload_folder, exist_ok=True)
        
#         # Sauvegarder le fichier
#         file_path = os.path.join(upload_folder, unique_filename)
#         file.save(file_path)
        
#         # Retourner le chemin relatif
#         return os.path.join(subfolder, unique_filename)
    
#     @staticmethod
#     def delete_file(file_path):
#         """Supprimer un fichier"""
#         try:
#             full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_path)
#             if os.path.exists(full_path):
#                 os.remove(full_path)
#                 return True
#         except Exception as e:
#             print(f"Erreur lors de la suppression du fichier: {e}")
#         return False
    
#     @staticmethod
#     def get_file_size(file_path):
#         """Obtenir la taille d'un fichier"""
#         try:
#             full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_path)
#             return os.path.getsize(full_path)
#         except:
#             return 0



