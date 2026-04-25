import sqlite3
import re

conn = sqlite3.connect('insights.db')
cursor = conn.cursor()

# title이 '분석 완료'인 최근 데이터 조회
cursor.execute("SELECT id, analysis_result FROM insights WHERE title = '분석 완료' ORDER BY created_at DESC LIMIT 10")
rows = cursor.fetchall()

updated = 0
for row in rows:
    insight_id = row[0]
    analysis = row[1]
    
    # 정규식으로 title 추출 시도
    title_match = re.search(r'"title"\s*:\s*"([^"]+)"', analysis)
    if title_match:
        new_title = title_match.group(1)
        cursor.execute("UPDATE insights SET title = ? WHERE id = ?", (new_title, insight_id))
        updated += 1
        print(f"ID {insight_id}의 제목을 업데이트했습니다: {new_title}")

if updated > 0:
    conn.commit()
    print(f"총 {updated}개의 데이터 복구 완료.")
else:
    print("복구할 데이터가 없습니다.")

conn.close()
