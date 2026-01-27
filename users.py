import sqlite3

DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Crear tabla users si no existe
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """)
    
    # Insertar usuario de prueba si no existe
    c.execute("SELECT * FROM users WHERE email = ?", ("test@example.com",))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            ("Test User", "test@example.com", "1234")
        )

    conn.commit()
    conn.close()


def get_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM users")
    users = [{"id": row[0], "name": row[1], "email": row[2]} for row in c.fetchall()]
    conn.close()
    return users
