"""
search_quality_log.py - 검색 품질 측정 및 개선을 위한 로그 모듈입니다.
app.py를 import하지 않습니다 (순환 참조 방지).
"""

import sqlite3
import json

def init_log_table(db_path: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_quality_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT NOT NULL,
            query_type TEXT,
            search_strategies TEXT,
            search_queries TEXT,
            retrieved_docs TEXT,
            reranked_docs TEXT,
            retrieval_steps INTEGER,
            final_sources TEXT,
            final_answer TEXT,
            confidence TEXT,
            processing_time_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def log_search(db_path: str, log_data: dict):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO search_quality_logs (
                user_id, query, query_type, search_strategies, search_queries,
                retrieved_docs, reranked_docs, retrieval_steps, final_sources,
                final_answer, confidence, processing_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_data.get('user_id'),
            log_data.get('query', ''),
            log_data.get('query_type'),
            json.dumps(log_data.get('search_strategies', []), ensure_ascii=False),
            json.dumps(log_data.get('search_queries', []), ensure_ascii=False),
            json.dumps(log_data.get('retrieved_docs', []), ensure_ascii=False),
            json.dumps(log_data.get('reranked_docs', []), ensure_ascii=False),
            log_data.get('retrieval_steps', 1),
            json.dumps(log_data.get('final_sources', []), ensure_ascii=False),
            log_data.get('final_answer', ''),
            log_data.get('confidence', 'unknown'),
            log_data.get('processing_time_ms', 0)
        ))
        conn.commit()
    except Exception as e:
        print(f"[LOG ERROR] 검색 로그 저장 실패: {e}")
    finally:
        conn.close()
