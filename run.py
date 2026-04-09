import os
import time
import json
import socket
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, request, g, has_request_context
from flask_cors import CORS
from elasticapm.contrib.flask import ElasticAPM
from app.config import Config
from app import create_app
import logging
from logging.handlers import TimedRotatingFileHandler
import uuid
import re
from logging.handlers import RotatingFileHandler
 
 
 
# -----------------------------
# 0️⃣ Pré-configuration et helpers
# -----------------------------
# Créer le répertoire de logs (si absent)
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir, exist_ok=True)
 
# Helper pour timestamp ISO UTC
def now_iso_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
 
# -----------------------------
# 1️⃣ Formatters personnalisés
# -----------------------------
class JsonFormatter(logging.Formatter):
    """Formatter pour logs en JSON"""
    def format(self, record):
        # Build a base structure
        log_object = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'source_module': getattr(record, 'source_module', record.module),
            'function': record.funcName,
            'line': record.lineno,
            'process_id': os.getpid(),
            'thread_name': record.threadName,
        }
 
        # Add our optional context attributes safely
        for attr, key in [
            ('request_id', 'request_id'),
            ('client_ip', 'client_ip'),
            ('user_agent', 'user_agent'),
            ('response_time', 'response_time_ms'),
            ('status_code', 'status_code'),
            ('http_method', 'method'),
            ('endpoint', 'endpoint'),
            ('log_action', 'action'),
            ('response_size', 'response_size'),
        ]:
            if hasattr(record, attr):
                log_object[key] = getattr(record, attr)
 
        # Exception info
        if record.exc_info:
            log_object['exception'] = {
                'type': str(record.exc_info[0].__name__),
                'message': str(record.exc_info[1]),
                'traceback': self.formatException(record.exc_info)
            }
 
        return json.dumps(log_object, ensure_ascii=False)
 
class DetailedFormatter(logging.Formatter):

    """Formatter pour logs texte détaillés"""

    def format(self, record):

        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]

        message_parts = [

            f"{timestamp}",

            f"PID:{os.getpid():<6}",

            f"TID:{record.threadName:>5}",

            f"{record.levelname:<8}",

        ]
 
        # Request ID

        request_id = getattr(record, "request_id", None)

        message_parts.append(f"REQ:{str(request_id)[:8] if request_id else '--------'}")
 
        # Client IP : SAFE

        client_ip = getattr(record, "client_ip", None)

        message_parts.append(f"IP:{client_ip if client_ip else '---':<15}")
 
        # HTTP method & endpoint

        http_method = getattr(record, "http_method", None)

        endpoint = getattr(record, "endpoint", None)
 
        if http_method and endpoint:

            message_parts.append(f"{http_method:<7} {endpoint}")

        elif http_method:

            message_parts.append(f"{http_method:<7}")
 
        # Status code

        status_code = getattr(record, "status_code", None)

        if status_code is not None:

            message_parts.append(f"STATUS:{status_code}")
 
        # Response time

        response_time = getattr(record, "response_time", None)

        if response_time is not None:

            message_parts.append(f"TIME:{response_time:>7.2f}ms")
 
        # Message final

        message_parts.append(f"- {record.getMessage()}")
 
        # Exception handling

        if record.exc_info:

            message_parts.append(f"\n{self.formatException(record.exc_info)}")
 
        return ' | '.join(message_parts)
 
