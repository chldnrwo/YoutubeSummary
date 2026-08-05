"""
wiki.py — Insight Pipeline LLM 위키 시스템
엔터티·주장 추출, 위키 페이지 관리, UI 렌더링을 담당합니다.
app.py를 import하지 않습니다 (순환 참조 방지).
"""

import sqlite3
import json
import re
import chromadb
from datetime import datetime, timedelta

import streamlit as st
import google.generativeai as genai

# ============================================================
# 상수
# ============================================================
CURRENT_EXTRACTION_VERSION = 1

ENTITY_TYPES = ['COMPANY', 'PERSON', 'TOPIC']
CLAIM_TYPES = ['PREDICTION', 'OPINION', 'ANALYSIS']
SENTIMENTS = ['BULLISH', 'BEARISH', 'NEUTRAL']
RELEVANCE_LEVELS = ['PRIMARY', 'SECONDARY', 'MENTION']
RELATION_TYPES = ['RELATED', 'COMPETITOR', 'SUPPLIER', 'SUBSET']

SYSTEM_INSTRUCTION_WIKI_EXTRACT = """
당신은 투자 분석 콘텐츠에서 구조화된 정보를 추출하는 전문가입니다.
주어진 분석 리포트에서 다음을 추출하십시오:

[추출 대상]
1. entities: 언급된 기업, 인물, 투자 주제 (가장 핵심적인 것만, 최대 10개)
2. claims: 예측, 전망, 의견 (구체적인 주장만, 일반 서술이나 사실 나열 제외)
3. relations: 엔터티 간 관계

[Output Format - 순수 JSON만 출력, 코드 블록 없이]
{
  "entities": [
    {
      "name": "SK하이닉스",
      "type": "COMPANY",
      "aliases": ["하이닉스", "000660"],
      "relevance": "PRIMARY"
    },
    {
      "name": "HBM",
      "type": "TOPIC",
      "aliases": ["고대역폭메모리"],
      "relevance": "PRIMARY"
    }
  ],
  "claims": [
    {
      "text": "2026년 하반기 HBM 공급 과잉이 발생할 가능성이 높다",
      "type": "PREDICTION",
      "sentiment": "BEARISH",
      "related_entities": ["HBM", "SK하이닉스"]
    }
  ],
  "relations": [
    {
      "source": "SK하이닉스",
      "target": "HBM",
      "type": "SUPPLIER"
    }
  ]
}

[규칙]
- entities는 최대 10개 (핵심적인 것만)
- claims는 구체적인 예측/전망/강한 의견만 추출 (단순 사실 서술 제외)
- claims의 text는 원문에 가깝게, 1~2문장으로
- claims가 없으면 빈 배열 []
- 한국 주식 종목은 종목코드를 aliases에 포함
- type: COMPANY(기업), PERSON(인물), TOPIC(주제/테마)
- relevance: PRIMARY(핵심 주제), SECONDARY(부차적), MENTION(단순 언급)
- sentiment: BULLISH(긍정/강세), BEARISH(부정/약세), NEUTRAL(중립)
- claim type: PREDICTION(미래 예측), OPINION(현재 의견), ANALYSIS(분석 결과)
- relation type: RELATED(관련), COMPETITOR(경쟁), SUPPLIER(공급), SUBSET(하위 주제)
"""


