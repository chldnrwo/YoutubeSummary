"""
retrieval.py - 지식 검색 시스템 확장 모듈
키워드 검색(FTS5), 벡터 검색(ChromaDB), 메타데이터 필터링, Hybrid Search, Reranking을 제공합니다.
app.py를 import하지 않습니다.
"""
import sqlite3
import json
import chromadb
import google.generativeai as genai
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

@dataclass
class SearchResult:
    insight_id: int
    title: str
    content_snippet: str
    score: float
    search_method: str
    source_type: str
    metadata: dict
    has_raw_source: bool

def init_retrieval_tables(db_path: str):
    """FTS5 가상 테이블을 생성합니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 전문 검색 인덱스
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
    conn.commit()
    conn.close()

def search_keyword(db_path: str, query: str, user_id: int, limit: int = 20) -> list[SearchResult]:
    """FTS5를 사용한 키워드 검색을 수행합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # SQLite FTS5 MATCH 쿼리는 query에 큰따옴표를 씌우는 것이 안전 (에러 방지)
    safe_query = f'"{query.replace('"', "")}"'
    
    results = []
    
    # 1. insights 검색
    try:
        insights_rows = cursor.execute(f"""
            SELECT i.id, i.title, snippet(insights_fts, 1, '<b>', '</b>', '...', 32) as snippet,
                   bm25(insights_fts) as score, i.video_url, i.category, i.published_at, i.transcript
            FROM insights_fts f
            JOIN insights i ON f.rowid = i.id
            WHERE insights_fts MATCH ? AND i.user_id = ?
            ORDER BY score
            LIMIT ?
        """, (safe_query, user_id, limit)).fetchall()
        
        for r in insights_rows:
            # bm25 점수는 음수일수록 좋음
            score = -float(r['score']) 
            has_raw = bool(r['transcript'])
            meta = {
                'video_url': r['video_url'],
                'category': r['category'],
                'published_at': r['published_at']
            }
            results.append(SearchResult(r['id'], r['title'] or '제목 없음', r['snippet'], score, 'keyword', 'insight', meta, has_raw))
    except Exception as e:
        print(f"[SEARCH ERROR] insights_fts 검색 실패: {e}")
        
    conn.close()
    
    # 점수순 정렬
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]

def search_vector(db_path: str, chroma_path: str, query: str, user_id: int, api_key: str, limit: int = 20) -> list[SearchResult]:
    """ChromaDB를 이용한 벡터 검색을 수행합니다."""
    genai.configure(api_key=api_key)
    
    try:
        query_embed = genai.embed_content(
            model="models/gemini-embedding-2",
            content=query,
            task_type="retrieval_query"
        )
        embedding = query_embed['embedding']
        
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        collection = chroma_client.get_or_create_collection(name="insights_collection")
        
        where = {"user_id": user_id} if user_id else {}
        
        res = collection.query(
            query_embeddings=[embedding],
            n_results=limit,
            where=where
        )
        
        results = []
        if res and res['documents'] and len(res['documents'][0]) > 0:
            for idx, doc in enumerate(res['documents'][0]):
                meta = res['metadatas'][0][idx]
                distance = res['distances'][0][idx] if 'distances' in res and res['distances'] else 0.0
                score = 1.0 / (1.0 + distance)  # 거리 역산
                
                # insight_id 파싱 (id format: insight_DBID_VIDEOID)
                doc_id = res['ids'][0][idx]
                try:
                    db_id = int(doc_id.split('_')[1])
                except:
                    db_id = -1
                    
                meta_dict = {
                    'video_url': meta.get('video_url'),
                    'category': meta.get('category'),
                    'published_at': meta.get('created_at')
                }
                
                results.append(SearchResult(db_id, meta.get('title', '제목 없음'), doc[:200] + "...", score, 'vector', 'insight', meta_dict, True))
        return results
    except Exception as e:
        print(f"[SEARCH ERROR] Vector 검색 실패: {e}")
        return []

def hybrid_search(db_path: str, chroma_path: str, query: str, user_id: int, api_key: str, limit: int = 20) -> list[SearchResult]:
    """키워드 검색과 벡터 검색을 병합합니다. (RRF 또는 단순 스코어 정규화)"""
    keyword_res = search_keyword(db_path, query, user_id, limit=limit)
    vector_res = search_vector(db_path, chroma_path, query, user_id, api_key, limit=limit)
    
    # 딕셔너리로 합치기 (ID 기준 중복 제거)
    merged = {}
    
    # Keyword scores normalize (0~1)
    if keyword_res:
        max_k = max(r.score for r in keyword_res)
        min_k = min(r.score for r in keyword_res)
        range_k = max_k - min_k if max_k > min_k else 1
        for r in keyword_res:
            r.score = (r.score - min_k) / range_k
            merged[r.insight_id] = r
    
    # Vector scores normalize (0~1)
    if vector_res:
        max_v = max(r.score for r in vector_res)
        min_v = min(r.score for r in vector_res)
        range_v = max_v - min_v if max_v > min_v else 1
        for r in vector_res:
            r.score = (r.score - min_v) / range_v
            
            if r.insight_id in merged:
                # 둘 다 있으면 점수 합산 (가중치 가능)
                merged[r.insight_id].score = (merged[r.insight_id].score * 0.4) + (r.score * 0.6)
                merged[r.insight_id].search_method = 'hybrid'
            else:
                merged[r.insight_id] = r
            
    res_list = list(merged.values())
    res_list.sort(key=lambda x: x.score, reverse=True)
    return res_list[:limit]

def rerank_results(results: list[SearchResult], query: str, api_key: str, top_k: int = 10) -> list[SearchResult]:
    """LLM 기반 리랭커: 문서 리스트를 받아 프롬프트로 재정렬을 요청합니다."""
    if not results or not api_key:
        return results[:top_k]
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    
    # 문서들을 텍스트로 합치기
    docs_text = ""
    for idx, r in enumerate(results[:30]): # 최대 30개까지만 리랭킹
        docs_text += f"ID: {idx}\nTitle: {r.title}\nContent: {r.content_snippet}\n\n"
        
    prompt = f"""당신은 정보 검색 리랭커입니다. 
사용자의 질문에 가장 도움이 되는 문서를 골라 관련성 점수(0~10)를 매겨주세요. 10점이 가장 높습니다.
가장 관련성이 높은 순서대로 JSON 배열로 응답해주세요. 
코드 블록 없이 순수한 JSON 배열 형식만 출력하세요.
형식: [ {{"id": 0, "score": 9}}, {{"id": 1, "score": 7}}, ... ]

질문: {query}

문서 목록:
{docs_text}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text
        # JSON 파싱
        json_str = None
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            
        if json_str:
            scores = json.loads(json_str)
            score_map = {item['id']: item['score'] for item in scores if 'id' in item and 'score' in item}
            
            for idx, r in enumerate(results):
                # 점수 반영 (LLM이 점수를 주지 않은 것은 0점 처리)
                r.score = score_map.get(idx, 0.0)
                
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]
    except Exception as e:
        print(f"[RERANK ERROR] 리랭킹 실패: {e}")
        
    # 실패 시 원래 순서대로 반환
    return results[:top_k]

def open_source(db_path: str, insight_id: int) -> dict:
    """원본 인사이트 데이터를 조회합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}
