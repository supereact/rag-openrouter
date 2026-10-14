from app.db import db_connection

with db_connection() as conn:
    result = conn.execute(
        "SELECT current_database(), current_user"
    ).fetchone()

    print("Connected successfully:", result)