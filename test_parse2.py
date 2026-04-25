import sqlite3

conn = sqlite3.connect('insights.db')
cur = conn.cursor()
cur.execute("SELECT id, analysis_result FROM insights ORDER BY id DESC LIMIT 5")
rows = cur.fetchall()

for row in rows:
    print(f"--- ID {row[0]} ---")
    raw = row[1].strip()
    print("Starts with '{':", raw.startswith('{'))
    print("First 20 chars:", repr(raw[:20]))
