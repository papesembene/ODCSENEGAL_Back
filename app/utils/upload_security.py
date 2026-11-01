"""Bounded uploads: extension and basic container signatures, never MIME trust."""
import os
from pathlib import Path
import zipfile


DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def validate_upload(file, allowed, max_bytes):
    filename = getattr(file, "filename", "") or ""
    extension = Path(filename.replace("\\", "/")).suffix.lower().lstrip(".")
    if extension not in allowed:
        raise ValueError("Format de fichier non autorisé")
    stream = getattr(file, "stream", file)
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if not 0 < size <= max_bytes:
        raise ValueError("Fichier vide ou trop volumineux")
    header = stream.read(16)
    stream.seek(0)
    signatures = {
        "pdf": header.startswith(b"%PDF-"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": header.startswith(b"\xff\xd8\xff"),
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "doc": header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "ppt": header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "xls": header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    }
    try:
        if extension in {"docx", "pptx", "xlsx"}:
            stream.seek(max(0, size - 65557))
            tail = stream.read(65557)
            end = tail.rfind(b"PK\x05\x06")
            if end < 0 or len(tail) < end + 22:
                raise ValueError("Document Office invalide")
            entries = int.from_bytes(tail[end + 10:end + 12], "little")
            directory_bytes = int.from_bytes(tail[end + 12:end + 16], "little")
            if entries > 10000 or directory_bytes > 4 * 1024 * 1024:
                raise ValueError("Document Office trop complexe")
            stream.seek(0)
            # Inspect directory entries without extracting or inflating file contents.
            with zipfile.ZipFile(stream) as archive:
                if len(archive.infolist()) > 10000 or sum(item.file_size for item in archive.infolist()) > max_bytes * 4:
                    raise ValueError("Document Office décompressé trop volumineux")
                names = set(archive.namelist())
                prefix = {"docx": "word/", "pptx": "ppt/", "xlsx": "xl/"}[extension]
                valid = "[Content_Types].xml" in names and any(name.startswith(prefix) for name in names)
                valid = valid and not any(name.lower().endswith("vbaproject.bin") for name in names)
        else:
            valid = signatures.get(extension, False)
        if not valid:
            raise ValueError("Le contenu du fichier ne correspond pas au format autorisé")
    except (zipfile.BadZipFile, OSError) as error:
        raise ValueError("Document invalide") from error
    finally:
        stream.seek(0)
    return size
