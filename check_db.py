import sqlite3
import json

conn = sqlite3.connect('insights.db')
cursor = conn.cursor()
cursor.execute('SELECT id, title, analysis_result FROM insights ORDER BY created_at DESC LIMIT 3')
rows = cursor.fetchall()

with open('out.txt', 'w', encoding='utf-8') as f:
    for row in rows:
        f.write(f"ID: {row[0]}\n")
        f.write(f"Title: {row[1]}\n")
        f.write(f"Analysis Result:\n{row[2][:500]}\n")  # 앞 500자
        f.write(f"... [중략] ...\n")
        f.write(f"끝부분:\n{row[2][-500:]}\n")  # 끝 500자
        f.write("-" * 50 + "\n")
