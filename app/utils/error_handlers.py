from flask import jsonify
from werkzeug.exceptions import HTTPException

def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        response = jsonify({
            'error': True,
            'message': error.description,
            'status_code': error.code
        })
        response.status_code = error.code
        return response
    
    @app.errorhandler(Exception)
    def handle_generic_exception(error):
        app.logger.error(f"Unhandled exception: {str(error)}")
        response = jsonify({
            'error': True,
            'message': "Une erreur interne est survenue",
            'status_code': 500
        })
        response.status_code = 500
        return response
