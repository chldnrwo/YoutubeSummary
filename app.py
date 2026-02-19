"""
Insight Pipeline - YouTube 영상 심층 분석 애플리케이션
YouTube 영상의 자막을 추출하고 Google Gemini AI를 활용하여 지식을 추출합니다.
"""

import re
import json
import sqlite3
import os
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi

# YouTube API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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
CONFIG_PATH = BASE_PATH / "config.json"

# OAuth 스코프
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']

# ============================================================
# 병렬 분석 관리 (글로벌)
# ============================================================
_analysis_executor = ThreadPoolExecutor(max_workers=3)
_analysis_status = {}  # {video_id: 'queued'|'running'|'done'|'error'}
_analysis_lock = threading.Lock()

# 주식 스케줄러 (글로벌)
_stock_scheduler = None
_stock_fetch_status = {}  # {symbol: {'status': str, 'message': str, 'updated_at': str}}
_stock_fetch_lock = threading.Lock()


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
    
    # 주식 종목 마스터 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            market TEXT DEFAULT 'KRX',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
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
# 주식 데이터 DB 함수
# ============================================================
def get_or_create_stock(symbol: str, name: str) -> int:
    """종목 코드로 stocks 테이블 조회/생성 후 ID 반환."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM stocks WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    
    if row:
        stock_id = row[0]
    else:
        cursor.execute(
            "INSERT INTO stocks (symbol, name) VALUES (?, ?)",
            (symbol, name)
        )
        conn.commit()
        stock_id = cursor.lastrowid
    
    conn.close()
    return stock_id


def save_daily_prices_bulk(stock_id: int, records: list):
    """일별 시세 데이터를 벌크로 저장합니다. 중복은 무시합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.executemany("""
        INSERT OR IGNORE INTO daily_prices
        (stock_id, date, open_price, high_price, low_price, close_price, volume, market_cap)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [(stock_id, r['date'], r['open'], r['high'], r['low'], r['close'], r['volume'], r.get('market_cap')) for r in records])
    
    conn.commit()
    inserted = cursor.rowcount
    conn.close()
    return inserted


def get_watched_stocks():
    """등록된 관심 종목 목록을 조회합니다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT s.id, s.symbol, s.name, s.market, s.created_at,
               MAX(dp.date) as last_date,
               COUNT(dp.id) as data_count
        FROM stocks s
        LEFT JOIN daily_prices dp ON s.id = dp.stock_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """)
    
    results = cursor.fetchall()
    conn.close()
    return results


def get_daily_prices(stock_id: int, limit: int = 60):
    """종목의 일별 시세를 최신순으로 조회합니다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, open_price, high_price, low_price, close_price, volume, market_cap
        FROM daily_prices
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (stock_id, limit))
    
    results = cursor.fetchall()
    conn.close()
    return results


