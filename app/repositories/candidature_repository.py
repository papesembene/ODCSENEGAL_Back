"""MongoEngine persistence adapter for ODC candidatures."""

from app.models.candidature import Candidature


class CandidatureRepository:
    def create(self, **values):
        return Candidature(**values)

    @staticmethod
    def save(candidature):
        candidature.save()
        return candidature

    @staticmethod
    def delete(candidature):
        candidature.delete()

    @staticmethod
    def get(candidature_id):
        return Candidature.objects(id=candidature_id).first()

    @staticmethod
    def find_by_email(email):
        return Candidature.objects(email=email).only("id").first()

    @staticmethod
    def find_by_identity_number(identity_number):
        return Candidature.objects(
            cni_or_passport_number=identity_number,
        ).only("id").first()

    @staticmethod
    def list_filtered(filters, search="", page=None, per_page=None):
        query = Candidature.objects(**filters)
        if search:
            regex = {"$regex": search, "$options": "i"}
            query = query.filter(__raw__={
                "$or": [
                    {"first_name": regex},
                    {"last_name": regex},
                    {"email": regex},
                    {"phone": regex},
                ],
            })
        query = query.order_by("-created_at")
        if page is not None and per_page is not None:
            offset = max(page - 1, 0) * per_page
            return query.skip(offset).limit(per_page)
        return query

    @staticmethod
    def count_filtered(filters, search=""):
        query = Candidature.objects(**filters)
        if search:
            regex = {"$regex": search, "$options": "i"}
            query = query.filter(__raw__={
                "$or": [
                    {"first_name": regex},
                    {"last_name": regex},
                    {"email": regex},
                    {"phone": regex},
                ],
            })
        return query.count()

    @staticmethod
    def list_by_ids(candidate_ids):
        return Candidature.objects(id__in=candidate_ids)

    @staticmethod
    def list_for_training(desired_training=None):
        if desired_training and desired_training != "all":
            return Candidature.objects(
                desired_training=desired_training,
            )
        return Candidature.objects()