class ColorFormatter(logging.Formatter):
    """Formatter avec couleurs pour la console"""
    COLORS = {
        'DEBUG': '\033[37m',      # White
        'INFO': '\033[36m',       # Cyan
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[41m',   # Red background
    }
    RESET = '\033[0m'
 
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
 
        parts = []
        parts.append(f"{color}{timestamp} {record.levelname:<8}{self.RESET}")
 
        if hasattr(record, 'request_id'):
            parts.append(f"[{str(record.request_id)[:8]}]")
 
        if hasattr(record, 'client_ip'):
            parts.append(f"{record.client_ip}")
 
        if hasattr(record, 'http_method') and hasattr(record, 'endpoint'):
            parts.append(f"{record.http_method} {record.endpoint}")
 
        parts.append(f"- {record.getMessage()}")
 
        if hasattr(record, 'response_time'):
            try:
                parts.append(f"({record.response_time:.2f}ms)")
            except Exception:
                pass
 
        return ' '.join(parts)
 
# -----------------------------
# 2️⃣ Request context filter
# -----------------------------
class RequestContextFilter(logging.Filter):
    """
    Enrichit les LogRecord avec des informations de la requête Flask si disponibles.
    Ajoute : request_id, client_ip, user_agent, http_method, endpoint
    """
    def filter(self, record):
        try:
            if has_request_context():
                # request_id peut être dans g, sinon none
                record.request_id = getattr(g, 'request_id', None)
                record.client_ip = getattr(g, 'client_ip', None) or _safe_get_client_ip()
                record.user_agent = request.headers.get('User-Agent', None)
                record.http_method = request.method
                record.endpoint = request.path
            else:
                # Pas de contexte; mettre None pour garder les clés cohérentes
                record.request_id = getattr(record, 'request_id', None)
                record.client_ip = getattr(record, 'client_ip', None)
                record.user_agent = getattr(record, 'user_agent', None)
                record.http_method = getattr(record, 'http_method', None)
                record.endpoint = getattr(record, 'endpoint', None)
        except RuntimeError:
            # sécurité : parfois Flask lève si on est en thread hors contexte
            record.request_id = getattr(record, 'request_id', None)
            record.client_ip = getattr(record, 'client_ip', None)
            record.user_agent = getattr(record, 'user_agent', None)
            record.http_method = getattr(record, 'http_method', None)
            record.endpoint = getattr(record, 'endpoint', None)
        return True
 
# -----------------------------
# 3️⃣ Helpers IP / UA (réutilisés)
# -----------------------------
def _safe_get_client_ip():
    """Récupère l'IP réelle du client derrière un proxy (usage interne)"""
    try:
        # priorité aux headers
        ip_headers = [
            'X-Client-IP',
            'X-Real-IP',
            'X-Forwarded-For',
            'CF-Connecting-IP',
            'True-Client-IP',
            'X-Cluster-Client-IP',
            'Forwarded',
            'Forwarded-For',
            'X-Original-Forwarded-For'
        ]
        client_ip = None
        for header in ip_headers:
            if request.headers.get(header):
                ips = request.headers[header].split(',')
                client_ip = ips[0].strip()
                if client_ip:
                    break
 
        if not client_ip:
            client_ip = request.remote_addr
 
        if client_ip:
            # enlever port si present
            if ':' in client_ip and client_ip.count(':') == 1:
                client_ip = client_ip.split(':')[0]
 
            ip_pattern = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
            if ip_pattern.match(client_ip):
                return client_ip
    except Exception:
        pass
    return 'unknown-ip'
 
def get_client_ip():
    """Exposé : Récupère l'IP réelle du client derrière un proxy"""
    from flask import has_request_context
    if not has_request_context():
        return 'no-context'
    return _safe_get_client_ip()
 
def get_user_agent():
    """Récupère le User-Agent"""
    from flask import has_request_context
    if not has_request_context():
        return 'Unknown'
    return request.headers.get('User-Agent', 'Unknown')
 
# -----------------------------
# 4️⃣ Configuration du logger principal + root
# -----------------------------
# Logger dédié
logger = logging.getLogger('candidatures_api')
logger.setLevel(logging.INFO)
logger.propagate = False  # évite duplication si on attache aussi au root
 
# Handlers
json_handler = TimedRotatingFileHandler(
    filename=os.path.join(log_dir, "app.json.log"),
    when="midnight", interval=1, backupCount=30, encoding="utf-8", utc=True
)
json_handler.setFormatter(JsonFormatter())
json_handler.setLevel(logging.INFO)
 
text_handler = TimedRotatingFileHandler(
    filename=os.path.join(log_dir, "app.log"),
    when="midnight", interval=1, backupCount=14, encoding="utf-8", utc=True
)
text_handler.setFormatter(DetailedFormatter())
text_handler.setLevel(logging.INFO)
 
error_handler = TimedRotatingFileHandler(
    filename=os.path.join(log_dir, "error.log"),
    when="midnight", interval=1, backupCount=90, encoding="utf-8", utc=True
)
error_handler.setFormatter(DetailedFormatter())
error_handler.setLevel(logging.ERROR)
 
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter())
console_handler.setLevel(logging.INFO)
 
