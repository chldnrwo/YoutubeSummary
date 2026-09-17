import sqlite3
import os

DB_PATH = 'insights.db'

def migrate_sessions():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return
        
    print("RAG 멀티 세션 마이그레이션 시작...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. rag_sessions 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL DEFAULT '새 대화',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("rag_sessions 테이블 생성 완료 (또는 이미 존재).")
        
        # 2. rag_chat_history 테이블에 session_id 컬럼 추가
        # 컬럼이 존재하는지 먼저 확인
        cursor.execute("PRAGMA table_info(rag_chat_history)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'session_id' not in columns:
            cursor.execute("ALTER TABLE rag_chat_history ADD COLUMN session_id INTEGER REFERENCES rag_sessions(id)")
            print("rag_chat_history 테이블에 session_id 컬럼 추가 완료.")
        else:
            print("session_id 컬럼이 이미 존재합니다.")
            
        # 3. 기존 대화 기록을 '이전 대화' 세션으로 묶어주기 (선택사항)
        # user별로 기존 대화가 있으면, 각각에 대해 '이전 대화 (마이그레이션)' 세션을 하나 만들고 할당한다.
        cursor.execute("SELECT DISTINCT user_id FROM rag_chat_history WHERE session_id IS NULL")
        users_with_null_sessions = cursor.fetchall()
        
        for (user_id,) in users_with_null_sessions:
            # 새 세션 생성
            cursor.execute("""
                INSERT INTO rag_sessions (user_id, title)
                VALUES (?, ?)
            """, (user_id, "이전 대화 (마이그레이션)"))
            new_session_id = cursor.lastrowid
            
            # 기존 대화를 이 세션에 할당
            cursor.execute("""
                UPDATE rag_chat_history 
                SET session_id = ? 
                WHERE user_id = ? AND session_id IS NULL
            """, (new_session_id, user_id))
            print(f"사용자 {user_id}의 기존 대화를 세션 {new_session_id}로 마이그레이션 완료.")
            
        conn.commit()
        print("마이그레이션 성공!")
    except Exception as e:
        conn.rollback()
        print(f"마이그레이션 실패: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_sessions()
