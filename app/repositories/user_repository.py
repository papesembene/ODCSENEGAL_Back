"""MongoEngine persistence adapter for users."""

from app.models.user import User


class UserRepository:
    @staticmethod
    def find_by_email(email):
        return User.objects(email=email).first()

    @staticmethod
    def create(**values):
        return User(**values)

    @staticmethod
    def save(user):
        user.save()
        return user
