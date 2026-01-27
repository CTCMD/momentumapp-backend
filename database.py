import sqlite3

conn = sqlite3.connect("users.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    is_active INTEGER DEFAULT 0
)
""")

conn.commit()
conn.close()
