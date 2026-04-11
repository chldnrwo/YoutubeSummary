# YouTube 자막 소프트밴 방지 — Webshare 프록시 연동

**날짜**: 2026-04-11

## 문제

`youtube-transcript-api` 라이브러리로 자막을 반복 수집하면 YouTube가 IP를 감지하여 소프트 밴(요청 차단)을 걸어버리는 문제가 있었음. 이 라이브러리는 비공식 YouTube 내부 엔드포인트를 사용하기 때문에 자동화 대량 요청에 취약함.

## 해결 방법

**Webshare Rotating Residential Proxy** 도입 — 매 요청마다 전 세계 8천만 개 가정용 IP 중 하나로 자동 변경하여 YouTube가 봇 탐지를 못하게 함.

## 변경 파일

### 1. config.json

Webshare 프록시 인증 정보 추가:

```diff
 {
-    "GOOGLE_API_KEY": "..."
+    "GOOGLE_API_KEY": "...",
+    "WEBSHARE_PROXY": {
+        "enabled": true,
+        "username": "vduxpbne",
+        "password": "od9zlc1ycwht"
+    }
 }
```

- `enabled`: true/false로 프록시 사용 여부 토글 가능
- `username`, `password`: Webshare 대시보드 Proxy Settings에서 확인 가능

---

### 2. app.py

#### Import 추가
```diff
 from youtube_transcript_api import YouTubeTranscriptApi
+from youtube_transcript_api.proxies import WebshareProxyConfig
```

#### 신규 헬퍼 함수

| 함수 | 역할 |
| :--- | :--- |
| `_get_proxy_config()` | config.json에서 프록시 설정을 읽어 `WebshareProxyConfig` 객체 반환 |
| `_get_cached_transcript()` | DB에 이미 저장된 자막이 있으면 재요청 없이 캐시 반환 |
| 글로벌 쓰로틀링 변수 | 요청 간 최소 간격을 보장하는 타이머 |

#### `get_transcript()` 함수 리팩토링

기존 단순 요청 → **4단계 방어 체계**로 변경:

```
get_transcript(video_id)
  │
  ├─ 1단계: DB 캐시 확인 (이미 자막 있으면 재요청 안 함)
  │
  ├─ 2단계: 쓰로틀링 (이전 요청 대비 2~5초 랜덤 딜레이)
  │
  ├─ 3단계: Webshare 프록시로 YouTube 요청
  │
  └─ 4단계: 실패 시 지수 백오프 재시도 (최대 3회)
```

## 동작 원리

```
[기존] 내 컴퓨터 ──────────────→ YouTube  →  밴 ❌

[현재] 내 컴퓨터 → Webshare → (매번 다른 IP로 변장) → YouTube → 자막 ✅
```

## Webshare 요금

| 항목 | 내용 |
| :--- | :--- |
| **플랜** | Rotating Residential 1GB |
| **월 비용** | $3.50 |
| **처리 가능량** | 자막 1건당 ~10-50KB → 약 2만 건 이상/월 |

## 참고

- **YouTube Data API** (구독 목록 조회)는 공식 API이므로 프록시 불필요. 일일 10,000 유닛 쿼터 제한 (개인 사용 시 충분)
- 프록시를 끄고 싶으면 config.json에서 `"enabled": false`로 변경