# Ajouter RequestContextFilter à chaque handler pour injecter IP / req_id / method
req_filter = RequestContextFilter()
json_handler.addFilter(req_filter)
text_handler.addFilter(req_filter)
error_handler.addFilter(req_filter)
console_handler.addFilter(req_filter)
 
# Ajouter handlers au logger 'candidatures_api'
logger.addHandler(json_handler)
logger.addHandler(text_handler)
logger.addHandler(error_handler)
logger.addHandler(console_handler)
 
# --- Et on attache AUSSI les mêmes handlers au logger root pour capter logging.info(...) partout ---
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
 
# Éviter duplication des handlers si déjà attachés (re-run safe)
existing_handler_types = {type(h) for h in root_logger.handlers}
for h in (json_handler, text_handler, error_handler, console_handler):
    if type(h) not in existing_handler_types:
        root_logger.addHandler(h)
 
# Ajouter le filter aussi sur le root
root_logger.addFilter(req_filter)
 
# Configurer le logger werkzeug (Flask) pour un niveau moins verbeux et sortie vers nos handlers
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)
# make sure werkzeug logs propagate to root handlers but avoid double attach
if not any(isinstance(h, TimedRotatingFileHandler) for h in werkzeug_logger.handlers):
    werkzeug_logger.addHandler(text_handler)
    werkzeug_logger.addHandler(json_handler)
    werkzeug_logger.propagate = True
 
# -----------------------------
# 5️⃣ Fonctions utilitaires pour logging
# -----------------------------
def log_with_context(message, level=logging.INFO, **extra):
    """Fonction helper pour logger avec contexte (préserve les champs personnalisés)"""
    extra_data = {}
 
    mapping = {
        'module': 'source_module',
        'action': 'log_action',
        'method': 'http_method'
    }
 
    for key, value in extra.items():
        if key in mapping:
            extra_data[mapping[key]] = value
        else:
            extra_data[key] = value
 
    # ajouter le contexte Flask si présent (non bloquant)
    try:
        if has_request_context():
            if hasattr(g, 'request_id'):
                extra_data['request_id'] = g.request_id
            if hasattr(g, 'client_ip'):
                extra_data['client_ip'] = g.client_ip
            # on peut aussi ajouter user_agent
            extra_data.setdefault('user_agent', get_user_agent())
    except RuntimeError:
        pass
 
    # logger principal (utilise le logger dédié)
    logger.log(level, message, extra=extra_data)
 
def simple_log(message, level=logging.INFO, **extra):
    """Log simple sans vérification de contexte Flask"""
    extra_data = {}
    mapping = {
        'module': 'source_module',
        'action': 'log_action',
        'method': 'http_method'
    }
    for key, value in extra.items():
        if key in mapping:
            extra_data[mapping[key]] = value
        else:
            extra_data[key] = value
 
    logger.log(level, message, extra=extra_data)
 
# -----------------------------
# 6️⃣ Middlewares and request/response logging
# -----------------------------
def log_request():
    """Loggue une requête entrante"""
    client_ip = get_client_ip()
    user_agent = get_user_agent()
    request_id = str(uuid.uuid4())
 
    # Stocker dans le contexte Flask
    g.request_id = request_id
    g.client_ip = client_ip
    g.start_time = time.time()
 
    # Log principal
    log_with_context(
        f"Requête entrante: {request.method} {request.path}",
        level=logging.INFO,
        source_module='request',
        log_action='incoming',
        http_method=request.method,
        endpoint=request.path,
        user_agent=user_agent,
        query_params=dict(request.args) if request.args else None
    )
 
    # Log plus détaillé pour méthodes avec body
    if request.method in ['POST', 'PUT', 'PATCH']:
        content_type = request.headers.get('Content-Type', '')
        content_length = request.headers.get('Content-Length', 0)
        log_with_context(
            f"Body details - Type: {content_type}, Length: {content_length}",
            level=logging.DEBUG,
            source_module='request',
            log_action='body_details',
            content_type=content_type,
            content_length=content_length
        )
 