def delete_stock(stock_id: int):
    """종목과 관련 시세 데이터를 삭제합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM daily_prices WHERE stock_id = ?", (stock_id,))
    cursor.execute("DELETE FROM stocks WHERE id = ?", (stock_id,))
    
    conn.commit()
    conn.close()


# ============================================================
# KRX 종목 목록 (자동완성 검색용)
# ============================================================
_krx_stock_list: list[dict] | None = None


def load_krx_stock_list() -> list[dict]:
    """KRX 상장법인 목록을 다운로드하여 캐시합니다."""
    global _krx_stock_list
    if _krx_stock_list is not None:
        return _krx_stock_list
    
    try:
        url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        text = resp.text
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
        
        stocks = []
        for tr in trs:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
            if len(cells) >= 3 and re.match(r'^[0-9A-Z]{6}$', cells[2]):
                stocks.append({
                    'name': cells[0],
                    'market': cells[1],
                    'symbol': cells[2],
                })
        
        _krx_stock_list = stocks
        print(f"[KRX] 종목 목록 로드 완료: {len(stocks)}개")
        return stocks
    except Exception as e:
        print(f"[ERROR] KRX 종목 목록 로드 실패: {e}")
        return []


def search_stocks(query: str, limit: int = 0) -> list[dict]:
    """종목명 또는 종목코드로 검색합니다."""
    if not query or len(query) < 1:
        return []
    
    stocks = load_krx_stock_list()
    query_lower = query.lower()
    
    results = []
    for s in stocks:
        if query_lower in s['name'].lower() or query_lower in s['symbol']:
            results.append(s)
            if limit > 0 and len(results) >= limit:
                break
    
    return results


# ============================================================
# 네이버 금융 데이터 수집 함수
# ============================================================
def fetch_naver_stock_name(symbol: str) -> str | None:
    """네이버 금융에서 종목명을 가져옵니다."""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        # title 형식: "삼성전자 : Npay 증권" 또는 "삼성전자 : 네이버 금융"
        match = re.search(r'<title>\s*(.+?)\s*:\s*(?:Npay|네이버)', resp.text)
        if match:
            return match.group(1).strip()
        return None
    except Exception:
        return None


def fetch_naver_daily_prices(symbol: str, page: int = 1) -> list:
    """
    네이버 금융 일별 시세 페이지에서 OHLCV 데이터를 가져옵니다.
    Returns: [{'date': 'YYYY-MM-DD', 'open': int, 'high': int, 'low': int, 'close': int, 'volume': int}, ...]
    """
    try:
        url = f"https://finance.naver.com/item/sise_day.naver?code={symbol}&page={page}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        text = resp.text
        records = []
        
        # 날짜 위치를 기준으로 텍스트를 행 단위로 분할
        date_matches = list(re.finditer(r'\d{4}\.\d{2}\.\d{2}', text))
        
        for i, dm in enumerate(date_matches):
            date_str = dm.group()
            # 이 날짜부터 다음 날짜(또는 끝)까지의 텍스트를 한 행으로 취급
            start = dm.start()
            end = date_matches[i + 1].start() if i + 1 < len(date_matches) else start + 600
            chunk = text[start:end]
            
            # 이 행 내 태그 사이의 텍스트 중 순수 숫자(콤마 포함)만 필터
            all_between = re.findall(r'>([^<]+)<', chunk)
            nums = [s.strip() for s in all_between if s.strip() and re.match(r'^[\d,]+$', s.strip())]
            
            # 순서: [0]=종가, [1]=전일비(스킵), [2]=시가, [3]=고가, [4]=저가, [5]=거래량
            if len(nums) >= 6:
                records.append({
                    'date': date_str.replace('.', '-'),
                    'close': int(nums[0].replace(',', '')),
                    'open': int(nums[2].replace(',', '')),
                    'high': int(nums[3].replace(',', '')),
                    'low': int(nums[4].replace(',', '')),
                    'volume': int(nums[5].replace(',', '')),
                })
        
        return records
    except Exception as e:
        print(f"[ERROR] 네이버 시세 수집 실패 ({symbol}, page={page}): {e}")
        return []


def fetch_naver_market_cap(symbol: str) -> int | None:
    """네이버 금융에서 현재 시가총액을 가져옵니다."""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        # 시가총액 주변에서 숫자 추출 (억원 단위)
        idx = resp.text.find('시가총액')
        if idx >= 0:
            context = resp.text[idx:idx+300]
            # td 또는 em 내 콤마 포함 숫자 찾기
            nums = re.findall(r'([\d,]{4,})', context)
            if nums:
                cap_str = nums[0].replace(',', '')
                return int(cap_str) * 100_000_000  # 억원 -> 원
        return None
    except Exception:
        return None


def fetch_stock_data(symbol: str, pages: int = 25) -> tuple[str | None, list]:
    """
    종목의 일별 시세 데이터를 수집합니다.
    Returns: (종목명, [시세 레코드 리스트])
    """
    name = fetch_naver_stock_name(symbol)
    if not name:
        return None, []
    
    all_records = []
    for page in range(1, pages + 1):
        records = fetch_naver_daily_prices(symbol, page)
        if not records:
            break
        all_records.extend(records)
        import time
        time.sleep(0.3)  # 요청 간격
    
    # 시가총액은 최신일 데이터에만 추가 (네이버는 현재 시총만 제공)
    market_cap = fetch_naver_market_cap(symbol)
    if all_records and market_cap:
        all_records[0]['market_cap'] = market_cap
    
    return name, all_records


def scheduled_fetch_all():
    """등록된 전 종목의 당일 데이터를 자동 수집합니다 (스케줄러용)."""
    print(f"[SCHEDULER] 자동 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    stocks = get_watched_stocks()
    
    for stock in stocks:
        symbol = stock['symbol']
        try:
            with _stock_fetch_lock:
                _stock_fetch_status[symbol] = {
                    'status': 'running',
                    'message': '수집 중...',
                    'updated_at': datetime.now().strftime('%H:%M:%S')
                }
            
            name, records = fetch_stock_data(symbol, pages=1)  # 최근 1페이지만
            if records:
                stock_id = get_or_create_stock(symbol, name or symbol)
                save_daily_prices_bulk(stock_id, records)
            
            with _stock_fetch_lock:
                _stock_fetch_status[symbol] = {
                    'status': 'done',
                    'message': f'{len(records)}건 수집 완료',
                    'updated_at': datetime.now().strftime('%H:%M:%S')
                }
        except Exception as e:
            with _stock_fetch_lock:
                _stock_fetch_status[symbol] = {
                    'status': 'error',
                    'message': str(e),
                    'updated_at': datetime.now().strftime('%H:%M:%S')
                }
        
        import time
        time.sleep(1)  # 종목 간 간격
    
    print(f"[SCHEDULER] 자동 수집 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def init_stock_scheduler():
    """주식 데이터 자동 수집 스케줄러를 초기화합니다."""
    global _stock_scheduler
    if _stock_scheduler is not None:
        return  # 이미 실행 중
    
    _stock_scheduler = BackgroundScheduler()
    _stock_scheduler.add_job(
        scheduled_fetch_all,
        trigger=CronTrigger(day_of_week='mon-fri', hour=18, minute=0),
        id='stock_daily_fetch',
        name='일별 주식 데이터 자동 수집',
        replace_existing=True
    )
    _stock_scheduler.start()
    print("[SCHEDULER] 주식 자동 수집 스케줄러 시작 (평일 18:00)")


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
        
        # 토큰이 만료되었지만 refresh_token이 있으면 자동 갱신
        if creds and not creds.valid and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            save_credentials(creds)
        
        if creds and creds.valid:
            return build('youtube', 'v3', credentials=creds)
    except Exception:
        # 갱신 실패 시 (refresh_token 만료 등) 토큰 파일 삭제 → 재로그인 유도
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
    
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
    쇼츠(120초 이하) 영상은 제외됩니다.
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
            maxResults=50  # 채널당 최근 50개 (쇼츠가 많을 경우 대비)
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
            
            # 120초 이하 영상(쇼츠) 제외
            videos = [v for v in candidate_videos if duration_map.get(v['video_id'], 0) > 120]
            return videos
        
        return []
    except Exception as e:
        return []


# ============================================================
# 시스템 프롬프트 정의
# ============================================================
SYSTEM_INSTRUCTION = """
당신은 콘텐츠의 숨겨진 맥락과 디테일을 완벽하게 파악하는 '심층 분석 에디터'입니다.
단순한 줄거리 요약이 아니라, **핵심 논리와 구체적인 정보가 담긴 '마스터 리포트'**를 작성하십시오.

