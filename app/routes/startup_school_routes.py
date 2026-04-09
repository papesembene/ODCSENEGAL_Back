from flask import Blueprint, request, jsonify
from app.models.startup_school import StartupSchool
from flask_jwt_extended import jwt_required

startup_school_bp = Blueprint("startup_school", __name__)

@startup_school_bp.route('/', methods=['GET'])
@jwt_required()
def get_all_startup_schools():
    startup_schools = StartupSchool.objects()
    return jsonify([ss.to_dict() for ss in startup_schools])

@startup_school_bp.route('/', methods=['POST'])
@jwt_required()
def create_startup_school():
    data = request.get_json()
    startup_school = StartupSchool(name=data['name'], description=data.get('description', ''),
                                   start_date=data.get('start_date'), end_date=data.get('end_date'))
    startup_school.save()
    return jsonify(startup_school.to_dict()), 201