def log_response(response):
    """Loggue une réponse"""
    request_id = getattr(g, 'request_id', 'no-id')
    client_ip = getattr(g, 'client_ip', '0.0.0.0')
    start_time = getattr(g, 'start_time', time.time())
 
    response_time = (time.time() - start_time) * 1000  # ms
    status_code = response.status_code
 
    # response size (fallback safe)
    try:
        response_size = int(response.headers.get('Content-Length') or len(response.get_data() or b''))
    except Exception:
        response_size = 0
 
    # choose level
    if status_code >= 500:
        log_level = logging.ERROR
        msg = f"Erreur serveur {status_code}"
    elif status_code >= 400:
        log_level = logging.WARNING
        msg = f"Erreur client {status_code}"
    else:
        log_level = logging.INFO
        msg = f"Réponse {status_code}"
 
    log_with_context(
        f"{msg}: {request.method} {request.path}",
        level=log_level,
        source_module='response',
        log_action='completed',
        status_code=status_code,
        response_time=round(response_time, 2),
        http_method=request.method,
        endpoint=request.path,
        response_size=response_size
    )
 
    # ajouter headers utiles
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Response-Time'] = f'{response_time:.2f}ms'
 
    return response
 
def log_exception(error):
    """Loggue une exception hors ou dans le contexte Flask"""
    from flask import has_request_context
    if not has_request_context():
        simple_log(
            f"Exception hors contexte: {str(error)}",
            level=logging.ERROR,
            source_module='exception',
            log_action='out_of_context',
            exception_type=type(error).__name__,
            exception_message=str(error)
        )
        return
 
    request_id = getattr(g, 'request_id', 'no-id')
    client_ip = getattr(g, 'client_ip', '0.0.0.0')
 
    log_with_context(
        f"Exception non gérée: {str(error)}",
        level=logging.ERROR,
        source_module='exception',
        log_action='unhandled',
        exception_type=type(error).__name__,
        exception_message=str(error),
        http_method=request.method,
        endpoint=request.path
    )
 
# -----------------------------
# 7️⃣ Chargement des variables d'environnement
# -----------------------------
print("🔧 Chargement des variables d'environnement...")
load_dotenv()
 
# -----------------------------
# 8️⃣ Création de l'application Flask
# -----------------------------
print("🚀 Création de l'application Flask...")
app = create_app()
app.config.from_object(Config)
 
# -----------------------------
# 9️⃣ Initialisation Elastic APM (optionnelle)
# -----------------------------
print("📊 Vérification Elastic APM...")
apm = None
apm_config = {
    'server_url': os.getenv('ELASTIC_APM_SERVER_URL'),
    'service_name': os.getenv('ELASTIC_APM_SERVICE_NAME'),
    'secret_token': os.getenv('ELASTIC_APM_SECRET_TOKEN'),
    'api_key': os.getenv('ELASTIC_APM_API_KEY')
}
 
if all([apm_config['server_url'], apm_config['service_name']]) and \
   (apm_config['secret_token'] or apm_config['api_key']):
    try:
        apm = ElasticAPM(app)
        print(f"✅ Elastic APM initialisé: {apm_config['service_name']}")
        simple_log(
            "Elastic APM initialisé avec succès",
            source_module='bootstrap',
            log_action='apm_success',
            service_name=apm_config['service_name']
        )
    except Exception as e:
        print(f"❌ Erreur Elastic APM: {e}")
        simple_log(
            f"Erreur d'initialisation Elastic APM: {e}",
            level=logging.ERROR,
            source_module='bootstrap',
            log_action='apm_error',
            error=str(e)
        )
else:
    print("⚠️  Elastic APM non configuré")
    simple_log(
        "Elastic APM non configuré - monitoring désactivé",
        level=logging.WARNING,
        source_module='bootstrap',
        log_action='apm_disabled'
    )
 
