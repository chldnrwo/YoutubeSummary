"""
rag_agent.py - Agentic RAG 모듈
반복 검색을 통해 질문을 분석하고, 충분한 근거를 확보한 뒤 답변을 생성합니다.
app.py를 import하지 않습니다.
"""
import google.generativeai as genai
import json
import time
from dataclasses import dataclass
from retrieval import hybrid_search, rerank_results, open_source, SearchResult
from search_quality_log import log_search
import re

MAX_RETRIEVAL_STEPS = 5

@dataclass
class Citation:
    source_type: str
    source_id: int
    title: str
    excerpt: str
    url: str | None
    date: str | None

@dataclass
class AgentResponse:
    answer: str
    citations: list[Citation]
    retrieval_log: list[dict]
    confidence: str
    processing_time_ms: int

class RAGAgent:
    def __init__(self, db_path: str, chroma_path: str, api_key: str, user_id: int):
        self.db_path = db_path
        self.chroma_path = chroma_path
        self.api_key = api_key
        self.user_id = user_id
        
    def answer(self, query: str, filters: dict = None, chat_history: list = None) -> AgentResponse:
        start_time = time.time()
        retrieval_log = []
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        
        # 1. 질문 분석
        analysis_prompt = f"""사용자의 질문을 분석하여 어떤 검색 전략이 적절한지 판단하세요.
결과는 JSON으로 출력하세요.
질문: {query}

응답 형식:
{{
  "query_type": "exact_match" | "semantic" | "relational" | "mixed",
  "search_strategies": ["keyword", "vector"]
}}
"""
        try:
            analysis_res = model.generate_content(analysis_prompt)
            analysis_text = analysis_res.text
            json_match = re.search(r'\{.*\}', analysis_text, re.DOTALL)
            if json_match:
                analysis_data = json.loads(json_match.group(0))
            else:
                analysis_data = {"query_type": "semantic", "search_strategies": ["keyword", "vector"]}
        except Exception:
            analysis_data = {"query_type": "semantic", "search_strategies": ["keyword", "vector"]}
            
        retrieval_log.append({"step": 1, "action": "Analyze Query", "result": analysis_data})
        
        # 2. 검색 실행 (Hybrid Search 기반)
        results = hybrid_search(
            db_path=self.db_path,
            chroma_path=self.chroma_path,
            query=query,
            user_id=self.user_id,
            api_key=self.api_key,
            limit=30
        )
        
        # 3. 필터 적용 (카테고리, 날짜 등)
        if filters:
            filtered_results = []
            for r in results:
                # 카테고리 필터
                if filters.get('category') and filters['category'] != "전체":
                    if r.metadata.get('category') != filters['category']:
                        continue
                        
                # 날짜 필터 로직
                if filters.get('cutoff_date'):
                    doc_date = r.metadata.get('published_at', '')[:10]
                    if doc_date and doc_date < filters['cutoff_date']:
                        continue
                        
                filtered_results.append(r)
            results = filtered_results
            
        # 4. Reranking
        if results:
            results = rerank_results(results, query, self.api_key, top_k=10)
            
        retrieval_log.append({
            "step": 2, 
            "action": "Retrieve & Rerank", 
            "result_count": len(results),
            "top_docs": [{"id": r.insight_id, "score": r.score} for r in results[:5]]
        })
        
        # 5. 최종 컨텍스트 구성 및 답변 생성
        context_docs = []
        for i, r in enumerate(results[:10]):
            date_str = r.metadata.get('published_at', '')[:10] if r.metadata.get('published_at') else "날짜 미상"
            cat_str = r.metadata.get('category', '그 외')
            context_docs.append(f"[문서 {i+1}] ID:{r.insight_id} | {r.title} | {cat_str} | {date_str}\n{r.content_snippet}")
            
        context_text = "\n\n".join(context_docs)
        
        if not results:
            processing_time = int((time.time() - start_time) * 1000)
            log_search(self.db_path, {
                "user_id": self.user_id, "query": query, "query_type": analysis_data.get('query_type'),
                "search_strategies": analysis_data.get('search_strategies'), "search_queries": [query],
                "retrieved_docs": [], "reranked_docs": [], "retrieval_steps": 1,
                "final_sources": [], "final_answer": "문서 없음", "confidence": "low", "processing_time_ms": processing_time
            })
            return AgentResponse(
                answer="선택하신 조건(필터)에 부합하는 분석 문서가 지식베이스에 없습니다. 필터를 변경하거나 질문을 바꿔보세요.",
                citations=[],
                retrieval_log=retrieval_log,
                confidence="low",
                processing_time_ms=processing_time
            )
            
        history_text = ""
        if chat_history:
            recent_history = chat_history[-5:]
            for h in recent_history:
                history_text += f"User: {h['query']}\nAssistant: {h['response']}\n\n"
            
        final_prompt = f"""당신은 사용자의 개인 지식베이스(세컨드 브레인)를 관리하는 AI 비서입니다.
아래 제공된 [관련 지식 문서]들만을 바탕으로 사용자의 [현재 질문]에 상세하고 친절하게 답변해주세요.
이전 대화의 문맥(Context)이 있다면, 이를 참고하여 답변하세요 (예: 대명사가 무엇을 지칭하는지 등).
문서에 없는 내용은 지어내지 말고, "제공된 지식베이스에는 관련 내용이 없습니다"라고 답변하세요.

[이전 대화 기록]
{history_text if history_text else "없음"}

[관련 지식 문서 ({len(results[:10])}개)]
{context_text}

[현재 질문]
{query}
"""
        try:
            answer_model = genai.GenerativeModel('gemini-2.5-flash')
            answer_res = answer_model.generate_content(final_prompt)
            answer_text = answer_res.text
        except Exception as e:
            answer_text = f"답변 생성 중 오류가 발생했습니다: {e}"
            
        # Citation 구성
        citations = []
        for r in results[:5]: # 상위 5개만 근거로 표시
            date_str = r.metadata.get('published_at', '')[:10] if r.metadata.get('published_at') else None
            citations.append(Citation(
                source_type=r.source_type,
                source_id=r.insight_id,
                title=r.title,
                excerpt=r.content_snippet,
                url=r.metadata.get('video_url'),
                date=date_str
            ))
            
        processing_time = int((time.time() - start_time) * 1000)
        
        # 로그 기록
        log_search(self.db_path, {
            "user_id": self.user_id,
            "query": query,
            "query_type": analysis_data.get('query_type'),
            "search_strategies": analysis_data.get('search_strategies'),
            "search_queries": [query],
            "retrieved_docs": [{"id": r.insight_id, "score": r.score} for r in results],
            "reranked_docs": [{"id": r.insight_id, "score": r.score} for r in results[:10]],
            "retrieval_steps": 1,
            "final_sources": [c.source_id for c in citations],
            "final_answer": answer_text,
            "confidence": "high",
            "processing_time_ms": processing_time
        })
        
        return AgentResponse(
            answer=answer_text,
            citations=citations,
            retrieval_log=retrieval_log,
            confidence="high",
            processing_time_ms=processing_time
        )
