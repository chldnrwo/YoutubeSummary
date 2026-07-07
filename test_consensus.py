"""컨센서스 함수 통합 테스트 - app.py에서 직접 import"""
import sys
sys.path.insert(0, '.')

# app.py에서 필요한 함수만 import하여 테스트
from app import (
    init_database,
    fetch_consensus_data,
    save_consensus_data,
    get_or_create_stock,
    get_all_consensus_summary,
)

# DB 초기화
init_database()

# 테스트 종목
test_symbols = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
]

print("=" * 60)
print("컨센서스 수집 테스트")
print("=" * 60)

for symbol, name in test_symbols:
    print(f"\n[{name} ({symbol})] 수집 중...")
    result = fetch_consensus_data(symbol)
    
    if result:
        print(f"  종목명: {result['name']}")
        print(f"  레코드 수: {len(result['records'])}")
        
        # DB 저장 테스트
        stock_id = get_or_create_stock(symbol, result['name'])
        saved = save_consensus_data(stock_id, result['records'])
        print(f"  DB 저장: {saved}건")
        
        for r in result['records']:
            est = "(E)" if r['is_estimate'] else "(A)"
            val = r['value']
            if abs(val) >= 10000:
                fmt = f"{val/10000:,.1f}조"
            else:
                fmt = f"{val:,.0f}억"
            print(f"  {r['year']}년{est}: {fmt}")
    else:
        print(f"  수집 실패!")

import time
time.sleep(1)

print("\n" + "=" * 60)
print("전체 요약 조회 테스트 (user_id=None)")
print("=" * 60)

# user_id 없이 조회하는 대신 직접 쿼리
import sqlite3
from pathlib import Path
DB_PATH = Path(__file__).parent / "insights.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("""
    SELECT s.symbol, s.name, cd.year, cd.value, cd.is_estimate, cd.updated_at
    FROM consensus_data cd
    JOIN stocks s ON cd.stock_id = s.id
    ORDER BY s.name, cd.year
""")
rows = cursor.fetchall()
conn.close()

for row in rows:
    est = "(E)" if row['is_estimate'] else "(A)"
    val = row['value']
    if abs(val) >= 10000:
        fmt = f"{val/10000:,.1f}조"
    else:
        fmt = f"{val:,.0f}억"
    print(f"  {row['name']}({row['symbol']}) {row['year']}년{est}: {fmt} (갱신: {row['updated_at']})")

print("\n✅ 테스트 완료!")
