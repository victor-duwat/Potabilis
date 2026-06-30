"""
api/app.py — Factory Flask Waterflow 2
"""

import os
import secrets
import hashlib
import logging
import click
from dotenv import load_dotenv
from flask import Flask, jsonify

# Charge .env dès que le module est importé, quel que soit le point d'entrée
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
from flasgger import Swagger
from prometheus_flask_exporter import PrometheusMetrics
from api.models.db     import init_db, purge_old_logs
from api.routes.routes import bp
from extensions        import limiter

_ROOT = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger(__name__)

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs",
}


def _start_scheduler(app: Flask) -> None:
    """
    Lance APScheduler en arrière-plan pour la purge RGPD nocturne.
    Le check WERKZEUG_RUN_MAIN évite le double démarrage en mode debug
    (le reloader Flask crée deux processus — on ne démarre le scheduler
    que dans le processus enfant qui fait vraiment tourner le serveur).
    """
    in_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    in_production     = os.environ.get("FLASK_ENV", "production") != "development"

    if not (in_reloader_child or in_production):
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    def _job():
        with app.app_context():
            result = purge_old_logs()
            logger.info("Purge planifiée exécutée : %s", result)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _job,
        trigger="cron",
        hour=2,
        minute=0,
        id="purge_rgpd",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler RGPD actif — purge quotidienne à 02h00")


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_ROOT, "templates"),
        static_folder=os.path.join(_ROOT, "static"),
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    # ── Prometheus métriques (/metrics) ─────────────────────────────────────
    PrometheusMetrics(app, group_by="endpoint")

    # ── Rate limiting ────────────────────────────────────────────────────────
    # Initialise le limiter avec l'app Flask.
    # Les limites par route sont déclarées dans routes.py via @limiter.limit().
    # Désactivable via RATELIMIT_ENABLED=false (utilisé par la suite de tests,
    # où l'on enchaîne volontairement de nombreuses requêtes).
    app.config["RATELIMIT_ENABLED"] = (
        os.getenv("RATELIMIT_ENABLED", "true").lower() not in ("false", "0", "no")
    )
    limiter.init_app(app)

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        return jsonify({
            "error": "Trop de requêtes. Réessayez dans quelques instants.",
            "retry_after": str(e.description),
        }), 429

    # ── Base de données ──────────────────────────────────────────────────────
    init_db()

    # ── Routes ──────────────────────────────────────────────────────────────
    app.register_blueprint(bp)

    # ── Swagger ─────────────────────────────────────────────────────────────
    swagger_path = os.path.join(_ROOT, "swagger.yaml")
    Swagger(app, config=SWAGGER_CONFIG, template_file=swagger_path)

    # ── Purge RGPD automatique ───────────────────────────────────────────────
    _start_scheduler(app)

    # ── Commande CLI : flask purge-logs ──────────────────────────────────────
    @app.cli.command("purge-logs")
    def purge_logs_cmd():
        """Purge manuelle : audit_logs > 12 mois, request_metrics > 90 jours."""
        result = purge_old_logs()
        print(f"Purge terminée : {result}")

    # ── Commande CLI : flask new-expert-token ────────────────────────────────
    @app.cli.command("new-expert-token")
    @click.argument("login")
    @click.argument("role", type=click.Choice(["analyste", "exploit"]))
    def new_expert_token_cmd(login: str, role: str):
        """Génère un token expert et affiche la ligne à ajouter dans .env.

        Usage : flask new-expert-token <login> <role>
        Rôles : analyste | exploit
        """
        raw_token  = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        print(f"\nToken brut (à transmettre à {login} par canal sécurisé — affiché UNE SEULE FOIS) :")
        print(f"  {raw_token}\n")
        print("Ligne à ajouter/remplacer dans EXPERT_TOKENS dans .env :")
        print(f"  {login}:{token_hash}:{role}\n")
        print("Le token brut n'est PAS stocké. Conservez-le ou régénérez-en un nouveau.")

    return app
