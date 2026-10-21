"""Small Flask binding for MongoEngine, without the obsolete Flask extension."""

import mongoengine


class MongoDatabase:
    def init_app(self, app):
        mongoengine.connect(**app.config["MONGODB_SETTINGS"])
        app.extensions["odc_mongoengine"] = self

    @property
    def connection(self):
        return mongoengine.get_connection()

    def __getattr__(self, name):
        # Preserve the db.Document / db.StringField namespace used by models.
        return getattr(mongoengine, name)


db = MongoDatabase()
