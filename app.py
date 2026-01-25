"""
Insight Pipeline - YouTube 영상 심층 분석 애플리케이션
YouTube 영상의 자막을 추출하고 Google Gemini AI를 활용하여 지식을 추출합니다.
"""

import re
import json
import sqlite3
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi

# YouTube API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# ============================================================
# 페이지 설정 (가장 먼저 호출되어야 함)
# ============================================================
st.set_page_config(
    page_title="Insight Pipeline",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# 커스텀 CSS
# ============================================================
st.markdown("""
<style>
    /* 사이드바 버튼 텍스트 ellipsis */
    section[data-testid="stSidebar"] button p {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    /* 제목 버튼 (st-key-view_) - 왼쪽 정렬 */
    [class*="st-key-view_"] button {
        justify-content: flex-start !important;
    }
    [class*="st-key-view_"] button div {
        justify-content: flex-start !important;
    }
    /* 삭제 버튼 (st-key-del_) - 가운데 정렬 */
    [class*="st-key-del_"] button {
        justify-content: center !important;
    }
    /* 영상 카드 그리드 - 제목 2줄 제한 */
    .video-title {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        min-height: 2.8em;
        line-height: 1.4em;
        font-weight: 600;
        font-size: 14px;
    }
    .video-channel {
        font-size: 12px;
        color: #666;
        margin-top: 4px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 경로 설정
# ============================================================
BASE_PATH = Path(__file__).parent
DB_PATH = BASE_PATH / "insights.db"
CLIENT_SECRET_PATH = BASE_PATH / "client_secret.json"
TOKEN_PATH = BASE_PATH / "token.json"

# OAuth 스코프
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']


# ============================================================
# 데이터베이스 함수
# ============================================================
def init_database():
    """데이터베이스와 테이블을 초기화합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            video_url TEXT NOT NULL,
            title TEXT,
            transcript TEXT,
            analysis_result TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE insights ADD COLUMN title TEXT")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_video_id ON insights(video_id)
    """)
    
    conn.commit()
    conn.close()


def save_insight(video_id: str, video_url: str, title: str, transcript: str, analysis_result: str):
    """분석 결과를 데이터베이스에 저장합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO insights (video_id, video_url, title, transcript, analysis_result)
        VALUES (?, ?, ?, ?, ?)
    """, (video_id, video_url, title, transcript, analysis_result))
    
    conn.commit()
    conn.close()


def get_all_insights():
    """저장된 모든 분석 결과를 조회합니다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, video_id, video_url, title, analysis_result, created_at
        FROM insights
        ORDER BY created_at DESC
    """)
    
    results = cursor.fetchall()
    conn.close()
    return results


def get_insight_by_id(insight_id: int):
    """특정 ID의 분석 결과를 조회합니다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM insights WHERE id = ?
    """, (insight_id,))
    
    result = cursor.fetchone()
    conn.close()
    return result


def delete_insight(insight_id: int):
    """특정 분석 결과를 삭제합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
    
    conn.commit()
    conn.close()


# ============================================================
# YouTube OAuth 함수
# ============================================================
def get_oauth_flow():
    """OAuth Flow 객체를 생성합니다."""
    if not CLIENT_SECRET_PATH.exists():
        return None
    
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri='http://localhost:8501'
    )
    return flow


def get_youtube_client():
    """인증된 YouTube API 클라이언트를 반환합니다."""
    if not TOKEN_PATH.exists():
        return None
    
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds and creds.valid:
            return build('youtube', 'v3', credentials=creds)
    except Exception:
        pass
    
    return None


def save_credentials(creds):
    """인증 정보를 파일에 저장합니다."""
    with open(TOKEN_PATH, 'w') as f:
        f.write(creds.to_json())


def get_subscriptions(youtube):
    """구독 채널 목록을 가져옵니다."""
    subscriptions = []
    next_page_token = None
    
    while True:
        request = youtube.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        
        for item in response.get('items', []):
            subscriptions.append({
                'channel_id': item['snippet']['resourceId']['channelId'],
                'channel_title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails'].get('default', {}).get('url', '')
            })
        
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    
    return subscriptions


