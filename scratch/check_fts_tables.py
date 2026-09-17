import sqlite3

conn = sqlite3.connect('insights.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'")
tables = cursor.fetchall()
print("FTS Tables:", tables)
conn.close()
