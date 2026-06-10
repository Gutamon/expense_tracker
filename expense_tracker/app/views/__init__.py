import os
from flask import Flask
from app.models import csv_store

def create_app():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    app = Flask(
        __name__,
        template_folder=os.path.join(current_dir, "templates"),
        static_folder=os.path.join(current_dir, "static"),
        static_url_path="/static"
    )

    from config import Config
    app.config.from_object(Config)

    csv_store.set_data_dir(app.config["DATA_DIR"])
    csv_store.init_data_dir()

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    from app.controllers.main_routes import main_bp
    from app.controllers.category_routes import settings_bp
    from app.controllers.stock_routes import stock_bp
    from app.controllers.debt_routes import debt_bp
    from app.controllers.onboarding_routes import onboarding_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(debt_bp)
    app.register_blueprint(onboarding_bp)

    return app