def get_recent_videos(youtube, channel_id: str, days: int = 3):
    """
    채널의 최근 N일 영상을 가져옵니다.
    playlistItems.list (1유닛) 사용으로 API 할당량 최적화
    쇼츠(60초 이하) 영상은 제외됩니다.
    """
    try:
        # 1. 채널의 uploads playlist ID 가져오기 (channels.list = 1유닛)
        channel_request = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        )
        channel_response = channel_request.execute()
        
        if not channel_response.get('items'):
            return []
        
        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # 2. uploads playlist에서 최근 영상 가져오기 (playlistItems.list = 1유닛)
        playlist_request = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=10  # 채널당 최근 10개 (쇼츠 필터링 후 5개 정도)
        )
        playlist_response = playlist_request.execute()
        
        # 3. N일 이내 영상만 필터링
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        candidate_videos = []
        
        for item in playlist_response.get('items', []):
            published_at = item['snippet']['publishedAt']
            video_date = datetime.fromisoformat(published_at.replace('Z', '+00:00')).replace(tzinfo=None)
            
            if video_date >= cutoff_date:
                title = item['snippet']['title']
                # 제목에 #shorts 있으면 바로 제외
                if '#shorts' in title.lower() or '#short' in title.lower():
                    continue
                
                candidate_videos.append({
                    'video_id': item['snippet']['resourceId']['videoId'],
                    'title': title,
                    'channel_title': item['snippet']['channelTitle'],
                    'thumbnail': item['snippet']['thumbnails'].get('high', {}).get('url', 
                                item['snippet']['thumbnails'].get('medium', {}).get('url', '')),
                    'published_at': published_at
                })
        
        # 4. 영상 길이로 쇼츠 필터링 (videos.list = 1유닛)
        if candidate_videos:
            video_ids = [v['video_id'] for v in candidate_videos]
            videos_request = youtube.videos().list(
                part="contentDetails",
                id=','.join(video_ids)
            )
            videos_response = videos_request.execute()
            
            # 영상 길이 파싱 (PT1M30S 형식)
            duration_map = {}
            for item in videos_response.get('items', []):
                duration_str = item['contentDetails']['duration']
                # 간단한 파싱: PT로 시작, H/M/S 포함
                seconds = 0
                import re
                hours = re.search(r'(\d+)H', duration_str)
                minutes = re.search(r'(\d+)M', duration_str)
                secs = re.search(r'(\d+)S', duration_str)
                if hours:
                    seconds += int(hours.group(1)) * 3600
                if minutes:
                    seconds += int(minutes.group(1)) * 60
                if secs:
                    seconds += int(secs.group(1))
                duration_map[item['id']] = seconds
            
            # 60초 이하 영상(쇼츠) 제외
            videos = [v for v in candidate_videos if duration_map.get(v['video_id'], 0) > 60]
            return videos
        
        return []
    except Exception as e:
        return []


# ============================================================
# 시스템 프롬프트 정의
# ============================================================
SYSTEM_INSTRUCTION = """
당신은 복잡한 콘텐츠에서 **핵심 메시지**를 추출하고 **충분히 상세하게** 정리하는 전문가입니다.

[핵심 원칙]
- 서론, 인사말 없이 즉시 본론 진입
- 형식은 완전히 자유롭게, 콘텐츠에 가장 적합한 구조로 정리
- 중요한 내용은 빠뜨리지 말고 충분히 설명
- 스크립트가 길면 정리도 그에 비례해서 상세하게 작성
- 마지막에 핵심 메시지를 한 문장으로 요약
- **비핵심 내용은 완전히 제외** (오프닝 인사, 구독/좋아요 요청, 광고, 마무리 인사 등)

[Output Format]
반드시 아래 JSON 형식으로만 응답:

```json
{
  "title": "핵심을 담은 제목 (15자 이내)",
  "analysis": "분석 내용 (마크다운, 자유 형식)"
}
```

- 언어: 한국어(Korean)
"""


