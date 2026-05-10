import os
from flask import Flask
from app.models.db import init_db

def create_app():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    app = Flask(
        __name__,
        template_folder=os.path.join(current_dir, "templates"),
        static_folder=os.path.join(current_dir, "static"),
        static_url_path="/static"
    )

    # 載入設定
    from config import Config
    app.config.from_object(Config)
    
    # 建立資料庫與資料表
    init_db()

    # 強制瀏覽器不快取任何回應
    @app.after_request
    def add_header(response):
        # 設定 HTTP Headers 告訴瀏覽器不要保留歷史紀錄快取
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    from app.controllers.main_routes import main_bp
    from app.controllers.auth_routes import auth_bp
    from app.controllers.category_routes import settings_bp
    from app.controllers.stock_routes import stock_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(stock_bp)

    return app