[절대 어기면 안 되는 작성 원칙]
1. **'추상적인 요약' 금지**: "설명했다", "좋다고 했다"라고 뭉뚱그리지 말고, **"정확히 어떤 방법인지", "구체적인 수치나 예시(고유명사)"**를 명시하십시오.
2. **Key-Point 중심 재구성**: 영상의 시간 순서(타임라인)를 무시하고, **주제(Topic)별로 내용을 묶어서 논리적으로 재구성**하십시오.
3. **논리적 완결성**: [배경/문제] → [해결책/핵심주장] → [결과/의의]로 이어지는 흐름을 명확히 하십시오.
4. **전문적 어조**: "~해요" 같은 구어체 대신, 보고서나 기사 형식의 명료한 문체를 사용하십시오.

[Output Format]
반드시 아래 JSON 형식으로만 응답하십시오:

```
json
{
  "title": "내용을 관통하는 매력적인 제목",
  "analysis": "위 작성 원칙에 따라 재구성된 마크다운 포맷의 상세 리포트"
}
```

[상세 작성 가이드]

📌 핵심 한 줄 요약: 전체 콘텐츠가 전달하려는 궁극적인 메시지

1️⃣ [주제별 소제목]:

배경/상황: (무엇에 대한 이야기인가? 구체적 상황 묘사)