# ============================================================
# DB 초기화
# ============================================================
def init_wiki_tables(db_path: str):
    """위키 관련 테이블을 생성하고, insights 테이블에 추출 상태 컬럼을 추가합니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # insights 테이블에 위키 추출 상태 컬럼 추가
    for col_def in [
        ("wiki_extracted", "INTEGER DEFAULT 0"),
        ("wiki_extraction_version", "INTEGER DEFAULT 0"),
        ("wiki_extraction_error", "TEXT"),
        ("wiki_extracted_at", "TIMESTAMP"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE insights ADD COLUMN {col_def[0]} {col_def[1]}")
        except sqlite3.OperationalError:
            pass  # 이미 존재

    # 위키 엔터티
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            description TEXT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, entity_type, user_id)
        )
    """)

    # 엔터티 별칭
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_entity_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            alias TEXT NOT NULL,
            UNIQUE(entity_id, alias)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_alias_text ON wiki_entity_aliases(alias)
    """)

    # 엔터티 관계
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_entity_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            target_entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_entity_id, target_entity_id, relation_type)
        )
    """)

    # 인사이트 ↔ 엔터티 연결
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_insight_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_id INTEGER NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            relevance TEXT DEFAULT 'MENTION',
            UNIQUE(insight_id, entity_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wie_insight ON wiki_insight_entities(insight_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wie_entity ON wiki_insight_entities(entity_id)")

    # 주장
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_id INTEGER NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
            channel_title TEXT,
            claim_text TEXT NOT NULL,
            claim_type TEXT DEFAULT 'OPINION',
            sentiment TEXT DEFAULT 'NEUTRAL',
            source_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_date ON wiki_claims(source_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_channel ON wiki_claims(channel_title)")

    # 주장 ↔ 엔터티 다대다
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_claim_entities (
            claim_id INTEGER NOT NULL REFERENCES wiki_claims(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            PRIMARY KEY (claim_id, entity_id)
        )
    """)

    # 위키 페이지 캐시
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            content TEXT NOT NULL,
            source_insight_ids TEXT,
            version INTEGER DEFAULT 1,
            is_stale INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id, user_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pages_entity ON wiki_pages(entity_id)")

    # 종목 ↔ 엔터티
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wiki_stock_entities (
            stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES wiki_entities(id) ON DELETE CASCADE,
            PRIMARY KEY (stock_id, entity_id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# 엔터티 매칭 / UPSERT
# ============================================================
def match_entity(conn, name: str, entity_type: str, user_id: int) -> int | None:
    """이름 또는 별칭으로 기존 엔터티를 검색합니다. 없으면 None 반환."""
    # 1. 정확한 이름 매칭
    row = conn.execute(
        "SELECT id FROM wiki_entities WHERE name = ? AND entity_type = ? AND user_id = ?",
        (name, entity_type, user_id)
    ).fetchone()
    if row:
        return row[0]

    # 2. 별칭 매칭
    row = conn.execute("""
        SELECT e.id FROM wiki_entities e
        JOIN wiki_entity_aliases a ON e.id = a.entity_id
        WHERE a.alias = ? AND e.entity_type = ? AND e.user_id = ?
    """, (name, entity_type, user_id)).fetchone()
    if row:
        return row[0]

    return None


def upsert_entity(conn, name: str, entity_type: str, user_id: int,
                  aliases: list[str] = None) -> int:
    """엔터티를 찾거나 새로 생성합니다. 별칭도 등록합니다."""
    entity_id = match_entity(conn, name, entity_type, user_id)

    if entity_id is None:
        # 별칭으로도 매칭 시도
        if aliases:
            for alias in aliases:
                entity_id = match_entity(conn, alias, entity_type, user_id)
                if entity_id:
                    break

    if entity_id is None:
        # 새 엔터티 생성
        cursor = conn.execute(
            "INSERT INTO wiki_entities (name, entity_type, user_id) VALUES (?, ?, ?)",
            (name, entity_type, user_id)
        )
        entity_id = cursor.lastrowid

    # 별칭 등록
    if aliases:
        for alias in aliases:
            if alias and alias != name:
                conn.execute(
                    "INSERT OR IGNORE INTO wiki_entity_aliases (entity_id, alias) VALUES (?, ?)",
                    (entity_id, alias)
                )

    return entity_id


# ============================================================
# Gemini 추출
# ============================================================
def _parse_extraction_response(response_text: str) -> dict:
    """Gemini 응답에서 JSON을 파싱합니다."""
    text = response_text.strip()

    # ```json ... ``` 블록 추출
    json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()
    elif '```' in text:
        code_match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if code_match:
            text = code_match.group(1).strip()

    # json 접두사 제거
    if text.startswith('json'):
        text = text[4:].strip()

    # 중괄호로 시작하지 않으면 찾기
    if not text.startswith('{'):
        brace_match = re.search(r'\{.*', text, re.DOTALL)
        if brace_match:
            text = brace_match.group(0)

    return json.loads(text, strict=False)


def call_gemini_extract(analysis_result: str, title: str, channel_title: str,
                        api_key: str) -> dict:
    """Gemini를 호출하여 엔터티·주장을 추출합니다."""
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        generation_config=genai.GenerationConfig(
            temperature=0,
            max_output_tokens=4096,
        ),
        system_instruction=SYSTEM_INSTRUCTION_WIKI_EXTRACT
    )

    prompt = f"""다음 YouTube 영상 분석 리포트에서 엔터티와 주장을 추출해주세요.

채널: {channel_title or '알 수 없음'}
제목: {title or '제목 없음'}

분석 내용:
{analysis_result[:8000]}"""

    response = model.generate_content(prompt)
    return _parse_extraction_response(response.text)


# ============================================================
# 핵심 함수: extract_wiki_data (트랜잭션 기반 멱등성)
# ============================================================
def extract_wiki_data(db_path: str, insight_id: int, api_key: str, user_id: int):
    """인사이트에서 엔터티·주장을 추출하고 DB에 저장합니다.
    트랜잭션으로 처리하며, 재실행해도 중복이 생기지 않습니다."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 1. 인사이트 조회
        insight = conn.execute(
            "SELECT id, title, analysis_result, channel_title, published_at FROM insights WHERE id = ?",
            (insight_id,)
        ).fetchone()

        if not insight:
            raise ValueError(f"인사이트 {insight_id}를 찾을 수 없습니다")

        # 2. Gemini 추출
        extracted = call_gemini_extract(
            analysis_result=insight['analysis_result'],
            title=insight['title'],
            channel_title=insight['channel_title'],
            api_key=api_key
        )

        # 3. 트랜잭션으로 저장 (삭제 후 재생성)
        conn.execute("BEGIN")

        # 기존 추출 결과 삭제
        conn.execute("""
            DELETE FROM wiki_claim_entities
            WHERE claim_id IN (SELECT id FROM wiki_claims WHERE insight_id = ?)
        """, (insight_id,))
        conn.execute("DELETE FROM wiki_claims WHERE insight_id = ?", (insight_id,))
        conn.execute("DELETE FROM wiki_insight_entities WHERE insight_id = ?", (insight_id,))

        source_date = None
        if insight['published_at']:
            source_date = insight['published_at'][:10]

        # 엔터티 저장
        entity_name_to_id = {}
        for ent in extracted.get('entities', []):
            name = ent.get('name', '').strip()
            etype = ent.get('type', 'TOPIC')
            if not name:
                continue
            if etype not in ENTITY_TYPES:
                etype = 'TOPIC'

            aliases = ent.get('aliases', [])
            entity_id = upsert_entity(conn, name, etype, user_id, aliases)
            entity_name_to_id[name] = entity_id

            # 인사이트 ↔ 엔터티 연결
            relevance = ent.get('relevance', 'MENTION')
            if relevance not in RELEVANCE_LEVELS:
                relevance = 'MENTION'
            conn.execute(
                "INSERT OR IGNORE INTO wiki_insight_entities (insight_id, entity_id, relevance) VALUES (?, ?, ?)",
                (insight_id, entity_id, relevance)
            )

        # 주장 저장
        for claim in extracted.get('claims', []):
            claim_text = claim.get('text', '').strip()
            if not claim_text:
                continue

            claim_type = claim.get('type', 'OPINION')
            if claim_type not in CLAIM_TYPES:
                claim_type = 'OPINION'

            sentiment = claim.get('sentiment', 'NEUTRAL')
            if sentiment not in SENTIMENTS:
                sentiment = 'NEUTRAL'

            cursor = conn.execute("""
                INSERT INTO wiki_claims (insight_id, channel_title, claim_text, claim_type, sentiment, source_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (insight_id, insight['channel_title'], claim_text, claim_type, sentiment, source_date))
            claim_id = cursor.lastrowid

            # 주장 ↔ 엔터티 다대다 연결
            related_entities = claim.get('related_entities', [])
            for ent_name in related_entities:
                ent_id = entity_name_to_id.get(ent_name)
                if ent_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO wiki_claim_entities (claim_id, entity_id) VALUES (?, ?)",
                        (claim_id, ent_id)
                    )

        # 관계 저장
        for rel in extracted.get('relations', []):
            src_id = entity_name_to_id.get(rel.get('source'))
            tgt_id = entity_name_to_id.get(rel.get('target'))
            rel_type = rel.get('type', 'RELATED')
            if src_id and tgt_id and src_id != tgt_id:
                if rel_type not in RELATION_TYPES:
                    rel_type = 'RELATED'
                conn.execute(
                    "INSERT OR IGNORE INTO wiki_entity_relations (source_entity_id, target_entity_id, relation_type) VALUES (?, ?, ?)",
                    (src_id, tgt_id, rel_type)
                )

        # 영향받는 위키 페이지 stale 마킹
        conn.execute("""
            UPDATE wiki_pages SET is_stale = 1
            WHERE entity_id IN (
                SELECT entity_id FROM wiki_insight_entities WHERE insight_id = ?
            )
        """, (insight_id,))

        # 추출 상태 업데이트
        conn.execute("""
            UPDATE insights
            SET wiki_extracted = 1,
                wiki_extraction_version = ?,
                wiki_extraction_error = NULL,
                wiki_extracted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (CURRENT_EXTRACTION_VERSION, insight_id))

        conn.commit()

        # ChromaDB 동기화
        for eid in set(entity_name_to_id.values()):
            _sync_entity_to_chroma(db_path, eid)

    except Exception as e:
        conn.rollback()
        # 실패 상태 기록 (별도 커밋)
        try:
            conn.execute("""
                UPDATE insights
                SET wiki_extracted = -1,
                    wiki_extraction_error = ?
                WHERE id = ?
            """, (str(e)[:500], insight_id))
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ============================================================
# 엔터티 병합
# ============================================================
def merge_entities(db_path: str, keep_id: int, remove_id: int):
    """remove_id 엔터티를 keep_id로 병합합니다.
    모든 연결 테이블의 참조를 이전하고, remove_id를 삭제합니다.
    전체가 하나의 트랜잭션으로 처리됩니다."""

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")

        # 1. wiki_insight_entities: entity_id 교체
        conn.execute(
            "UPDATE OR IGNORE wiki_insight_entities SET entity_id = ? WHERE entity_id = ?",
            (keep_id, remove_id))
        conn.execute(
            "DELETE FROM wiki_insight_entities WHERE entity_id = ?", (remove_id,))

        # 2. wiki_claim_entities: entity_id 교체
        conn.execute(
            "UPDATE OR IGNORE wiki_claim_entities SET entity_id = ? WHERE entity_id = ?",
            (keep_id, remove_id))
        conn.execute(
            "DELETE FROM wiki_claim_entities WHERE entity_id = ?", (remove_id,))

        # 3. wiki_entity_aliases: entity_id 교체
        conn.execute(
            "UPDATE OR IGNORE wiki_entity_aliases SET entity_id = ? WHERE entity_id = ?",
            (keep_id, remove_id))
        conn.execute(
            "DELETE FROM wiki_entity_aliases WHERE entity_id = ?", (remove_id,))

        # 4. wiki_stock_entities: entity_id 교체
        conn.execute(
            "UPDATE OR IGNORE wiki_stock_entities SET entity_id = ? WHERE entity_id = ?",
            (keep_id, remove_id))
        conn.execute(
            "DELETE FROM wiki_stock_entities WHERE entity_id = ?", (remove_id,))

        # 5. wiki_entity_relations: 양방향 교체
        for col in ["source_entity_id", "target_entity_id"]:
            conn.execute(
                f"UPDATE OR IGNORE wiki_entity_relations SET {col} = ? WHERE {col} = ?",
                (keep_id, remove_id))
            conn.execute(
                f"DELETE FROM wiki_entity_relations WHERE {col} = ?", (remove_id,))
        # 자기 자신과의 관계 제거
        conn.execute(
            "DELETE FROM wiki_entity_relations WHERE source_entity_id = target_entity_id")

        # 6. remove_id의 이름을 keep_id의 별칭으로 추가
        old_name_row = conn.execute(
            "SELECT name FROM wiki_entities WHERE id = ?", (remove_id,)).fetchone()
        if old_name_row:
            conn.execute(
                "INSERT OR IGNORE INTO wiki_entity_aliases (entity_id, alias) VALUES (?, ?)",
                (keep_id, old_name_row[0]))

        # 7. wiki_pages: remove_id의 페이지 삭제
        conn.execute("DELETE FROM wiki_pages WHERE entity_id = ?", (remove_id,))

        # 8. 원본 엔터티 삭제
        conn.execute("DELETE FROM wiki_entities WHERE id = ?", (remove_id,))

        # 9. 병합된 엔터티의 위키 페이지 stale 마킹
        conn.execute("UPDATE wiki_pages SET is_stale = 1 WHERE entity_id = ?", (keep_id,))

        conn.commit()
        
        # ChromaDB 처리: 제거된 엔터티 벡터 삭제 후 합쳐진 엔터티 갱신
        try:
            chroma_path = str(Path(db_path).parent / "chroma_db")
            chroma_client = chromadb.PersistentClient(path=chroma_path)
            collection = chroma_client.get_or_create_collection(name="wiki_entities")
            collection.delete(ids=[str(remove_id)])
        except Exception:
            pass
        _sync_entity_to_chroma(db_path, keep_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _sync_entity_to_chroma(db_path: str, entity_id: int):
    """엔터티의 텍스트 정보를 ChromaDB에 동기화(Upsert)합니다."""
    try:
        chroma_path = str(Path(db_path).parent / "chroma_db")
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        collection = chroma_client.get_or_create_collection(name="wiki_entities")

        conn = sqlite3.connect(db_path)
        ent = conn.execute("SELECT name, description, entity_type FROM wiki_entities WHERE id = ?", (entity_id,)).fetchone()
        if not ent:
            conn.close()
            return
            
        aliases = conn.execute("SELECT alias FROM wiki_entity_aliases WHERE entity_id = ?", (entity_id,)).fetchall()
        conn.close()
        
        name, desc, etype = ent
        alias_str = ", ".join([a[0] for a in aliases]) if aliases else ""
        
        text_for_embedding = f"이름: {name}"
        if alias_str:
            text_for_embedding += f"\n별칭: {alias_str}"
        if desc:
            text_for_embedding += f"\n설명: {desc}"
            
        collection.upsert(
            ids=[str(entity_id)],
            documents=[text_for_embedding],
            metadatas=[{"name": name, "type": etype}]
        )
    except Exception as e:
        print(f"[위키 시맨틱] 엔터티 동기화 실패: {e}")

# ============================================================
# 조회 함수
# ============================================================
def get_wiki_entities(db_path: str, user_id: int, entity_type: str = None,
                      search: str = None, days: int = None,
                      limit: int = 50) -> list[dict]:
    """엔터티 목록을 조회합니다. 언급 횟수(인사이트 연결 수)로 정렬됩니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT e.id, e.name, e.entity_type, e.description,
               COUNT(DISTINCT wie.insight_id) as mention_count,
               MAX(i.published_at) as last_mentioned
        FROM wiki_entities e
        LEFT JOIN wiki_insight_entities wie ON e.id = wie.entity_id
        LEFT JOIN insights i ON wie.insight_id = i.id
        WHERE e.user_id = ?
    """
    params = [user_id]

    if entity_type:
        query += " AND e.entity_type = ?"
        params.append(entity_type)

    semantic_ids = []
    if search:
        try:
            chroma_path = str(Path(db_path).parent / "chroma_db")
            chroma_client = chromadb.PersistentClient(path=chroma_path)
            collection = chroma_client.get_or_create_collection(name="wiki_entities")
            
            results = collection.query(
                query_texts=[search],
                n_results=100
            )
            
            if results and results['ids'] and results['ids'][0]:
                semantic_ids = [int(i) for i in results['ids'][0]]
                
            if semantic_ids:
                placeholders = ",".join("?" * len(semantic_ids))
                query += f" AND e.id IN ({placeholders})"
                params.extend(semantic_ids)
            else:
                query += " AND 1=0"
        except Exception as e:
            print(f"[위키 시맨틱] 검색 실패: {e}")
            query += """ AND (e.name LIKE ? OR e.id IN (
                SELECT entity_id FROM wiki_entity_aliases WHERE alias LIKE ?
            ))"""
            params.extend([f"%{search}%", f"%{search}%"])

    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        query += " AND i.published_at >= ?"
        params.append(cutoff)

    query += " GROUP BY e.id"
    
    if search and semantic_ids:
        order_cases = " ".join([f"WHEN e.id = {sid} THEN {idx}" for idx, sid in enumerate(semantic_ids)])
        query += f" ORDER BY CASE {order_cases} ELSE 9999 END"
    else:
        query += " ORDER BY mention_count DESC"
        
    query += " LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_entity_detail(db_path: str, entity_id: int) -> dict | None:
    """엔터티 상세 정보 (별칭, 관련 인사이트, 관련 엔터티)를 반환합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    entity = conn.execute(
        "SELECT * FROM wiki_entities WHERE id = ?", (entity_id,)).fetchone()
    if not entity:
        conn.close()
        return None

    result = dict(entity)

    # 별칭
    aliases = conn.execute(
        "SELECT alias FROM wiki_entity_aliases WHERE entity_id = ?",
        (entity_id,)).fetchall()
    result['aliases'] = [a['alias'] for a in aliases]

    # 관련 인사이트 (최근순, 최대 30건)
    insights = conn.execute("""
        SELECT i.id, i.title, i.channel_title, i.published_at, i.video_url,
               wie.relevance
        FROM insights i
        JOIN wiki_insight_entities wie ON i.id = wie.insight_id
        WHERE wie.entity_id = ?
        ORDER BY i.published_at DESC
        LIMIT 30
    """, (entity_id,)).fetchall()
    result['insights'] = [dict(i) for i in insights]

    # 관련 엔터티 (양방향, 중복 제거)
    related = conn.execute("""
        SELECT e.id, e.name, e.entity_type
        FROM wiki_entity_relations r
        JOIN wiki_entities e ON (
            CASE WHEN r.source_entity_id = ? THEN r.target_entity_id
                 ELSE r.source_entity_id END = e.id
        )
        WHERE r.source_entity_id = ? OR r.target_entity_id = ?
        GROUP BY e.id
    """, (entity_id, entity_id, entity_id)).fetchall()
    result['related_entities'] = [dict(r) for r in related]

    # 연결된 주식 종목
    stocks = conn.execute("""
        SELECT s.id, s.symbol, s.name
        FROM stocks s
        JOIN wiki_stock_entities wse ON s.id = wse.stock_id
        WHERE wse.entity_id = ?
    """, (entity_id,)).fetchall()
    result['stocks'] = [dict(s) for s in stocks]

    conn.close()
    return result


def get_claims_for_entity(db_path: str, entity_id: int, limit: int = 50) -> list[dict]:
    """특정 엔터티에 연결된 주장을 날짜순으로 반환합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT c.id, c.claim_text, c.claim_type, c.sentiment,
               c.channel_title, c.source_date, c.insight_id,
               i.title as insight_title, i.video_url
        FROM wiki_claims c
        JOIN wiki_claim_entities ce ON c.id = ce.claim_id
        JOIN insights i ON c.insight_id = i.id
        WHERE ce.entity_id = ?
        ORDER BY c.source_date DESC
        LIMIT ?
    """, (entity_id, limit)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_all_claims(db_path: str, user_id: int, entity_type: str = None,
                   channel: str = None, days: int = None,
                   limit: int = 100) -> list[dict]:
    """전체 주장을 필터링하여 반환합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT c.id, c.claim_text, c.claim_type, c.sentiment,
               c.channel_title, c.source_date, c.insight_id,
               i.title as insight_title, i.video_url,
               GROUP_CONCAT(DISTINCT e.name) as related_entity_names
        FROM wiki_claims c
        JOIN insights i ON c.insight_id = i.id
        LEFT JOIN wiki_claim_entities ce ON c.id = ce.claim_id
        LEFT JOIN wiki_entities e ON ce.entity_id = e.id
        WHERE i.user_id = ?
    """
    params = [user_id]

    if channel:
        query += " AND c.channel_title = ?"
        params.append(channel)

    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        query += " AND c.source_date >= ?"
        params.append(cutoff)

    query += " GROUP BY c.id ORDER BY c.source_date DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_channel_summary(db_path: str, user_id: int) -> list[dict]:
    """채널별 요약 (총 분석 수, 주요 주제, 강세/약세 비율)을 반환합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 채널별 분석 수
    channels = conn.execute("""
        SELECT channel_title, COUNT(*) as insight_count
        FROM insights
        WHERE user_id = ? AND channel_title IS NOT NULL
        GROUP BY channel_title
        ORDER BY insight_count DESC
    """, (user_id,)).fetchall()

    result = []
    for ch in channels:
        channel_name = ch['channel_title']
        data = dict(ch)

        # 최근 30일 주요 주제
        topics = conn.execute("""
            SELECT e.name, COUNT(*) as cnt
            FROM wiki_insight_entities wie
            JOIN wiki_entities e ON wie.entity_id = e.id
            JOIN insights i ON wie.insight_id = i.id
            WHERE i.channel_title = ? AND i.user_id = ?
              AND i.published_at >= date('now', '-30 days')
            GROUP BY e.id
            ORDER BY cnt DESC
            LIMIT 5
        """, (channel_name, user_id)).fetchall()
        data['recent_topics'] = [dict(t) for t in topics]

        # 강세/약세 비율
        sentiments = conn.execute("""
            SELECT sentiment, COUNT(*) as cnt
            FROM wiki_claims
            WHERE channel_title = ?
            GROUP BY sentiment
        """, (channel_name,)).fetchall()
        data['sentiment_distribution'] = {s['sentiment']: s['cnt'] for s in sentiments}

        # 최근 주장 5건
        recent_claims = conn.execute("""
            SELECT claim_text, claim_type, sentiment, source_date
            FROM wiki_claims
            WHERE channel_title = ?
            ORDER BY source_date DESC
            LIMIT 5
        """, (channel_name,)).fetchall()
        data['recent_claims'] = [dict(c) for c in recent_claims]

        result.append(data)

    conn.close()
    return result


def get_extraction_stats(db_path: str, user_id: int) -> dict:
    """위키 추출 상태 통계를 반환합니다."""
    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN wiki_extracted = 1 THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN wiki_extracted = -1 THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN wiki_extracted = 0 THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN wiki_extracted = 1 AND wiki_extraction_version < ? THEN 1 ELSE 0 END) as outdated
        FROM insights
        WHERE user_id = ?
    """, (CURRENT_EXTRACTION_VERSION, user_id)).fetchone()
    conn.close()
    return {
        'total': row[0],
        'completed': row[1],
        'failed': row[2],
        'pending': row[3],
        'outdated': row[4],
    }


# ============================================================
# 종목 ↔ 엔터티 자동 연결
# ============================================================
def link_stocks_to_entities(db_path: str, user_id: int) -> int:
    """기존 종목과 동일 이름의 COMPANY 엔터티를 자동으로 연결합니다.
    연결된 건수를 반환합니다."""
    conn = sqlite3.connect(db_path)
    linked = 0

    stocks = conn.execute(
        "SELECT id, name FROM stocks WHERE user_id = ?", (user_id,)).fetchall()

    for stock_id, stock_name in stocks:
        entity = conn.execute(
            "SELECT id FROM wiki_entities WHERE name = ? AND entity_type = 'COMPANY' AND user_id = ?",
            (stock_name, user_id)).fetchone()
        if entity:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO wiki_stock_entities (stock_id, entity_id) VALUES (?, ?)",
                    (stock_id, entity[0]))
                linked += 1
            except Exception:
                pass

    conn.commit()
    conn.close()
    return linked


# ============================================================
# UI 렌더링
# ============================================================
def render_wiki_tab(db_path: str, user_id: int, api_key: str = None):
    """위키 탭 전체를 렌더링합니다. app.py의 main()에서 호출됩니다."""
    st.subheader("📖 투자 위키")

    tab_explore, tab_claims, tab_channels, tab_admin = st.tabs(
        ["🏷️ 주제 탐색", "📢 주장 추적", "📺 채널 분석", "⚙️ 관리"]
    )

    with tab_explore:
        _render_explore_tab(db_path, user_id)

    with tab_claims:
        _render_claims_tab(db_path, user_id)

    with tab_channels:
        _render_channels_tab(db_path, user_id)

    with tab_admin:
        _render_admin_tab(db_path, user_id, api_key)


def _render_explore_tab(db_path: str, user_id: int):
    """주제 탐색 탭: 엔터티 목록 + 상세 페이지"""
    
    # 커스텀 CSS 주입 (위키 탭 UI 개선)
    st.markdown("""
    <style>
        /* 일반 엔터티 버튼 좌측 정렬 및 세로 높이 압축 */
        div[class*="st-key-ent_"] button {
            justify-content: flex-start !important;
            text-align: left !important;
            padding-left: 15px !important;
            padding-top: 0.2rem !important;
            padding-bottom: 0.2rem !important;
            min-height: 2.2rem !important;
        }
        
        /* 핫 토픽 버튼 트렌디한 호버/그림자 효과 */
        div[class*="st-key-top_ent_"] button {
            background: linear-gradient(135deg, #f8faff, #ffffff);
            border: 1px solid #d0dfff !important;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
            transition: all 0.2s ease-in-out;
        }
        div[class*="st-key-top_ent_"] button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(66, 133, 244, 0.15);
            border-color: #4285f4 !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # 상세 페이지 모드
    if 'wiki_selected_entity' in st.session_state:
        entity_id = st.session_state['wiki_selected_entity']
        if st.button("← 목록으로"):
            del st.session_state['wiki_selected_entity']
            st.rerun()
        _render_entity_detail(db_path, entity_id, user_id)
        return

    # 검색 및 필터
    col_search, col_type, col_period = st.columns([3, 2, 2])
    with col_search:
        search = st.text_input("🔍 검색", placeholder="기업, 인물, 주제...", key="wiki_search")
    with col_type:
        type_options = {"전체": None, "기업": "COMPANY", "인물": "PERSON", "주제": "TOPIC"}
        selected_type = st.selectbox("분류", list(type_options.keys()), key="wiki_type_filter")
    with col_period:
        period_options = {"전체": None, "최근 7일": 7, "최근 30일": 30, "최근 90일": 90}
        selected_period = st.selectbox("기간", list(period_options.keys()), index=1, key="wiki_period_filter")

    entities = get_wiki_entities(
        db_path, user_id,
        entity_type=type_options[selected_type],
        search=search if search else None,
        days=period_options[selected_period],
        limit=100
    )

    if not entities:
        st.info("아직 위키 데이터가 없습니다. 영상을 분석하면 자동으로 엔터티가 추출됩니다.")
        return

    # 자주 언급되는 주제 (상위 8개)
    top_entities = entities[:8]
    if top_entities:
        st.markdown("**🔥 자주 언급되는 주제**")
        cols = st.columns(min(len(top_entities), 4))
        for i, ent in enumerate(top_entities):
            with cols[i % 4]:
                type_emoji = {"COMPANY": "🏢", "PERSON": "👤", "TOPIC": "📌"}.get(ent['entity_type'], "📌")
                if st.button(
                    f"{type_emoji} {ent['name']}\n({ent['mention_count']}건)",
                    key=f"top_ent_{ent['id']}",
                    use_container_width=True
                ):
                    st.session_state['wiki_selected_entity'] = ent['id']
                    st.rerun()

    st.markdown("---")

    # 전체 목록
    type_groups = {}
    for ent in entities:
        etype = ent['entity_type']
        if etype not in type_groups:
            type_groups[etype] = []
        type_groups[etype].append(ent)

    type_labels = {"COMPANY": "🏢 기업", "TOPIC": "📌 주제", "PERSON": "👤 인물"}
    
    # 세로 길이 축소를 위해 expander 대신 tabs 사용
    available_etypes = [t for t in ["COMPANY", "TOPIC", "PERSON"] if t in type_groups]
    if available_etypes:
        tabs = st.tabs([f"{type_labels.get(t, t)} ({len(type_groups[t])}개)" for t in available_etypes])
        
        for idx, etype in enumerate(available_etypes):
            with tabs[idx]:
                group = type_groups[etype]
                # 4열로 더 촘촘하게 배치
                cols = st.columns(4)
                for i, ent in enumerate(group):
                    with cols[i % 4]:
                        label = f"{ent['name']} ({ent['mention_count']}건)"
                        if ent.get('last_mentioned'):
                            label += f" · {ent['last_mentioned'][:10]}"
                            
                        if st.button(
                            label,
                            key=f"ent_{ent['id']}",
                            use_container_width=True
                        ):
                            st.session_state['wiki_selected_entity'] = ent['id']
                            st.rerun()


def _render_entity_detail(db_path: str, entity_id: int, user_id: int):
    """엔터티 상세 위키 페이지"""
    detail = get_entity_detail(db_path, entity_id)
    if not detail:
        st.error("엔터티를 찾을 수 없습니다.")
        return

    type_emoji = {"COMPANY": "🏢", "PERSON": "👤", "TOPIC": "📌"}.get(detail['entity_type'], "📌")
    st.markdown(f"## {type_emoji} {detail['name']}")

    if detail['aliases']:
        st.caption(f"별칭: {', '.join(detail['aliases'])}")

    # 연결된 주식 종목
    if detail['stocks']:
        st.markdown("**📈 연결된 종목**")
        for stock in detail['stocks']:
            st.write(f"• {stock['name']} ({stock['symbol']})")

    st.markdown("---")

    # 주장 타임라인
    claims = get_claims_for_entity(db_path, entity_id, limit=500)
    if claims:
        st.markdown(f"**📢 주요 주장 ({len(claims)}건)**")
        
        with st.expander("🤖 뭉탱이로 ChatGPT Pro에 던지기 (프롬프트 복사)"):
            st.caption("코드 블록 우측 상단의 복사 아이콘을 누른 후, 본인의 ChatGPT 창에 붙여넣기 하세요.")
            prompt_lines = [
                f"너는 월스트리트의 탑 티어 애널리스트야. 아래는 내가 유튜브 경제 방송에서 수집한 '{detail['name']}'에 대한 최근 전문가들의 주장 Raw Data야.",
                "이 데이터를 바탕으로 다음 3가지를 정리해서 완벽한 투자 리포트를 작성해 줘.",
                "1. 현재 시장의 핵심 쟁점 및 비관론/낙관론 요약",
                "2. 투자자들이 놓치고 있는 숨은 리스크",
                "3. 향후 대응 전략\n",
                "[Data Start]"
            ]
            sentiment_kr = {"BULLISH": "🟢강세", "BEARISH": "🔴약세", "NEUTRAL": "🟡중립"}
            for claim in claims:
                sent = sentiment_kr.get(claim['sentiment'], "중립")
                date_str = claim['source_date'] or "날짜 미상"
                channel = claim['channel_title'] or "알 수 없음"
                prompt_lines.append(f"- {date_str} | {channel} | {sent}: {claim['claim_text']}")
            prompt_lines.append("[Data End]")
            
            st.code("\n".join(prompt_lines), language="markdown")

        sentiment_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
        with st.container(height=400, border=True):
            for claim in claims:
                emoji = sentiment_emoji.get(claim['sentiment'], "⚪")
                date_str = claim['source_date'] or "날짜 미상"
                channel = claim['channel_title'] or "알 수 없음"
                
                link = f" [📎 원본]({claim['video_url']})" if claim.get('video_url') else ""
                st.markdown(f"**{date_str}** {channel} | {emoji} {claim['claim_text']}{link}")

    st.markdown("---")

    # 관련 주제
    if detail['related_entities']:
        st.markdown("**🔗 관련 주제**")
        
        # 중복 제거 안전장치
        seen_ids = set()
        unique_rels = []
        for rel in detail['related_entities']:
            if rel['id'] not in seen_ids:
                seen_ids.add(rel['id'])
                unique_rels.append(rel)
                
        cols = st.columns(5)
        for i, rel in enumerate(unique_rels):
            with cols[i % 5]:
                rel_emoji = {"COMPANY": "🏢", "PERSON": "👤", "TOPIC": "📌"}.get(rel['entity_type'], "📌")
                if st.button(f"{rel_emoji} {rel['name']}", key=f"rel_{rel['id']}_{i}", use_container_width=True):
                    st.session_state['wiki_selected_entity'] = rel['id']
                    st.rerun()

    st.markdown("---")

    # 관련 영상
    if detail['insights']:
        st.markdown(f"**📺 관련 영상 ({len(detail['insights'])}건)**")
        with st.container(height=300, border=True):
            for ins in detail['insights']:
                date_str = ins['published_at'][:10] if ins['published_at'] else ""
                channel = ins['channel_title'] or ""
                title = ins['title'] or f"영상 {ins['id']}"
                relevance_badge = {"PRIMARY": "⭐", "SECONDARY": "◾", "MENTION": "·"}.get(ins['relevance'], "·")
                
                link = f" [📎]({ins['video_url']})" if ins.get('video_url') else ""
                st.markdown(f"{relevance_badge} **{date_str}** {channel} — {title}{link}")

    # 경고 문구
    st.markdown("---")
    st.caption("⚠️ 이 페이지는 AI가 원본 분석에서 추출한 데이터를 구조화한 것입니다. 정확한 내용은 📎원본 영상을 확인하세요.")


def _render_claims_tab(db_path: str, user_id: int):
    """주장 추적 탭: 날짜순 주장 목록"""

    # 필터
    col1, col2, col3 = st.columns(3)
    with col1:
        # 채널 목록 가져오기
        conn = sqlite3.connect(db_path)
        channels_rows = conn.execute("""
            SELECT DISTINCT channel_title FROM wiki_claims
            WHERE channel_title IS NOT NULL
            ORDER BY channel_title
        """).fetchall()
        conn.close()
        channel_options = ["전체"] + [r[0] for r in channels_rows]
        selected_channel = st.selectbox("📺 채널", channel_options, key="claims_channel")

    with col2:
        period_map = {"전체": None, "최근 7일": 7, "최근 30일": 30, "최근 90일": 90}
        selected_period = st.selectbox("📅 기간", list(period_map.keys()), index=1, key="claims_period")

    with col3:
        sentiment_filter = st.selectbox("논조", ["전체", "🟢 강세", "🔴 약세", "🟡 중립"], key="claims_sentiment")

    claims = get_all_claims(
        db_path, user_id,
        channel=selected_channel if selected_channel != "전체" else None,
        days=period_map[selected_period]
    )

    # 논조 필터 적용
    if sentiment_filter != "전체":
        sentiment_map = {"🟢 강세": "BULLISH", "🔴 약세": "BEARISH", "🟡 중립": "NEUTRAL"}
        target = sentiment_map.get(sentiment_filter)
        if target:
            claims = [c for c in claims if c['sentiment'] == target]

    if not claims:
        st.info("조건에 맞는 주장이 없습니다.")
        return

    st.markdown(f"**총 {len(claims)}건의 주장**")

    sentiment_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
    for claim in claims:
        emoji = sentiment_emoji.get(claim['sentiment'], "⚪")
        date_str = claim['source_date'] or "날짜 미상"
        channel = claim['channel_title'] or ""
        entities = claim.get('related_entity_names', '') or ''

        with st.container():
            st.markdown(f"**{date_str}** | {channel} | {emoji} {claim['claim_text']}")
            meta_parts = []
            if entities:
                meta_parts.append(f"🏷️ {entities}")
            if claim.get('video_url'):
                meta_parts.append(f"[📎 원본]({claim['video_url']})")
            if meta_parts:
                st.caption(" · ".join(meta_parts))


def _render_channels_tab(db_path: str, user_id: int):
    """채널 분석 탭"""
    channel_data = get_channel_summary(db_path, user_id)

    if not channel_data:
        st.info("아직 위키 데이터가 없습니다.")
        return

    # 채널 선택
    channel_names = [ch['channel_title'] for ch in channel_data]
    selected_idx = st.selectbox(
        "채널 선택",
        range(len(channel_names)),
        format_func=lambda i: f"{channel_names[i]} ({channel_data[i]['insight_count']}건)",
        key="channel_select"
    )

    ch = channel_data[selected_idx]
    st.markdown(f"## 📺 {ch['channel_title']}")
    st.write(f"총 분석 영상: **{ch['insight_count']}건**")

    # 주요 주제
    if ch['recent_topics']:
        st.markdown("**🏷️ 최근 30일 주요 주제**")
        topic_text = " · ".join([f"{t['name']}({t['cnt']})" for t in ch['recent_topics']])
        st.write(topic_text)

    # 논조 분포
    if ch['sentiment_distribution']:
        st.markdown("**📊 논조 분포**")
        dist = ch['sentiment_distribution']
        total = sum(dist.values())
        if total > 0:
            col1, col2, col3 = st.columns(3)
            with col1:
                bullish = dist.get('BULLISH', 0)
                st.metric("🟢 강세", f"{bullish}건", f"{bullish/total*100:.0f}%")
            with col2:
                bearish = dist.get('BEARISH', 0)
                st.metric("🔴 약세", f"{bearish}건", f"{bearish/total*100:.0f}%")
            with col3:
                neutral = dist.get('NEUTRAL', 0)
                st.metric("🟡 중립", f"{neutral}건", f"{neutral/total*100:.0f}%")

    # 최근 주장
    if ch['recent_claims']:
        st.markdown("**📢 최근 주장**")
        sentiment_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
        for claim in ch['recent_claims']:
            emoji = sentiment_emoji.get(claim['sentiment'], "⚪")
            date_str = claim['source_date'] or ""
            st.write(f"{date_str} {emoji} {claim['claim_text']}")


def _render_admin_tab(db_path: str, user_id: int, api_key: str = None):
    """관리 탭: 추출 상태, 재시도, 엔터티 병합"""

    # 추출 상태 통계
    stats = get_extraction_stats(db_path, user_id)
    st.markdown("### 📊 위키 추출 상태")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("✅ 완료", stats['completed'])
    with col2:
        st.metric("⏳ 미처리", stats['pending'])
    with col3:
        st.metric("❌ 실패", stats['failed'])
    with col4:
        st.metric("🔄 구버전", stats['outdated'])

    # 실패한 항목 재시도
    if stats['failed'] and stats['failed'] > 0:
        if st.button("❌ 실패한 항목 재시도", key="retry_failed"):
            if not api_key:
                st.error("API Key가 설정되어 있지 않습니다.")
            else:
                conn = sqlite3.connect(db_path)
                failed_ids = [r[0] for r in conn.execute(
                    "SELECT id FROM insights WHERE user_id = ? AND wiki_extracted = -1",
                    (user_id,)).fetchall()]
                conn.close()

                progress = st.progress(0)
                for i, iid in enumerate(failed_ids):
                    try:
                        extract_wiki_data(db_path, iid, api_key, user_id)
                    except Exception as e:
                        st.warning(f"ID {iid} 재시도 실패: {e}")
                    progress.progress((i + 1) / len(failed_ids))
                st.success(f"{len(failed_ids)}건 재시도 완료")
                st.rerun()

    st.markdown("---")

    # 엔터티 병합
    st.markdown("### 🔀 엔터티 병합")
    st.caption("동일한 대상이 다른 이름으로 등록된 경우, 하나로 합칠 수 있습니다.")

    entities = get_wiki_entities(db_path, user_id, limit=200)
    if len(entities) < 2:
        st.info("병합할 엔터티가 충분하지 않습니다.")
        return

    entity_options = {f"{e['name']} ({e['entity_type']}, {e['mention_count']}건)": e['id'] for e in entities}
    option_list = list(entity_options.keys())

    col1, col2 = st.columns(2)
    with col1:
        keep_label = st.selectbox("유지할 엔터티", option_list, key="merge_keep")
    with col2:
        remove_label = st.selectbox("삭제할 엔터티 (이 쪽이 합쳐짐)", option_list, key="merge_remove")

    if keep_label and remove_label and keep_label != remove_label:
        keep_id = entity_options[keep_label]
        remove_id = entity_options[remove_label]

        st.warning(f"'{remove_label}'의 모든 연결(영상, 주장, 관계)이 '{keep_label}'로 이전되고, '{remove_label}'은 삭제됩니다.")

        if st.button("🔀 병합 실행", type="primary", key="merge_execute"):
            try:
                merge_entities(db_path, keep_id, remove_id)
                st.success("병합 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"병합 실패: {e}")
    elif keep_label == remove_label:
        st.error("같은 엔터티를 선택할 수 없습니다.")
