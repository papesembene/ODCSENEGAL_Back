from flask import Blueprint

connect_bp = Blueprint('connect', __name__)

@connect_bp.route('/')
def index_connect():
    return {"message": "Bienvenue dans le module Connect"}
