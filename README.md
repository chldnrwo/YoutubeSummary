<div align="center">

# 🔍 Insight Pipeline

### YouTube 영상을 심층 분석하고, 나만의 AI 지식 베이스를 구축하세요.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.34+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Gemini](https://img.shields.io/badge/Google_Gemini-2.5-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-00A67E?style=for-the-badge)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-Private-lightgrey?style=for-the-badge)]()

<br />

**Insight Pipeline**은 YouTube 구독 채널의 영상을 **Google Gemini AI**로 자동 분석하고,  
분석된 지식을 **벡터 DB 기반 RAG 챗봇**으로 검색·질의할 수 있는 **개인 AI 지식 관리 시스템**입니다.

<br />

[주요 기능](#-주요-기능) · [기술 스택](#-기술-스택) · [시작하기](#-시작하기) · [아키텍처](#-아키텍처) · [배포](#-배포)

</div>

---

<br />

## ✨ 주요 기능

### 📺 YouTube 영상 심층 분석
> 구독 채널의 최신 영상을 한 번의 클릭으로 AI가 분석합니다.

- **Google OAuth 2.0** 로그인으로 구독 채널 자동 연동
- 구독 채널의 **최근 영상을 카드 그리드 UI**로 탐색
- 영상 자막을 자동 추출 (한국어/영어 우선, Webshare 프록시 지원)
- **Gemini 2.5 Flash/Lite**로 핵심 인사이트·요약·키워드 추출
- 자막 길이에 따른 **자동 모델 선택** (비용 최적화)
- **병렬 분석** 지원 — 여러 영상을 동시에 분석 (ThreadPoolExecutor)

### 🤖 RAG 지식 챗봇 (Second Brain)
> 분석된 모든 지식을 대화형으로 검색하고 통합 답변을 받으세요.

- **ChromaDB** 벡터 데이터베이스에 분석 결과 자동 임베딩 저장
- **Gemini Embedding 2** 기반 시맨틱 검색
- 기간별(7일/14일/30일) · 카테고리별(경제/IT/문화) 필터링
- 여러 영상의 **공통 트렌드·패턴 분석** 지원
- 대화 기록 영구 저장 및 조회

### 📰 AI 신문 발행
> 분석 자료를 카테고리별로 종합하여 전문 기사를 자동 생성합니다.

- 카테고리별 분석 결과를 **Gemini 2.5 Pro**가 통합 기사로 작성
- 생성된 신문 DB 저장 및 열람

### 📈 주식 시세 트래커
> 관심 종목의 시세와 컨센서스 데이터를 한눈에 확인하세요.

- **네이버 금융** 크롤링 기반 일별 OHLCV 데이터 수집
- 시가총액, 컨센서스(영업이익 전망) 데이터 자동 수집
- 그룹(폴더) 단위로 관심 종목 관리
- **APScheduler** 기반 자동 시세 갱신 스케줄러
- KRX 전체 종목 검색 지원

### 🔐 사용자 인증 & 보안
- Google OAuth 2.0 + PKCE 인증 플로우
- **쿠키 기반 영구 세션** — 브라우저를 닫아도 로그인 유지 (30일)
- 미인증 사용자 **클로킹 페이지**로 완전 차단
- 사용자별 데이터 격리 (멀티 유저 지원)

<br />

---

## 🛠 기술 스택

| 영역 | 기술 |
|:---:|:---|
| **Frontend** | Streamlit, Custom CSS, extra-streamlit-components |
| **AI/LLM** | Google Gemini 2.5 Flash, Gemini 2.5 Flash Lite, Gemini 2.5 Pro |
| **Embedding** | Gemini Embedding 2 |
| **Vector DB** | ChromaDB (Persistent) |
| **Database** | SQLite3 |
| **인증** | Google OAuth 2.0 + PKCE |
| **데이터 수집** | YouTube Data API v3, youtube-transcript-api, 네이버 금융 크롤링 |
| **프록시** | Webshare Rotating Proxy |
| **스케줄링** | APScheduler (BackgroundScheduler) |
| **배포** | Oracle Cloud VM, GitHub Actions CI/CD |

<br />

---

## 🚀 시작하기

### 사전 요구사항

- **Python 3.10+**
- **Google API Key** — [Google AI Studio](https://aistudio.google.com)에서 발급
- **Google Cloud OAuth 2.0 Client** — YouTube Data API 활성화 필요
- (선택) **Webshare 프록시** — 자막 추출 시 IP 차단 방지용

### 설치

```bash
# 1. 저장소 클론
git clone https://github.com/your-username/YoutubeSummary.git
cd YoutubeSummary

# 2. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt
```

### 설정

#### `config.json` 생성

```json
{
    "GOOGLE_API_KEY": "YOUR_GEMINI_API_KEY",
    "WEBSHARE_PROXY": {
        "enabled": false,
        "username": "",
        "password": ""
    }
}
```

#### `client_secret.json` 배치

Google Cloud Console에서 다운로드한 OAuth 2.0 클라이언트 시크릿 파일을 프로젝트 루트에 배치합니다.

> [!WARNING]
> `config.json`과 `client_secret.json`은 `.gitignore`에 포함되어 있어 저장소에 커밋되지 않습니다. 절대 공개 저장소에 업로드하지 마세요.

### 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501`로 접속합니다.

<br />

---

## 🏗 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ 영상 분석 │ │ RAG 챗봇 │ │ AI 신문  │ │ 주식 트래커│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘ │
└───────┼────────────┼────────────┼──────────────┼────────┘
        │            │            │              │
   ┌────▼────┐  ┌────▼────┐ ┌────▼────┐   ┌─────▼─────┐
   │ YouTube │  │ChromaDB │ │ Gemini  │   │네이버 금융│
   │Data API │  │Vector DB│ │2.5 Pro  │   │ 크롤링    │
   └────┬────┘  └────┬────┘ └────┬────┘   └─────┬─────┘
        │            │           │               │
   ┌────▼────┐  ┌────▼────┐ ┌───▼─────┐         │
   │자막 추출│  │ Gemini  │ │  기사   │         │
   │(프록시) │  │Embedding│ │  생성   │         │
   └────┬────┘  └────┬────┘ └─────────┘         │
        │            │                           │
   ┌────▼────┐       │                           │
   │ Gemini  │       │                           │
   │2.5 Flash│       │                           │
   └────┬────┘       │                           │
        │            │                           │
        ▼            ▼                           ▼
  ┌──────────────────────────────────────────────────┐
  │              SQLite3 Database                     │
  │  users │ insights │ stocks │ daily_prices │ ...  │
  └──────────────────────────────────────────────────┘
```

### 데이터 흐름

1. **영상 분석**: YouTube API → 자막 추출 → Gemini 분석 → SQLite 저장 + ChromaDB 임베딩
2. **RAG 검색**: 사용자 질의 → Gemini Embedding → ChromaDB 유사도 검색 → Gemini 답변 생성
3. **주식 데이터**: 네이버 금융 크롤링 → SQLite 저장 → Streamlit 차트 렌더링

<br />

---

## 📁 프로젝트 구조

```
YoutubeSummary/
├── app.py                  # 메인 애플리케이션 (Streamlit)
├── requirements.txt        # Python 의존성
├── config.json             # API 키 및 프록시 설정 (gitignore)
├── client_secret.json      # Google OAuth 시크릿 (gitignore)
├── insights.db             # SQLite 데이터베이스 (gitignore)
├── .gitignore
├── .github/
│   └── workflows/
│       └── deploy.yml      # GitHub Actions CI/CD 파이프라인
└── updateNote/             # 업데이트 기록
    ├── 2026-04-11_ui_and_db_update.md
    ├── 2026-04-11_webshare_proxy.md
    ├── 2026-04-12_newspaper_pipeline.md
    └── 2026-04-13_oracle_deployment_and_security_fix.md
```

<br />

---

## 🚢 배포

### GitHub Actions → Oracle Cloud 자동 배포

`main` 브랜치에 푸시하면 **GitHub Actions**가 자동으로 Oracle Cloud VM에 SSH 접속하여 배포합니다.

```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

# 배포 프로세스:
# 1. git fetch & reset --hard origin/main
# 2. pip install -r requirements.txt
# 3. systemctl restart insight-pipeline.service
```

### 필요한 GitHub Secrets

| Secret | 설명 |
|:---|:---|
| `ORACLE_HOST` | Oracle Cloud VM IP 주소 |
| `ORACLE_USER` | SSH 사용자 이름 |
| `ORACLE_SSH_KEY` | SSH 프라이빗 키 |

<br />

---

## 📝 업데이트 기록

| 날짜 | 내용 |
|:---:|:---|
| 2026-04-13 | Oracle Cloud 배포 및 보안 수정 |
| 2026-04-12 | AI 신문 파이프라인 구현 |
| 2026-04-11 | Webshare 프록시 연동 |
| 2026-04-11 | UI 개선 및 DB 스키마 업데이트 |

<br />

---

<div align="center">

### Built with ❤️ and Google Gemini

<sub>Powered by Streamlit · Google Gemini 2.5 · ChromaDB · YouTube Data API</sub>

</div>
