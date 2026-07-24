import os
import threading
from flask import Flask, g, request
from app.models import csv_store, user

# Serializes first-touch seeding of a device folder. The shell loads five tabs as
# concurrent same-origin iframes; on a device whose folder is missing (freshly
# created, or wiped/lost) all five requests would race in init_current_user() and one
# could read accounts.csv mid-write, 500-ing with FileNotFoundError. One lock keyed
# per data_dir lets the first request seed while the rest wait, then find it ready.
_seed_lock = threading.Lock()


def start_rate_scheduler(app):
    """Daily 00:00 job that refreshes FX rates into every device's settings.csv.

    Call this from run.py, not create_app(): under the Werkzeug debug reloader,
    create_app() runs once in the parent "watcher" process (just to build the app
    for reload-inspection) and again in the child worker that actually serves
    requests — starting the scheduler there would double-fire the job. run.py's
    __main__ guard plus Werkzeug's own reloader-child guard (WERKZEUG_RUN_MAIN) give
    us a single, correct call site regardless of debug/reloader settings.
    """
    if app.config.get("TESTING"):
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.models import rates

    def _job():
        with app.app_context():
            rates.refresh_all_devices()

    scheduler = BackgroundScheduler(timezone="Asia/Taipei", daemon=True)
    scheduler.add_job(_job, "cron", hour=0, minute=0, id="daily_fx_refresh")
    scheduler.start()


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

    @app.template_filter("money")
    def money_filter(value, decimals=0):
        return "{:,.{}f}".format(float(value or 0), decimals)

    root_dir = app.config["DATA_DIR"]
    csv_store.set_data_dir(root_dir)
    csv_store.init_data_dir()

    @app.before_request
    def bind_device():
        # Static assets don't touch per-device data. The sync-code join endpoints
        # resolve their own device_id from the code and set the cookie themselves —
        # they must not have a throwaway device auto-created for them here first.
        if request.endpoint in ("static", "onboarding.join_by_code",
                                "onboarding.join_by_code_nav"):
            return
        device_id = user.resolve_device_id(request)
        new_device = device_id is None
        if new_device:
            device_id = user.adopt_or_create(root_dir)
            g.new_device = device_id
        g.device_id = device_id
        # A synced device's data lives in its sync group's shared folder, not its
        # own device_id folder — see user.effective_data_id.
        g.data_dir = user.resolve_data_dir(root_dir, device_id)
        # Seed + migrate the folder for new devices (and re-seed if it went missing).
        # Serialized so concurrent iframe requests don't race in init_current_user()
        # and read a half-written accounts.csv (see _seed_lock).
        if new_device or not os.path.isdir(g.data_dir):
            with _seed_lock:
                # Re-check under the lock: another request may have just seeded it.
                if new_device or not os.path.isdir(g.data_dir):
                    csv_store.init_current_user()
        else:
            # Existing devices: run one-time backfill of expenses/history.category_id.
            # Guarded by a settings flag so it costs one cheap check per request, not
            # a full CSV rewrite. New devices are already migrated by init_current_user.
            csv_store.ensure_category_id_migrated()

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
