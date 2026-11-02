"""Validated public images shared by editorial content and referentials."""

import os
import uuid

from flask import current_app
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from app.utils.upload_security import IMAGE_EXTENSIONS, validate_upload


def save_public_image(file_storage, category):
    if category not in {"portal", "trainings"}:
        raise ValueError("Unsupported public image category")
    if not file_storage or not file_storage.filename:
        raise BadRequest("Image requise")
    try:
        validate_upload(file_storage, IMAGE_EXTENSIONS, 10 * 1024 * 1024)
    except ValueError as error:
        raise BadRequest(str(error)) from error
    filename = f"{uuid.uuid4().hex}_{secure_filename(file_storage.filename)}"
    folder = os.path.join(current_app.root_path, "static", "uploads", category)
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, filename))
    return f"/static/uploads/{category}/{filename}"