# ============================================================
# 분석 함수
# ============================================================
def extract_video_id(url: str) -> str | None:
    """YouTube URL에서 Video ID를 추출합니다."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_transcript(video_id: str) -> str:
    """YouTube 영상에서 자막을 추출합니다."""
    try:
        ytt_api = YouTubeTranscriptApi()
        
        # 사용 가능한 자막 목록 가져오기
        transcript_list = ytt_api.list(video_id)
        
        # 우선순위: 한국어 수동 → 영어 수동 → 한국어 자동생성 → 영어 자동생성 → 아무거나
        selected_transcript = None
        
        # 1. 수동 생성 자막 먼저 시도
        for transcript in transcript_list:
            if not transcript.is_generated:
                if transcript.language_code in ['ko', 'ko-KR']:
                    selected_transcript = transcript
                    break
                elif transcript.language_code in ['en', 'en-US'] and not selected_transcript:
                    selected_transcript = transcript
        
        # 2. 자동 생성 자막 시도
        if not selected_transcript:
            for transcript in transcript_list:
                if transcript.is_generated:
                    if transcript.language_code in ['ko', 'ko-KR']:
                        selected_transcript = transcript
                        break
                    elif transcript.language_code in ['en', 'en-US'] and not selected_transcript:
                        selected_transcript = transcript
        
        # 3. 그래도 없으면 첫 번째 자막
        if not selected_transcript:
            for transcript in transcript_list:
                selected_transcript = transcript
                break
        
        if selected_transcript:
            fetched = selected_transcript.fetch()
            full_text = " ".join([entry.text for entry in fetched])
            return full_text
        else:
            raise Exception("사용 가능한 자막이 없습니다.")
        
    except Exception as e:
        raise Exception(f"자막 추출 중 오류 발생: {str(e)}")


def analyze_with_gemini(transcript: str, api_key: str) -> tuple[str, str]:
    """Gemini를 사용하여 자막 텍스트를 분석합니다."""
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config=genai.GenerationConfig(
            temperature=0,
            top_p=0.95,
            max_output_tokens=8192,
        ),
        system_instruction=SYSTEM_INSTRUCTION
    )
    
    prompt = f"다음 YouTube 영상 자막을 분석해주세요:\n\n{transcript}"
    response = model.generate_content(prompt)
    
    try:
        response_text = response.text.strip()
        print(f"[DEBUG] Gemini response (first 500 chars): {response_text[:500]}")
        
        json_str = None
        
        # 1. ```json ... ``` 형식 찾기
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        
        # 2. ``` ... ``` 형식 (언어 없이)
        if not json_str and '```' in response_text:
            code_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
            if code_match:
                json_str = code_match.group(1).strip()
        
        # 3. 중괄호로 시작하면 직접 JSON으로 시도
        if not json_str and response_text.startswith('{'):
            json_str = response_text
        
        # 4. 중괄호가 어딘가에 있으면 추출 시도
        if not json_str:
            brace_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)
        
        if json_str:
            result = json.loads(json_str, strict=False)
            title = result.get('title', '제목 없음')
            analysis = result.get('analysis', response_text)
            print(f"[DEBUG] Parsed title: {title}")
            return title, analysis
        else:
            return "분석 완료", response_text
            
    except Exception as e:
        print(f"[DEBUG] JSON parsing error: {e}")
        # 마지막 시도: 중괄호 찾아서 파싱
        try:
            brace_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if brace_match:
                result = json.loads(brace_match.group(0), strict=False)
                return result.get('title', '제목 없음'), result.get('analysis', response.text)
        except:
            pass
        return "분석 완료", response.text


def analyze_video(video_id: str, api_key: str) -> tuple[str, str]:
    """영상을 분석하고 결과를 반환합니다."""
    transcript = get_transcript(video_id)
    title, analysis = analyze_with_gemini(transcript, api_key)
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    save_insight(video_id, video_url, title, transcript, analysis)
    return title, analysis


# ============================================================
# 메인 함수
# ============================================================
def main():
    """메인 애플리케이션 로직"""
    init_database()
    
    # URL 파라미터에서 OAuth 콜백 처리
    query_params = st.query_params
    if 'code' in query_params:
        flow = get_oauth_flow()
        if flow:
            try:
                flow.fetch_token(code=query_params['code'])
                save_credentials(flow.credentials)
                st.query_params.clear()
                st.rerun()
            except Exception as e:
                st.error(f"인증 오류: {str(e)}")
    
    # ============================================================
    # 사이드바
    # ============================================================
    with st.sidebar:
        st.header("⚙️ 설정")
        st.markdown("---")
        
        api_key = st.text_input(
            "🔑 Google API Key",
            type="password",
            placeholder="AIza...",
            help="Google AI Studio에서 발급받은 API Key를 입력하세요."
        )
        
        if api_key:
            st.session_state['api_key'] = api_key
            st.success("✅ API Key 설정됨")
        
        st.markdown("---")
        
        # 저장된 분석 목록
        col_header, col_refresh = st.columns([5, 1])
        with col_header:
            st.header("📚 저장된 분석")
        with col_refresh:
            st.markdown("<br>", unsafe_allow_html=True)  # 정렬용
            if st.button("🔄", key="refresh_insights", help="분석 목록 새로고침"):
                st.rerun()
        
        insights = get_all_insights()
        
        if insights:
            # 페이지네이션: 기본 10개, 더보기 클릭 시 전체
            SHOW_COUNT = 10  # 기본 표시 개수 (조정 가능)
            show_all = st.session_state.get('show_all_insights', False)
            
            display_insights = insights if show_all else insights[:SHOW_COUNT]
            
            for insight in display_insights:
                col1, col2 = st.columns([5, 1])
                with col1:
                    title = insight['title'] if insight['title'] else f"영상 {insight['video_id'][:8]}..."
                    if st.button(f"📄 {title}", key=f"view_{insight['id']}", use_container_width=True):
                        st.session_state['selected_insight_id'] = insight['id']
                        st.rerun()
                with col2:
                    if st.button("🗑️", key=f"del_{insight['id']}"):
                        delete_insight(insight['id'])
                        st.rerun()
            
            # 더보기/접기 버튼
            if len(insights) > SHOW_COUNT:
                if show_all:
                    if st.button("📁 접기", key="collapse_insights", use_container_width=True):
                        st.session_state['show_all_insights'] = False
                        st.rerun()
                else:
                    remaining = len(insights) - SHOW_COUNT
                    if st.button(f"📂 더보기 (+{remaining}개)", key="expand_insights", use_container_width=True):
                        st.session_state['show_all_insights'] = True
                        st.rerun()
        else:
            st.caption("저장된 분석이 없습니다.")
        
        st.markdown("---")
        st.caption("Powered by Google Gemini 2.0 Flash")
    
    # ============================================================
    # 메인 화면
    # ============================================================
    st.title("🔍 Insight Pipeline")
    st.markdown("*YouTube 영상을 심층 분석하여 핵심 지식을 추출합니다.*")
    
    # 저장된 분석 보기 모드
    if 'selected_insight_id' in st.session_state:
        insight = get_insight_by_id(st.session_state['selected_insight_id'])
        
        if insight:
            title = insight['title'] if insight['title'] else "분석 결과"
            
            # 상단: 제목 + 썸네일 (비율 조정: [2, 1] = 큰 썸네일, [3, 1] = 작은 썸네일)
            col_title, col_thumb = st.columns([2, 1])
            with col_title:
                st.subheader(f"📊 {title}")
                st.caption(f"Video ID: {insight['video_id']} | 생성일: {insight['created_at']}")
                st.markdown(f"🔗 [YouTube 링크]({insight['video_url']})")
            with col_thumb:
                # YouTube 썸네일 자동 생성 (video_id로 URL 생성)
                thumbnail_url = f"https://img.youtube.com/vi/{insight['video_id']}/hqdefault.jpg"
                st.image(thumbnail_url, use_container_width=True)
            
            st.markdown("---")
            st.markdown(insight['analysis_result'])
            
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="📄 Markdown으로 다운로드",
                    data=insight['analysis_result'],
                    file_name=f"insight_{insight['video_id']}.md",
                    mime="text/markdown"
                )
            with col2:
                if st.button("🔙 돌아가기"):
                    del st.session_state['selected_insight_id']
                    st.rerun()
            return
    
    # 탭 구성
    tab1, tab2 = st.tabs(["🔗 URL 분석", "📺 구독 피드"])
    
    # ============================================================
    # 탭 1: URL 직접 입력 분석
    # ============================================================
    with tab1:
        st.markdown("---")
        col1, col2 = st.columns([4, 1])
        
        with col1:
            youtube_url = st.text_input(
                "📺 YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
                label_visibility="collapsed"
            )
        
        with col2:
            analyze_button = st.button("🚀 분석 시작", use_container_width=True)
        
        if analyze_button:
            if 'api_key' not in st.session_state or not st.session_state['api_key']:
                st.error("❌ 먼저 사이드바에서 Google API Key를 입력해주세요.")
                return
            
            if not youtube_url:
                st.error("❌ YouTube URL을 입력해주세요.")
                return
            
            video_id = extract_video_id(youtube_url)
            if not video_id:
                st.error("❌ 올바른 YouTube URL 형식이 아닙니다.")
                return
            
            try:
                with st.spinner("📥 자막 추출 중..."):
                    transcript = get_transcript(video_id)
                
                with st.expander("📝 추출된 자막 보기", expanded=False):
                    st.text_area(
                        "자막 원문",
                        value=transcript[:3000] + ("..." if len(transcript) > 3000 else ""),
                        height=200,
                        disabled=True
                    )
                
                with st.spinner("🤖 AI 분석 중..."):
                    title, analysis_result = analyze_with_gemini(
                        transcript, 
                        st.session_state['api_key']
                    )
                
                save_insight(video_id, youtube_url, title, transcript, analysis_result)
                st.success(f"✅ '{title}' 저장 완료!")
                
                st.markdown("---")
                st.subheader(f"📊 {title}")
                
                # JSON이 raw로 반환된 경우 한 번 더 파싱 시도
                display_result = analysis_result
                if analysis_result.strip().startswith('{'):
                    try:
                        parsed = json.loads(analysis_result)
                        if 'analysis' in parsed:
                            display_result = parsed['analysis']
                    except:
                        pass
                
                st.markdown(display_result)
                
                st.download_button(
                    label="📄 Markdown으로 다운로드",
                    data=analysis_result,
                    file_name=f"insight_{video_id}.md",
                    mime="text/markdown"
                )
                
            except Exception as e:
                st.error(f"❌ 오류: {str(e)}")
    
    # ============================================================
    # 탭 2: 구독 피드
    # ============================================================
    with tab2:
        st.markdown("---")
        
        youtube = get_youtube_client()
        
        if youtube is None:
            # 로그인 필요
            st.info("🔐 구독 채널의 영상을 보려면 YouTube 로그인이 필요합니다.")
            
            if not CLIENT_SECRET_PATH.exists():
                st.error("❌ client_secret.json 파일이 없습니다.")
            else:
                flow = get_oauth_flow()
                if flow:
                    auth_url, _ = flow.authorization_url(prompt='consent')
                    st.markdown(f"[🔗 Google 계정으로 로그인]({auth_url})")
        else:
            # 로그인 완료 - 구독 채널 영상 표시
            st.success("✅ YouTube 연결됨")
            
            if st.button("🔄 새로고침"):
                if 'subscription_videos' in st.session_state:
                    del st.session_state['subscription_videos']
                st.rerun()
            
            # 구독 채널 영상 캐싱
            if 'subscription_videos' not in st.session_state:
                with st.spinner("📡 구독 채널 영상을 불러오는 중... (처음에는 시간이 걸릴 수 있습니다)"):
                    try:
                        subscriptions = get_subscriptions(youtube)
                        all_videos = []
                        
                        progress_bar = st.progress(0)
                        for i, sub in enumerate(subscriptions):
                            videos = get_recent_videos(youtube, sub['channel_id'], days=3)
                            all_videos.extend(videos)
                            progress_bar.progress((i + 1) / len(subscriptions))
                        
                        progress_bar.empty()
                        
                        # 날짜순 정렬
                        all_videos.sort(key=lambda x: x['published_at'], reverse=True)
                        st.session_state['subscription_videos'] = all_videos
                        
                    except Exception as e:
                        error_msg = str(e)
                        if 'quotaExceeded' in error_msg or 'quota' in error_msg.lower():
                            st.error("❌ API 할당량이 소진되었습니다. 내일 다시 시도해주세요.")
                        else:
                            st.error(f"❌ 오류: {error_msg}")
                        st.session_state.pop('subscription_videos', None)
            
            # 영상 그리드 표시
            if 'subscription_videos' in st.session_state:
                videos = st.session_state['subscription_videos']
                
                if not videos:
                    st.info("📭 최근 3일 내 업로드된 영상이 없습니다.")
                else:
                    st.markdown(f"**최근 3일 영상: {len(videos)}개**")
                    
                    # 3열 그리드
                    cols = st.columns(3)
                    
                    for i, video in enumerate(videos):
                        with cols[i % 3]:
                            st.image(video['thumbnail'], use_container_width=True)
                            # 제목 2줄 제한 (CSS clamp)
                            st.markdown(f'<div class="video-title">{video["title"]}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="video-channel">📺 {video["channel_title"]}</div>', unsafe_allow_html=True)
                            
                            if st.button("🔍 분석", key=f"analyze_{video['video_id']}"):
                                if 'api_key' not in st.session_state or not st.session_state['api_key']:
                                    st.toast("❌ API Key를 먼저 입력하세요.", icon="⚠️")
                                else:
                                    # 백그라운드에서 분석 실행
                                    def run_analysis(vid, api_key):
                                        try:
                                            analyze_video(vid, api_key)
                                        except Exception:
                                            pass
                                    
                                    thread = threading.Thread(
                                        target=run_analysis,
                                        args=(video['video_id'], st.session_state['api_key'])
                                    )
                                    thread.start()
                                    st.toast(f"📝 '{video['title'][:20]}...' 분석 시작!", icon="🚀")
                            
                            st.markdown("---")


if __name__ == "__main__":
    main()
