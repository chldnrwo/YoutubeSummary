import sqlite3
import os

DB_PATH = 'insights.db'

def migrate_db_for_groups():
    if not os.path.exists(DB_PATH):
        print("DB가 존재하지 않습니다.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("1. stock_groups 테이블 생성 중...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            name TEXT NOT NULL,
            group_type TEXT NOT NULL,  -- 'DAILY' or 'CONSENSUS'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    print("2. stocks 테이블에 group_id 컬럼 추가 중...")
    try:
        cursor.execute("ALTER TABLE stocks ADD COLUMN group_id INTEGER REFERENCES stock_groups(id)")
        print("group_id 컬럼 추가 완료.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("group_id 컬럼이 이미 존재합니다.")
        else:
            print(f"컬럼 추가 실패 (무시됨): {e}")

    conn.commit()
    conn.close()
    print("그룹 기능 마이그레이션이 완료되었습니다!")

if __name__ == '__main__':
    migrate_db_for_groups()
