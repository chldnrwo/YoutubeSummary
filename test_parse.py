import sqlite3
import json
import re

conn = sqlite3.connect('insights.db')
cur = conn.cursor()
cur.execute('SELECT id, analysis_result FROM insights ORDER BY id DESC LIMIT 3')
rows = cur.fetchall()

for row in rows:
    insight_id = row[0]
    raw = row[1]
    
    print(f"\n--- ID {insight_id} ---")
    raw = raw.strip()
    
    # 1. 시뮬레이션: json.loads 
    fixed_raw = raw
    if fixed_raw.endswith('```'):
        fixed_raw = fixed_raw[:-3].strip()
        
    if not fixed_raw.endswith('}'):
        if fixed_raw.count('"') % 2 != 0:
            fixed_raw += '"'
        fixed_raw += '\n}'
    
    try:
        parsed = json.loads(fixed_raw, strict=False)
        print("PARSE OK:", list(parsed.keys()))
    except Exception as e:
        print("PARSE ERROR:", e)
        
    # 2. 시뮬레이션: 정규식
    analysis_match = re.search(r'"analysis"\s*:\s*"(.*)', raw, re.DOTALL)
    if analysis_match:
        display_analysis = analysis_match.group(1)
        display_analysis = re.sub(r'"?\s*\}?\s*$', '', display_analysis)
        display_analysis = display_analysis.replace('\\"', '"')
        print("REGEX SUCCESS, length:", len(display_analysis))
        print("REGEX END:", repr(display_analysis[-50:]))
    else:
        print("REGEX FAILED")
        
conn.close()