# -----------------------------
# 10️⃣ Configuration CORS
# -----------------------------
print("🌐 Configuration CORS...")
CORS(
    app,
    resources={r"/api/*": {"origins": [
        "https://orangedigitalcenter.sn",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Response-Time"]
)
 
# -----------------------------
# 11️⃣ Middleware de logging
# -----------------------------
@app.before_request
def before_request():
    """Middleware avant chaque requête"""
    # Ignorer health et favicon
    if request.path in ('/health', '/favicon.ico'):
        return
    log_request()
 
@app.after_request
def after_request(response):
    """Middleware après chaque requête"""
    if request.path in ('/health', '/favicon.ico'):
        return response
    return log_response(response)
 
@app.teardown_request
def teardown_request(error=None):
    """Middleware en cas d'erreur"""
    if error:
        log_exception(error)
 
@app.errorhandler(404)
def not_found_error(error):
    """Handler pour les 404"""
    client_ip = get_client_ip()
    log_with_context(
        f"Route non trouvée: {request.path}",
        level=logging.WARNING,
        source_module='error',
        log_action='not_found',
        http_method=request.method,
        endpoint=request.path,
        status_code=404,
        error_message=str(error)
    )
    return {"error": "Not Found", "path": request.path}, 404
 
@app.errorhandler(500)
def internal_error(error):
    """Handler pour les erreurs internes"""
    log_exception(error)
    return {"error": "Internal Server Error"}, 500
 
# -----------------------------
# 12️⃣ Endpoints de monitoring
# -----------------------------
@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de santé"""
    return {
        "status": "healthy",
        "timestamp": now_iso_z(),
        "service": "candidatures-api",
        "version": "1.0.0",
        "hostname": socket.gethostname(),
        "environment": os.getenv('FLASK_ENV', 'production'),
        "apm_enabled": apm is not None,
        "log_level": logger.level,
        "python_version": os.sys.version
    }
 
@app.route('/logs/info', methods=['GET'])
def logs_info():
    """Endpoint d'information sur les logs"""
    if os.environ.get('FLASK_ENV') == 'production':
        return {"error": "Not available in production"}, 403
 
    log_files = []
    for file in os.listdir(log_dir):
        file_path = os.path.join(log_dir, file)
        if os.path.isfile(file_path):
            stat = os.stat(file_path)
            log_files.append({
                'name': file,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'path': file_path
            })
 
    return {
        "log_directory": os.path.abspath(log_dir),
        "files": sorted(log_files, key=lambda x: x['name']),
        "total_size": sum(f['size'] for f in log_files),
        "total_files": len(log_files)
    }

# Crée un handler pour écrire dans un fichier avec rotation
file_handler = RotatingFileHandler("verify_access.log", maxBytes=5*1024*1024, backupCount=3)
file_handler.setLevel(logging.DEBUG)  # tout est loggué
 
# Format des logs : date, niveau, email, message
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
file_handler.setFormatter(formatter)
 
# Logger principal pour verify-access
logger = logging.getLogger("verify-access")
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# -----------------------------
# 13️⃣ Lancement du serveur
# -----------------------------

if __name__ == '__main__':
    from waitress import serve
 
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
 
    print("\n" + "=" * 60)
    print("🚀 LANCEMENT SERVEUR CANDIDATURES")
    print("=" * 60)
    print(f"📊 Host: {host}:{port}")
    print(f"⚙️  Environnement: {os.getenv('FLASK_ENV', 'production')}")
    print(f"🔧 Threads: 150 | Timeout: 120s")
    print(f"📁 Logs: {os.path.abspath(log_dir)}")
    print(f"🎯 Cible: 42k candidats avec pics de 10k soumissions")
    print("=" * 60 + "\n")
 
    simple_log(
        "Démarrage du serveur...",
        source_module='server',
        log_action='startup',
        host=host,
        port=port,
        pid=os.getpid(),
        environment=os.getenv('FLASK_ENV', 'production')
    )
 
    try:
        print(f"✅ Serveur démarré sur http://{host}:{port}")
        print("📝 Logs activés - Appuyez sur Ctrl+C pour arrêter\n")
 
        serve(
            app,
            host=host,
            port=port,
            threads=150,
            channel_timeout=120,
            cleanup_interval=30,
            asyncore_use_poll=True,
            ident=f"candidatures-api-{os.getpid()}-{socket.gethostname()}",
            max_request_body_size=100 * 1024 * 1024,
            connection_limit=1000,
        )
 
    except KeyboardInterrupt:
        simple_log(
            "Arrêt manuel du serveur",
            source_module='server',
            log_action='shutdown',
            reason='keyboard_interrupt'
        )
        print("\n Serveur arrêté proprement")
    except Exception as e:
        simple_log(
            f"Crash du serveur: {e}",
            level=logging.ERROR,
            source_module='server',
            log_action='crash',
            error=str(e),
            hostname=socket.gethostname()
        )
        print(f"\n Crash du serveur: {e}")
        traceback.print_exc()
        raise
    finally:
        simple_log(
            "Serveur arrêté",
            source_module='server',
            log_action='shutdown',
            pid=os.getpid()
        )
 
 