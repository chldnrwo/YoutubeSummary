import sqlite3

def fix_schema():
    conn = sqlite3.connect('insights.db')
    cursor = conn.cursor()
    
    # 외래키 검사 임시 해제
    cursor.execute("PRAGMA foreign_keys = OFF")
    
    print("새로운 stocks 테이블 생성 (단일 UNIQUE 제거)...")
    cursor.execute("""
        CREATE TABLE stocks_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT DEFAULT 'KRX',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id),
            stock_type TEXT DEFAULT 'DAILY'
        )
    """)
    
    print("기존 데이터 복사 중...")
    cursor.execute("""
        INSERT INTO stocks_new (id, symbol, name, market, created_at, user_id, stock_type)
        SELECT id, symbol, name, market, created_at, user_id, stock_type
        FROM stocks
    """)
    
    print("기존 테이블 및 인덱스 삭제...")
    cursor.execute("DROP TABLE stocks")
    
    print("테이블 이름 변경 및 신규 인덱스 생성...")
    cursor.execute("ALTER TABLE stocks_new RENAME TO stocks")
    
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_user_symbol_type ON stocks(symbol, user_id, stock_type)
    """)
    
    conn.commit()
    conn.close()
    print("스키마 마이그레이션이 완료되었습니다!")

if __name__ == '__main__':
    fix_schema()
