from flask import Blueprint, request, jsonify
from app.models.competence import Competence
from flask_jwt_extended import jwt_required

competence_bp = Blueprint("competence", __name__)

@competence_bp.route('/', methods=['GET'])
@jwt_required()
def get_all_competences():
    competences = Competence.objects()
    return jsonify([c.to_dict() for c in competences])

@competence_bp.route('/', methods=['POST'])
@jwt_required()
def create_competence():
    data = request.get_json()
    competence = Competence(name=data['name'], description=data.get('description', ''), level=data.get('level', ''))
    competence.save()
    return jsonify(competence.to_dict()), 201