핵심 내용: (How & Why - 구체적인 방법론, 논리, 메커니즘 상세 서술)

주요 포인트: (고유명사, 수치, 핵심 키워드를 포함한 디테일)

💡 Deep Insight: 이 콘텐츠를 통해 얻을 수 있는 통찰이나 실생활 적용점

언어: 한국어(Korean)

스타일: 깊이 있는 매거진 기사 또는 전문 리포트 스타일
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


def submit_analysis(video_id: str, api_key: str):
    """영상 분석을 ThreadPoolExecutor에 제출합니다."""
    with _analysis_lock:
        # 이미 진행 중이거나 완료된 경우 스킵
        if video_id in _analysis_status:
            return
        _analysis_status[video_id] = 'queued'
    
    def _run():
        try:
            with _analysis_lock:
                _analysis_status[video_id] = 'running'
            analyze_video(video_id, api_key)
            with _analysis_lock:
                _analysis_status[video_id] = 'done'
        except Exception as e:
            with _analysis_lock:
                _analysis_status[video_id] = 'error'
            print(f"[ERROR] 분석 실패 ({video_id}): {e}")
    
    _analysis_executor.submit(_run)


def get_analysis_status(video_id: str) -> str | None:
    """영상의 분석 상태를 반환합니다."""
    with _analysis_lock:
        return _analysis_status.get(video_id)


def get_active_analysis_count() -> int:
    """현재 진행 중인 분석 수를 반환합니다."""
    with _analysis_lock:
        return sum(1 for s in _analysis_status.values() if s in ('queued', 'running'))


