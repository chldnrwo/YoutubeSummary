"""30건 테스트용 인사이트 선정 스크립트 - 다양한 유형이 섞이도록"""
import sqlite3

conn = sqlite3.connect('insights.db')

# 사용자 ID 확인
user = conn.execute("SELECT id, name FROM users LIMIT 1").fetchone()
print(f"User: id={user[0]}, name={user[1]}")

# 채널별 분포
channels = conn.execute("""
    SELECT channel_title, COUNT(*) as cnt, category
    FROM insights
    WHERE user_id = ? AND channel_title IS NOT NULL
    GROUP BY channel_title
    ORDER BY cnt DESC
""", (user[0],)).fetchall()

print(f"\n채널 {len(channels)}개:")
for ch in channels:
    print(f"  {ch[0]}: {ch[1]}건 ({ch[2]})")

# 다양한 유형 선정
print("\n== 30건 테스트 후보 ==")

# 1. 상위 5개 채널에서 각 3건 (최근)
print("\n[채널 다양성 - 상위 5개 채널에서 각 2건]")
for ch_name, _, _ in channels[:5]:
    rows = conn.execute("""
        SELECT id, title, channel_title, category, length(analysis_result) as len
        FROM insights
        WHERE user_id = ? AND channel_title = ?
        ORDER BY created_at DESC LIMIT 2
    """, (user[0], ch_name)).fetchall()
    for r in rows:
        print(f"  id={r[0]} | {r[2]} | {r[3]} | {r[1][:40]}... | {r[4]}자")

# 2. IT 카테고리 5건
print("\n[IT 카테고리]")
rows = conn.execute("""
    SELECT id, title, channel_title, length(analysis_result) as len
    FROM insights
    WHERE user_id = ? AND category = 'IT'
    ORDER BY RANDOM() LIMIT 5
""", (user[0],)).fetchall()
for r in rows:
    print(f"  id={r[0]} | {r[2]} | {r[1][:40]}... | {r[3]}자")

# 3. 짧은 분석 5건 (3000자 이하)
print("\n[짧은 분석]")
rows = conn.execute("""
    SELECT id, title, channel_title, category, length(analysis_result) as len
    FROM insights
    WHERE user_id = ? AND length(analysis_result) < 3000
    ORDER BY RANDOM() LIMIT 5
""", (user[0],)).fetchall()
for r in rows:
    print(f"  id={r[0]} | {r[2]} | {r[3]} | {r[1][:40]}... | {r[4]}자")

# 4. 긴 분석 5건 (10000자 이상)
print("\n[긴 분석]")
rows = conn.execute("""
    SELECT id, title, channel_title, category, length(analysis_result) as len
    FROM insights
    WHERE user_id = ? AND length(analysis_result) > 10000
    ORDER BY RANDOM() LIMIT 5
""", (user[0],)).fetchall()
for r in rows:
    print(f"  id={r[0]} | {r[2]} | {r[3]} | {r[1][:40]}... | {r[4]}자")

conn.close()
