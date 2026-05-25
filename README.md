# 📄 HF Daily Papers → 한국어 블로그 자동 포스팅

HuggingFace Daily Papers에서 LLM/NLP 논문을 골라 한국어 블로그 포스트로 자동 변환 후 **Notion**과 **Velog**에 동시 업로드하는 자동화 파이프라인입니다.

매일 오전 9시(KST) GitHub Actions가 자동으로 실행됩니다.

---

## ✨ 주요 기능

- 🔍 **스마트 논문 필터링** — arXiv 카테고리(cs.CL) 1차 필터 + Claude Haiku 2차 판별로 LLM/NLP 논문만 선별
- ✍️ **한국어 포스트 자동 생성** — Claude Sonnet이 챕터별 번역 + 해설 작성 (멀티턴으로 긴 논문도 완전히 커버)
- 📬 **Notion 업로드** — 커버 이미지, 아이콘, 날짜/업보트/태그 속성 포함
- 🟢 **Velog 업로드** — GraphQL API로 자동 포스팅
- 🔔 **토큰 만료 알림** — Velog refresh_token 만료 7일 전 GitHub Issue 자동 생성

---

## 🏗️ 파이프라인

```
HuggingFace API
    │
    ▼
arXiv 카테고리 조회 (배치)
    │
    ├─ cs.CL → 확정 포함
    └─ cs.AI / cs.LG 등 → Claude Haiku 판별
            │
            ▼
        상위 5편 선정 (업보트 순)
            │
            ▼
        arXiv HTML 섹션 스크래핑
            │
            ▼
        Claude Sonnet 한국어 포스트 생성 (멀티턴)
            │
            ├──▶ Notion 업로드
            ├──▶ Velog 업로드
            └──▶ 로컬 .md 백업 (posts/)
```

---

## ⚙️ 설정

### 1. GitHub Secrets 등록

`Settings → Secrets and variables → Actions`에서 아래 5개 등록:

| Secret | 설명 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API 키 (`sk-ant-...`) |
| `NOTION_API_KEY` | Notion Integration 키 (`ntn_...`) |
| `NOTION_DATABASE_ID` | Notion 데이터베이스 ID (32자리) |
| `VELOG_ACCESS_TOKEN` | Velog 쿠키의 `access_token` |
| `VELOG_REFRESH_TOKEN` | Velog 쿠키의 `refresh_token` |

### 2. Notion 설정

1. Notion에서 데이터베이스 페이지 생성
2. `...` → Connections → Integration 연결
3. 데이터베이스 URL에서 ID 복사

### 3. Velog 토큰 발급

1. [velog.io](https://velog.io) 로그인
2. F12 → Application → Cookies → `https://velog.io`
3. `access_token`, `refresh_token` 값 복사

> ⚠️ `refresh_token`은 약 30일 후 만료됩니다. 만료 7일 전에 GitHub Issue로 자동 알림이 발송됩니다.

---

## 🚀 실행

### 자동 실행
매일 00:00 UTC (09:00 KST)에 GitHub Actions가 자동 실행됩니다.

### 수동 실행
`Actions` 탭 → `Daily HF Papers Blog` → `Run workflow`

### 로컬 실행
```bash
pip install anthropic requests beautifulsoup4 lxml

export ANTHROPIC_API_KEY=...
export NOTION_API_KEY=...
export NOTION_DATABASE_ID=...
export VELOG_ACCESS_TOKEN=...
export VELOG_REFRESH_TOKEN=...

python hf_paper_blog.py
```

---

## 📁 파일 구조

```
├── hf_paper_blog.py          # 메인 스크립트
├── .github/
│   └── workflows/
│       └── daily-papers.yml  # GitHub Actions 워크플로우
├── posts/                    # 로컬 .md 백업 (자동 생성)
│   └── 2026/
│       └── 05/
│           └── 2026-05-25-paper-title.md
└── README.md
```

---

## 💰 비용

| 항목 | 비용 |
|------|------|
| Claude API (논문 5편/일) | ~$0.10/일 |
| GitHub Actions | 무료 (Public 레포) |
| Notion API | 무료 |
| Velog | 무료 |
