from flask import Blueprint, request, jsonify
from app.models.job_offer import JobOffer
from flask_jwt_extended import jwt_required

job_offer_bp = Blueprint("job_offer", __name__)

@job_offer_bp.route('/', methods=['GET'])
@jwt_required()
def get_all_job_offers():
    job_offers = JobOffer.objects()
    return jsonify([jo.to_dict() for jo in job_offers])

@job_offer_bp.route('/', methods=['POST'])
@jwt_required()
def create_job_offer():
    data = request.get_json()
    job_offer = JobOffer(title=data['title'], description=data.get('description', ''),
                         company_name=data.get('company_name', ''), location=data.get('location', ''))
    job_offer.save()
    return jsonify(job_offer.to_dict()), 201
