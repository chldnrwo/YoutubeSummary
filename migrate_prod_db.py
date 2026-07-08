import sqlite3

DB_PATH = 'insights.db'

def init_database():
    """데이터베이스와 테이블을 초기화합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 사용자 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL UNIQUE,
            name TEXT,
            profile_image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            video_url TEXT NOT NULL,
            title TEXT,
            transcript TEXT,
            analysis_result TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN title TEXT")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN published_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN category TEXT DEFAULT '그 외'")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_video_id ON insights(video_id)
    """)
    
    # 주식 종목 마스터 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT DEFAULT 'KRX',
            user_id INTEGER REFERENCES users(id),
            stock_type TEXT DEFAULT 'DAILY',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE stocks ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE stocks ADD COLUMN stock_type TEXT DEFAULT 'DAILY'")
    except sqlite3.OperationalError:
        pass
    
    # 기존 인덱스는 남겨두거나 에러 무시, 새로운 인덱스 생성: (symbol, user_id, stock_type)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_user_symbol_type ON stocks(symbol, user_id, stock_type)
    """)
    
    # 일별 시세 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL,
            volume INTEGER,
            market_cap INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id),
            UNIQUE(stock_id, date)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_date ON daily_prices(stock_id, date)
    """)
    
    # OAuth 상태 저장 테이블 (세션 유실 방지용)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE oauth_states ADD COLUMN credentials_json TEXT")
    except sqlite3.OperationalError:
        pass
        
    # 영구 로그인용 세션 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            credentials_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 분석 읽음(확인) 상태 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS read_insights (
            user_id INTEGER NOT NULL,
            insight_id INTEGER NOT NULL,
            read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, insight_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (insight_id) REFERENCES insights(id) ON DELETE CASCADE
        )
    """)

    # RAG 챗봇 대화 기록 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rag_chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rag_chat_user ON rag_chat_history(user_id)
    """)
    
    # 컨센서스 데이터 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consensus_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            year TEXT NOT NULL,
            item_name TEXT NOT NULL,
            value REAL,
            is_estimate INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id),
            UNIQUE(stock_id, year, item_name)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_consensus_stock ON consensus_data(stock_id)
    """)
    
    conn.commit()
    conn.close()
    print("Database schema successfully migrated!")

if __name__ == "__main__":
    init_database()
