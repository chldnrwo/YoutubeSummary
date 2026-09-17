import sqlite3
import os

DB_PATH = 'insights.db'

def migrate_fts():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return
        
    print("FTS5 마이그레이션 시작...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # FTS 테이블 생성 (retrieval.py와 동일)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS insights_fts USING fts5(
            title, analysis_result, transcript,
            content='insights',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
            claim_text,
            content='wiki_claims',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
            name, description,
            content='wiki_entities',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    
    # 1. insights 데이터 삽입
    cursor.execute("""
        INSERT INTO insights_fts(rowid, title, analysis_result, transcript)
        SELECT id, title, analysis_result, transcript FROM insights
    """)
    print(f"insights_fts 에 {cursor.rowcount} 건 삽입 완료.")
    
    # 2. wiki_claims 데이터 삽입
    cursor.execute("""
        INSERT INTO claims_fts(rowid, claim_text)
        SELECT id, claim_text FROM wiki_claims
    """)
    print(f"claims_fts 에 {cursor.rowcount} 건 삽입 완료.")
    
    # 3. wiki_entities 데이터 삽입
    cursor.execute("""
        INSERT INTO entities_fts(rowid, name, description)
        SELECT id, name, description FROM wiki_entities
    """)
    print(f"entities_fts 에 {cursor.rowcount} 건 삽입 완료.")
    
    conn.commit()
    conn.close()
    print("FTS5 마이그레이션 완료!")

if __name__ == "__main__":
    migrate_fts()
