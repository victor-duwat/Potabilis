"""
api/app.py — Factory Flask Waterflow 2
"""

import os
import logging
from flask import Flask
from flasgger import Swagger
from api.models.db     import init_db
from api.routes.routes import bp

_ROOT = os.path.dirname(os.path.abspath(__file__))

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

    # Initialise les tables si elles n'existent pas
    init_db()

    app.register_blueprint(bp)

    # Documentation Swagger — accessible sur /apidocs
    swagger_path = os.path.join(_ROOT, "swagger.yaml")
    Swagger(app, config=SWAGGER_CONFIG, template_file=swagger_path)

    return app
