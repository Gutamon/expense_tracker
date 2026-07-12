import os
from flask import Flask, g, request
from app.models import csv_store, user

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

    root_dir = app.config["DATA_DIR"]
    csv_store.set_data_dir(root_dir)
    csv_store.init_data_dir()

    @app.before_request
    def bind_device():
        # Static assets don't touch per-device data. The rescue-code restore endpoint
        # resolves its own device_id from the code and sets the cookie itself — it
        # must not have a throwaway device auto-created for it here first.
        if request.endpoint in ("static", "onboarding.restore_device"):
            return
        device_id = user.resolve_device_id(request)
        new_device = device_id is None
        if new_device:
            device_id = user.adopt_or_create(root_dir)
            g.new_device = device_id
        g.device_id = device_id
        g.data_dir = user.user_data_dir(root_dir, device_id)
        # Seed + migrate the folder for new devices (and re-seed if it went missing).
        if new_device or not os.path.isdir(g.data_dir):
            csv_store.init_current_user()

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        new_device = g.get("new_device")
        if new_device:
            user.set_device_cookie(response, new_device)
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
