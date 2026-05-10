from werkzeug.security import generate_password_hash, check_password_hash
from app.models.db import get_db
from app.models.category import CategoryModel

class UserModel:
    def create_user(self, username, password):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return None

            hashed = generate_password_hash(password)
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
            user_id = cursor.lastrowid

        # create_defaults runs after the connection closes to avoid a nested lock
        CategoryModel().create_defaults(user_id)
        return user_id

    def authenticate(self, username, password):
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                return dict(user)
            return None