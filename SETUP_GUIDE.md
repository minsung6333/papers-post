# HF Daily Papers 블로그 자동화 설정 가이드

매일 오전 9시(KST)에 HuggingFace 최신 논문을 한국어로 번역해서 Notion에 자동 업로드하는 시스템입니다.

---

## 파일 구조

```
프로젝트 폴더/
├── hf_paper_blog.py          ← 메인 스크립트
├── .github/
│   └── workflows/
│       └── daily-papers.yml  ← GitHub Actions 설정
└── posts/                    ← 로컬 백업 저장 폴더 (자동 생성)
```

---

## Step 1. Notion 데이터베이스 만들기

1. Notion 열기 → 새 페이지 만들기
2. `/database` 입력 → **"Database - Full page"** 선택
3. 페이지 이름: `HF Daily Papers` (원하는 이름으로)
4. 이 데이터베이스의 URL 복사해두기
   - 예: `https://notion.so/abc123def456...`
   - URL에서 `-` 없는 32자리 ID 부분이 **NOTION_DATABASE_ID**

## Step 2. Notion Integration 만들기

1. https://www.notion.so/my-integrations 접속
2. **"+ New integration"** 클릭
3. 이름: `HF Papers Bot` (원하는 이름)
4. **Submit** → **"Internal Integration Secret"** 복사 → 이게 **NOTION_API_KEY**

## Step 3. 데이터베이스에 Integration 연결

1. 만든 Notion 데이터베이스 페이지 열기
2. 우상단 `...` → **"Connections"** → 방금 만든 Integration 추가

---

## Step 4. GitHub 저장소 만들기

```bash
# 터미널에서 실행
mkdir hf-papers-blog
cd hf-papers-blog
git init
```

## Step 5. 파일 배치

```
hf-papers-blog/
├── hf_paper_blog.py       ← 이 파일 복사
├── .github/
│   └── workflows/
│       └── daily-papers.yml  ← 이 파일 복사 (폴더 구조 그대로)
```

`.github/workflows/` 폴더를 직접 만들어야 합니다:

```bash
mkdir -p .github/workflows
cp /path/to/hf_paper_blog.py .
cp /path/to/daily-papers.yml .github/workflows/
```

## Step 6. GitHub에 올리기

```bash
git add .
git commit -m "첫 설정"
git branch -M main
git remote add origin https://github.com/[내_아이디]/hf-papers-blog.git
git push -u origin main
```

> GitHub에서 먼저 `hf-papers-blog` 저장소를 생성해야 합니다 (github.com → New repository)
> **반드시 Private 저장소**로 만드세요 (API 키가 들어가는 프로젝트이므로)

---

## Step 7. GitHub Secrets 설정 (API 키 등록)

1. GitHub 저장소 페이지 → **Settings** 탭
2. 좌측 메뉴 → **Secrets and variables** → **Actions**
3. **"New repository secret"** 으로 아래 3개 등록:

| Secret 이름 | 값 |
|------------|-----|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `NOTION_API_KEY` | `secret_...` |
| `NOTION_DATABASE_ID` | Notion URL의 32자리 ID |

---

## Step 8. 테스트 실행

1. GitHub 저장소 → **Actions** 탭
2. 좌측에서 **"Daily HF Papers Blog"** 클릭
3. **"Run workflow"** 버튼 → **"Run workflow"** 클릭
4. 실행 로그 확인 (약 2~5분 소요)
5. Notion 데이터베이스에 포스트가 올라왔는지 확인

---

## 이후 동작

- 매일 오전 9시(KST)에 자동으로 실행됨
- 데탑/맥북이 꺼져 있어도 GitHub 서버에서 실행
- 실패 시 GitHub에서 이메일 알림 발송

---

## 자주 묻는 것들

**논문 개수 조절하고 싶어요**
→ `hf_paper_blog.py` 상단의 `MAX_PAPERS = 5` 수정

**특정 날짜 논문을 가져오고 싶어요**
→ `fetch_daily_papers("2026-05-20")` 처럼 날짜 지정 가능

**비용은 얼마나 드나요?**
→ Claude API: 논문 1편당 약 $0.01~0.02, 하루 5편이면 $0.1 미만
→ GitHub Actions: 무료 (월 2000분 제공, 하루 5분이면 충분)

**Notion에 업로드 안 되고 에러 나요**
→ Step 3에서 Integration 연결을 빠뜨린 경우가 많음
→ Notion DB URL에서 ID를 잘못 추출한 경우도 있음 (32자리 확인)
