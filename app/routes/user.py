from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from app.models.user import User
from mongoengine.errors import NotUniqueError

user_bp = Blueprint("user", __name__)

@user_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    try:
        # Crée un utilisateur et hache son mot de passe
        user = User(email=data['email'], password=data['password'])
        user.save()
        return jsonify(message="User registered successfully"), 201
    except NotUniqueError:
        return jsonify(error="Email already registered"), 400

@user_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.objects(email=data['email']).first()
    
    if user and user.check_password(data['password']):
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token), 200
    return jsonify(error="Invalid credentials"), 401