# ============================================================
# 메인 함수
# ============================================================
def main():
    """메인 애플리케이션 로직"""
    init_database()
    
    # 설정 파일 로드
    default_api_key = ""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                default_api_key = config.get("GOOGLE_API_KEY", "")
        except Exception:
            pass
    
    # 세션 상태에 API 키가 없으면 설정 파일 값 사용
    if 'api_key' not in st.session_state and default_api_key:
        st.session_state['api_key'] = default_api_key
    
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
            value=st.session_state.get('api_key', default_api_key),
            placeholder="AIza...",
            help="Google AI Studio에서 발급받은 API Key를 입력하세요. (config.json에서 자동 로드 가능)"
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
    
    # 주식 스케줄러 시작
    init_stock_scheduler()
    
    # 탭 구성
    tab1, tab2, tab3 = st.tabs(["🔗 URL 분석", "📺 구독 피드", "📈 주식 데이터"])
    
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
        
        # 조회 기간 선택
        col_period, _ = st.columns([1, 4])
        with col_period:
            days_map = {"3일": 3, "7일": 7, "14일": 14, "30일": 30}
            
            selected_label = st.selectbox(
                "📅 조회 기간",
                options=list(days_map.keys()),
                index=3,
                key="days_selector"
            )
            selected_days = days_map[selected_label]
        
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
            
            # 구독 채널 영상 캐싱 (항상 30일치 가져와서 표시 시 필터링)
            MAX_FETCH_DAYS = 30
            if 'subscription_videos' not in st.session_state:
                with st.spinner("📡 구독 채널 영상을 불러오는 중... (처음에는 시간이 걸릴 수 있습니다)"):
                    try:
                        subscriptions = get_subscriptions(youtube)
                        all_videos = []
                        
                        progress_bar = st.progress(0)
                        for i, sub in enumerate(subscriptions):
                            videos = get_recent_videos(youtube, sub['channel_id'], days=MAX_FETCH_DAYS)
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
            
            # 영상 그리드 표시 (선택한 기간으로 필터링)
            if 'subscription_videos' in st.session_state:
                all_cached_videos = st.session_state['subscription_videos']
                
                # 선택한 기간에 맞게 필터링
                cutoff = datetime.utcnow() - timedelta(days=selected_days)
                videos = [
                    v for v in all_cached_videos
                    if datetime.fromisoformat(v['published_at'].replace('Z', '+00:00')).replace(tzinfo=None) >= cutoff
                ]
                
                if not videos:
                    st.info(f"📭 최근 {selected_days}일 내 업로드된 영상이 없습니다.")
                else:
                    # 진행 중인 분석 상태 표시
                    active_count = get_active_analysis_count()
                    col_info, col_auto = st.columns([3, 1])
                    with col_info:
                        status_text = f"**최근 {selected_days}일 영상: {len(videos)}개**"
                        if active_count > 0:
                            status_text += f" &nbsp;|&nbsp; ⏳ 분석 진행 중: {active_count}개"
                        st.markdown(status_text, unsafe_allow_html=True)
                    with col_auto:
                        if active_count > 0:
                            if st.button("🔄 상태 갱신", key="refresh_status"):
                                st.rerun()
                    
                    # 3열 그리드
                    cols = st.columns(3)
                    
                    for i, video in enumerate(videos):
                        with cols[i % 3]:
                            vid = video['video_id']
                            status = get_analysis_status(vid)
                            
                            st.image(video['thumbnail'], use_container_width=True)
                            # 제목 2줄 제한 (CSS clamp)
                            st.markdown(f'<div class="video-title">{video["title"]}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="video-channel">📺 {video["channel_title"]}</div>', unsafe_allow_html=True)
                            
                            # 분석 상태에 따른 버튼 렌더링
                            if status == 'done':
                                st.success("✅ 분석 완료")
                            elif status in ('queued', 'running'):
                                st.info("⏳ 분석 중...")
                            elif status == 'error':
                                st.error("❌ 분석 실패")
                                if st.button("🔄 재시도", key=f"retry_{vid}"):
                                    with _analysis_lock:
                                        _analysis_status.pop(vid, None)
                                    submit_analysis(vid, st.session_state['api_key'])
                                    st.toast(f"📝 '{video['title'][:20]}...' 재시도!", icon="🔄")
                                    st.rerun()
                            else:
                                if st.button("🔍 분석", key=f"analyze_{vid}"):
                                    if 'api_key' not in st.session_state or not st.session_state['api_key']:
                                        st.toast("❌ API Key를 먼저 입력하세요.", icon="⚠️")
                                    else:
                                        submit_analysis(vid, st.session_state['api_key'])
                                        st.toast(f"📝 '{video['title'][:20]}...' 분석 대기열 추가!", icon="🚀")
                                        st.rerun()
                            
                            st.markdown("---")
    
    # ============================================================
    # 탭 3: 주식 데이터
    # ============================================================
    with tab3:
        st.markdown("---")
        
        # 종목 추가 영역
        st.subheader("➕ 종목 추가")
        
        search_query = st.text_input(
            "종목 검색",
            placeholder="종목명 또는 종목코드 입력 (예: 삼성전자, 005930)",
            label_visibility="collapsed",
            key="stock_search_input"
        )
        
        if search_query and len(search_query.strip()) >= 1:
            query = search_query.strip()
            
            # 6자리 숫자 직접 입력 시 바로 추가 가능
            if re.match(r'^\d{6}$', query):
                col_direct, col_btn = st.columns([4, 1])
                with col_direct:
                    st.info(f"🔢 종목코드 직접 입력: **{query}**")
                with col_btn:
                    if st.button("➕ 추가", key="add_direct_btn", use_container_width=True):
                        with st.spinner(f"🔍 {query} 종목 정보 확인 중..."):
                            name = fetch_naver_stock_name(query)
                            if name:
                                get_or_create_stock(query, name)
                                st.success(f"✅ {name} ({query}) 등록 완료!")
                                st.rerun()
                            else:
                                st.error(f"❌ 종목코드 {query}을 찾을 수 없습니다.")
            
            # 종목명 검색
            results = search_stocks(query)
            
            if results:
                for r in results:
                    col_info, col_add = st.columns([4, 1])
                    with col_info:
                        market_badge = "🟦 코스피" if r['market'] == "유가증권시장" else "🟩 코스닥"
                        st.markdown(f"**{r['name']}** ({r['symbol']}) {market_badge}")
                    with col_add:
                        if st.button("➕", key=f"add_{r['symbol']}", use_container_width=True):
                            get_or_create_stock(r['symbol'], r['name'])
                            st.success(f"✅ {r['name']} ({r['symbol']}) 등록 완료!")
                            st.rerun()
            elif not re.match(r'^\d{6}$', query):
                st.caption("🔍 검색 결과가 없습니다.")
        
        st.markdown("---")
        
        # 관심 종목 목록
        st.subheader("📋 관심 종목 목록")
        watched = get_watched_stocks()
        
        if not watched:
            st.info("📭 등록된 종목이 없습니다. 위에서 종목코드를 추가해주세요.")
        else:
            # 스케줄러 상태
            if _stock_scheduler and _stock_scheduler.running:
                next_run = _stock_scheduler.get_job('stock_daily_fetch')
                if next_run and next_run.next_run_time:
                    st.caption(f"⏰ 다음 자동 수집: {next_run.next_run_time.strftime('%Y-%m-%d %H:%M')} (평일 18:00)")
            
            for stock in watched:
                col_name, col_info, col_fetch, col_del = st.columns([3, 2, 1, 1])
                
                with col_name:
                    st.markdown(f"**{stock['name']}** (`{stock['symbol']}`)")
                with col_info:
                    last_date = stock['last_date'] or '-'
                    data_count = stock['data_count'] or 0
                    st.caption(f"최근: {last_date} | {data_count}건")
                with col_fetch:
                    if st.button("📥", key=f"fetch_{stock['id']}", help="수동 수집"):
                        with st.spinner(f"📥 {stock['name']} 데이터 수집 중..."):
                            name, records = fetch_stock_data(stock['symbol'], pages=25)
                            if records:
                                inserted = save_daily_prices_bulk(stock['id'], records)
                                st.toast(f"✅ {stock['name']}: {len(records)}건 수집 완료!", icon="📈")
                            else:
                                st.toast(f"⚠️ {stock['name']}: 수집된 데이터가 없습니다.", icon="⚠️")
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_stock_{stock['id']}", help="종목 삭제"):
                        delete_stock(stock['id'])
                        st.toast(f"🗑️ {stock['name']} 삭제 완료", icon="🗑️")
                        st.rerun()
        
        st.markdown("---")
        
        # 데이터 조회 영역
        st.subheader("📊 데이터 조회")
        
        if watched:
            stock_options = {f"{s['name']} ({s['symbol']})": s for s in watched}
            selected_stock_label = st.selectbox(
                "종목 선택",
                options=list(stock_options.keys()),
                key="stock_viewer_select"
            )
            
            if selected_stock_label:
                selected_stock = stock_options[selected_stock_label]
                
                col_limit, col_download = st.columns([1, 4])
                with col_limit:
                    show_count = st.selectbox("조회 수", [50, 100, 200, 9999], index=0, key="price_limit",
                                               format_func=lambda x: "전체" if x == 9999 else str(x))
                
                prices = get_daily_prices(selected_stock['id'], limit=show_count)
                
                if prices:
                    # 테이블 데이터 구성
                    table_data = []
                    for p in prices:
                        mc = p['market_cap']
                        mc_str = f"{mc:,.0f}" if mc else "-"
                        table_data.append({
                            "날짜": p['date'],
                            "시가": f"{p['open_price']:,.0f}",
                            "고가": f"{p['high_price']:,.0f}",
                            "저가": f"{p['low_price']:,.0f}",
                            "종가": f"{p['close_price']:,.0f}",
                            "거래량": f"{p['volume']:,}",
                            "시가총액": mc_str
                        })
                    
                    st.dataframe(table_data, use_container_width=True, hide_index=True)
                    
                    # CSV 다운로드
                    csv_lines = ["날짜,시가,고가,저가,종가,거래량,시가총액"]
                    for p in prices:
                        mc = p['market_cap'] if p['market_cap'] else ''
                        csv_lines.append(f"{p['date']},{p['open_price']},{p['high_price']},{p['low_price']},{p['close_price']},{p['volume']},{mc}")
                    csv_content = "\n".join(csv_lines)
                    
                    with col_download:
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.download_button(
                            label="📄 CSV 다운로드",
                            data=csv_content,
                            file_name=f"{selected_stock['symbol']}_prices.csv",
                            mime="text/csv",
                            key="csv_download"
                        )
                else:
                    st.info("📭 저장된 시세 데이터가 없습니다. 📥 버튼으로 데이터를 수집해주세요.")
        else:
            st.info("📭 종목을 먼저 추가해주세요.")


if __name__ == "__main__":
    main()
