import sqlite3
import os

dbs = ['database.db', 'insight_pipeline.db', 'insights.db']
for d in dbs:
    if not os.path.exists(d):
        continue
    print(f"\n=== {d} ===")
    conn = sqlite3.connect(d)
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for name, sql in cur.fetchall():
        print(f"Table: {name}")
        print(f"SQL: {sql}\n")
    conn.close()
