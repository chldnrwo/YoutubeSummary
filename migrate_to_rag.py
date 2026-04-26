import os
import json
import sqlite3
import chromadb
import google.generativeai as genai
from tqdm import tqdm

DB_PATH = 'insights.db'
CHROMA_DB_PATH = 'chroma_db'
CONFIG_PATH = 'config.json'

def init_chroma():
    """ChromaDB 초기화 및 컬렉션 가져오기"""
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(name="insights_collection")
    return collection

def get_google_api_key():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
        return config.get("GOOGLE_API_KEY", "")

def get_embedding(text, model="models/gemini-embedding-2"):
    """Gemini를 사용해 텍스트 임베딩 생성"""
    if not text:
        return None
        
    try:
        # 긴 텍스트는 임베딩 전에 적절히 자르거나 처리할 수 있지만, 요약본은 대부분 안전합니다.
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="retrieval_document",
        )
        return result['embedding']
    except Exception as e:
        print(f"Embedding error: {e}")
        return None

def migrate_data():
    api_key = get_google_api_key()
    if not api_key:
        print("GOOGLE_API_KEY를 찾을 수 없습니다.")
        return
        
    genai.configure(api_key=api_key)
    
    # 1. 기존 SQLite 연결
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # insights 테이블에서 id, video_id, title, video_url, analysis_result, created_at, user_id, category 가져오기
    try:
        cursor.execute("SELECT id, video_id, title, video_url, analysis_result, created_at, user_id, category FROM insights")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"DB 읽기 에러: {e}")
        conn.close()
        return
        
    conn.close()
    
    if not rows:
        print("이전 데이터가 없습니다.")
        return
        
    # 2. ChromaDB 연결
    collection = init_chroma()
    
    # 3. 마이그레이션 실행
    print(f"총 {len(rows)}개의 데이터를 ChromaDB로 마이그레이션합니다...")
    
    for row in tqdm(rows):
        db_id, video_id, title, video_url, analysis_result, created_at, user_id, category = row
        
        doc_id = f"insight_{db_id}_{video_id}"
        
        # 임베딩 생성 (핵심은 분석 결과!)
        text_to_embed = f"Title: {title}\n\nAnalysis:\n{analysis_result}"
        
        embedding = get_embedding(text_to_embed)
        
        if embedding:
            # ChromaDB에 upsert (기존 데이터가 있으면 덮어쓰기)
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[{
                    "video_id": video_id,
                    "title": title if title else "제목 없음",
                    "video_url": video_url,
                    "created_at": created_at if created_at else "",
                    "user_id": user_id if user_id else -1,
                    "category": category if category else "그 외"
                }],
                documents=[text_to_embed]
            )
            
    print("마이그레이션 완료! 🎉")

if __name__ == "__main__":
    migrate_data()
