#!/usr/bin/env python3
"""
HuggingFace Daily Papers → 한국어 블로그 포스트 자동 생성 + Notion 업로드
매일 실행하면 LLM/NLP 관련 논문을 골라 챕터별 한국어 포스트를 Notion에 저장합니다.

환경변수 설정 (GitHub Secrets):
  ANTHROPIC_API_KEY  - Claude API 키 (sk-ant-...)
  NOTION_API_KEY     - Notion Integration 키 (secret_...)
  NOTION_DATABASE_ID - Notion 데이터베이스 ID
"""

import os
import re
import time
import requests
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
import anthropic
from bs4 import BeautifulSoup

# ===================== 설정 =====================
MODEL = "claude-sonnet-4-6"
MAX_PAPERS = 5       # 하루 최대 처리 논문 수
SAVE_LOCAL = True    # 로컬에도 .md 파일 저장할지 여부
OUTPUT_DIR = Path("./posts")
# =================================================

# cs.CL → LLM/NLP 확정, 나머지 → Claude Haiku로 2차 판별
NLP_PRIMARY_CATS = {"cs.CL"}
NLP_AMBIGUOUS_CATS = {"cs.AI", "cs.LG", "cs.IR", "cs.NE", "stat.ML"}


# ============================================================
# 논문 수집
# ============================================================

def fetch_arxiv_categories_batch(arxiv_ids: list) -> dict:
    """arXiv API로 여러 논문 카테고리 단일 요청으로 조회"""
    id_list = ",".join(arxiv_ids)
    url = f"http://export.arxiv.org/api/query?id_list={id_list}&max_results={len(arxiv_ids)}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  arXiv 카테고리 조회 실패: {e}")
        return {}

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(resp.text)
    result = {}
    for entry in root.findall("atom:entry", ns):
        id_elem = entry.find("atom:id", ns)
        if id_elem is None:
            continue
        arxiv_id = id_elem.text.split("/abs/")[-1].split("v")[0]
        cats = []
        primary = entry.find("arxiv:primary_category", ns)
        if primary is not None:
            cats.append(primary.get("term", ""))
        for cat in entry.findall("atom:category", ns):
            term = cat.get("term", "")
            if term and term not in cats:
                cats.append(term)
        result[arxiv_id] = cats
    return result


def classify_with_claude_haiku(papers: list, client: anthropic.Anthropic) -> list:
    """Claude Haiku로 LLM/NLP 관련 논문 배치 판별"""
    if not papers:
        return []

    paper_list = "\n".join(
        f"{i+1}. 제목: {p.get('title', '')}\n   초록: {p.get('summary', '')[:300]}"
        for i, p in enumerate(papers)
    )
    prompt = f"""다음 논문들 중 LLM(대형 언어 모델), NLP(자연어 처리), 생성 AI와 직접 관련된 논문의 번호만 나열하세요.
컴퓨터 비전만 다루거나 로봇공학, 순수 수학 등 NLP와 무관한 논문은 제외하세요.
번호만 쉼표로 구분해서 답하세요. 예: 1, 3, 5

{paper_list}"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    try:
        indices = [int(x.strip()) - 1 for x in re.split(r"[,\s]+", text) if x.strip().isdigit()]
        return [papers[i] for i in indices if 0 <= i < len(papers)]
    except Exception:
        return []


def filter_llm_papers(papers: list, client: anthropic.Anthropic) -> list:
    """arXiv 카테고리(1차) + Claude Haiku(2차) 이중 필터링"""
    arxiv_ids = [p["id"] for p in papers]
    print(f"  [1/2] arXiv 카테고리 조회 중... ({len(arxiv_ids)}편)")
    categories = fetch_arxiv_categories_batch(arxiv_ids)

    definitely_in, ambiguous = [], []
    for paper in papers:
        cats = set(categories.get(paper["id"], []))
        if cats & NLP_PRIMARY_CATS:
            definitely_in.append(paper)
        elif cats & NLP_AMBIGUOUS_CATS or not cats:
            ambiguous.append(paper)

    print(f"  cs.CL 확정: {len(definitely_in)}편 | 2차 판별 대상: {len(ambiguous)}편")

    if ambiguous:
        print(f"  [2/2] Claude Haiku로 {len(ambiguous)}편 분류 중...")
        claude_selected = classify_with_claude_haiku(ambiguous, client)
        print(f"  Claude 선정: {len(claude_selected)}편")
        definitely_in.extend(claude_selected)

    return definitely_in


def fetch_daily_papers(date: str = None) -> tuple:
    """오늘부터 최대 7일 전까지 거슬러 올라가며 논문이 있는 날짜 반환.
    Returns (papers, fetch_date) tuple."""
    if date is not None:
        url = f"https://huggingface.co/api/papers?date={date}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        papers = resp.json()
        print(f"[{date}] {len(papers)} papers loaded")
        return papers, date

    for days_back in range(7):
        d = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
        resp = requests.get(f"https://huggingface.co/api/papers?date={d}", timeout=30)
        resp.raise_for_status()
        papers = resp.json()
        if papers:
            if days_back > 0:
                print(f"No papers for today, using {d} ({days_back} days back)")
            print(f"[{d}] {len(papers)} papers loaded")
            return papers, d

    return [], datetime.date.today().strftime("%Y-%m-%d")


def fetch_arxiv_content(arxiv_id: str) -> dict:
    url = f"https://arxiv.org/html/{arxiv_id}"
    headers = {"User-Agent": "Mozilla/5.0 (research bot)"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  arXiv HTML 접근 실패 ({arxiv_id}): {e}")
        return {"sections": {}, "figures": [], "captions": [], "full_text": ""}

    soup = BeautifulSoup(resp.text, "lxml")

    sections = {}
    current_section = "Abstract"
    current_text = []

    for tag in soup.find_all(["h1", "h2", "h3", "p", "figcaption"]):
        if tag.name in ("h1", "h2", "h3"):
            if current_text:
                sections[current_section] = " ".join(current_text).strip()
            current_section = tag.get_text(" ", strip=True)
            current_text = []
        else:
            text = tag.get_text(" ", strip=True)
            if len(text) > 20:
                current_text.append(text)

    if current_text:
        sections[current_section] = " ".join(current_text).strip()

    captions = [cap.get_text(" ", strip=True)[:300] for cap in soup.select("figcaption")]

    return {
        "sections": sections,
        "figures": [],      # arXiv HTML 이미지는 PDF 렌더링이라 신뢰 불가 → HF 썸네일만 사용
        "captions": captions,
        "full_text": soup.get_text(" ", strip=True)[:15000],
    }


# ============================================================
# 한국어 포스트 생성 (Claude API)
# ============================================================

def generate_korean_post(paper: dict, arxiv_content: dict, client: anthropic.Anthropic, fetch_date: str = None) -> str:
    title = paper.get("title", "")
    arxiv_id = paper.get("id", "")
    abstract = paper.get("summary", "")
    authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:5])
    upvotes = paper.get("upvotes", 0)
    published = paper.get("publishedAt", "")[:10]
    featured_date = fetch_date or datetime.date.today().strftime("%Y-%m-%d")
    hf_thumbnail = paper.get("thumbnailUrl", "")

    # HF 썸네일만 신뢰성 있는 이미지로 사용
    figures_md = f"![논문 썸네일]({hf_thumbnail})" if hf_thumbnail else ""

    sections_text = "\n\n".join(
        f"## {sec}\n{text[:2000]}"
        for sec, text in list(arxiv_content["sections"].items())[:10]
        if len(text) > 100
    )

    prompt = f"""당신은 AI/ML 논문을 한국어로 번역·해설하는 전문 블로거입니다.
영어 논문을 읽지 못하는 한국어 독자들을 위해, 논문 내용을 **챕터별로 완전히 번역하고 친절하게 설명**하는 블로그 포스트를 작성하세요.

## 논문 정보
- 제목: {title}
- arXiv ID: {arxiv_id}
- 저자: {authors}
- HF 피처일: {featured_date} | arXiv 발표일: {published} | 업보트: {upvotes}
- HuggingFace: https://huggingface.co/papers/{arxiv_id}
- arXiv HTML: https://arxiv.org/html/{arxiv_id}

## 논문 초록 (원문)
{abstract}

## 논문 주요 섹션 내용 (원문)
{sections_text[:8000]}

## 논문 그림 URLs
{figures_md}

## 작성 지침

다음 형식으로 **완전한 마크다운 블로그 포스트**를 작성하세요:

1. **헤더**: 논문 제목(한국어 설명 포함), 메타정보(저자, 기관, 링크, 날짜, 업보트)
2. **한 줄 요약**: 핵심을 한 문장으로
3. **Abstract 번역**: 초록 전체를 자연스러운 한국어로
4. **각 챕터별 번역 및 설명**:
   - Introduction: 배경과 문제 설명, 기존 방법의 한계
   - Related Work: 관련 연구 흐름
   - Method: 핵심 아이디어와 방법론 (수식이 있으면 설명 포함)
   - Experiments: 실험 설정, 주요 결과 (표는 한국어로 재정리)
   - Conclusion: 결론 및 한계
5. **그림 삽입**: 각 챕터에 맞는 위치에 그림 URL을 마크다운으로 삽입하고 **한국어 캡션** 추가
6. **개인 소감**: 이 논문의 의의와 개인적 생각 2-3문단
7. **태그**: 관련 태그들

각 섹션을 충분히 자세하게 설명하되, 전문 용어는 한국어 번역 후 영문 병기 형식(예: 강화학습(Reinforcement Learning))으로 표기하세요.
독자가 원문 없이도 논문의 핵심을 완전히 이해할 수 있도록 작성하세요."""

    messages = [{"role": "user", "content": prompt}]
    full_text = ""

    for turn in range(1, 6):  # 최대 5회 = ~40000 토큰
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            messages=messages,
        )
        chunk = response.content[0].text
        full_text += chunk

        if response.stop_reason != "max_tokens":
            print(f"  generation complete ({turn} turn{'s' if turn > 1 else ''})")
            break

        print(f"  turn {turn} done, continuing...")
        messages.append({"role": "assistant", "content": chunk})
        messages.append({"role": "user", "content": "계속 작성해주세요."})

    return full_text


# ============================================================
# Velog 업로드
# ============================================================

VELOG_GQL = "https://v3.velog.io/graphql"


def _extract_tags(post_content: str) -> list:
    """포스트 하단 태그 섹션에서 태그 추출"""
    match = re.search(r'(?:태그|Tags?)[:\s#]*([#\w,\s가-힣A-Za-z0-9_-]+)', post_content, re.IGNORECASE)
    if match:
        tags = re.findall(r'#?([\w가-힣A-Za-z0-9_-]+)', match.group(1))
        return [t for t in tags if len(t) > 1][:10]
    return ["AI", "LLM", "NLP"]


def refresh_velog_token(refresh_token: str) -> str:
    """refresh_token으로 새 access_token 발급.
    v3.velog.io/api/auth/refresh 는 404를 반환하지만
    Set-Cookie 헤더에 새 access_token을 담아줌."""
    resp = requests.get(
        "https://v3.velog.io/api/auth/refresh",
        headers={"cookie": f"refresh_token={refresh_token}"},
        timeout=30,
        allow_redirects=True,
    )
    new_token = resp.cookies.get("access_token")
    if not new_token:
        raise Exception(f"Token refresh failed (status={resp.status_code})")
    print("  Velog token refreshed successfully")
    return new_token


def post_to_velog(paper: dict, post_content: str, access_token: str, refresh_token: str) -> str:
    """Velog에 포스트 업로드.
    브라우저 재로그인 등으로 access_token이 서버 측에서 무효화될 수 있으므로,
    항상 refresh_token으로 새 access_token을 먼저 발급한 뒤 포스팅합니다.
    refresh 실패 시 기존 access_token으로 폴백합니다."""
    title = paper.get("title", "")
    url_slug = slugify(title)
    tags = _extract_tags(post_content)

    mutation = """
    mutation WritePost($input: WritePostInput!) {
        writePost(input: $input) {
            id
            url_slug
            user { username }
        }
    }
    """
    variables = {
        "input": {
            "title": title,
            "body": post_content,
            "tags": tags,
            "is_markdown": True,
            "is_temp": False,
            "is_private": False,
            "url_slug": url_slug,
            "thumbnail": None,
            "meta": {},
            "series_id": None,
        }
    }

    def _do_post(token: str) -> dict | None:
        """포스트 요청. 빈 응답(토큰 무효화) 또는 에러 시 None 반환."""
        resp = requests.post(
            VELOG_GQL,
            json={"query": mutation, "variables": variables},
            headers={"Content-Type": "application/json", "cookie": f"access_token={token}"},
            timeout=30,
        )
        resp.raise_for_status()
        if not resp.content:
            return None  # 서버 측 토큰 무효화 시 빈 body 반환
        data = resp.json()
        if "errors" in data:
            return None  # GraphQL 인증 오류
        return data

    # 1) 항상 먼저 refresh → 서버 측 무효화된 토큰 문제를 원천 차단
    try:
        fresh_token = refresh_velog_token(refresh_token)
    except Exception as e:
        print(f"  Token refresh 실패 → 기존 access_token 사용: {e}")
        fresh_token = access_token

    # 2) 새 토큰으로 포스팅
    data = _do_post(fresh_token)

    # 3) 그래도 실패하면 원래 토큰으로 한 번 더 시도
    if data is None and fresh_token != access_token:
        print("  Refreshed token 실패 → 기존 access_token으로 재시도...")
        data = _do_post(access_token)

    if data is None:
        raise Exception("Velog writePost 실패: 인증 오류 (토큰 만료 또는 권한 없음)")

    post = data["data"]["writePost"]
    username = post["user"]["username"]
    slug = post["url_slug"]
    return f"https://velog.io/@{username}/{slug}"


# ============================================================
# Notion 업로드
# ============================================================

def _rich_text(content: str) -> list:
    """Notion rich_text 블록 생성 (2000자 제한 처리)"""
    content = content[:2000]
    return [{"type": "text", "text": {"content": content}}]


def markdown_to_notion_blocks(markdown_text: str) -> list:
    """마크다운 텍스트를 Notion 블록 리스트로 변환"""
    blocks = []
    lines = markdown_text.split('\n')
    i = 0
    in_code_block = False
    code_lines = []
    code_lang = "plain text"

    while i < len(lines):
        line = lines[i]

        # 코드 블록 처리
        if line.startswith('```'):
            if not in_code_block:
                in_code_block = True
                lang = line[3:].strip().lower()
                notion_langs = {"python", "javascript", "typescript", "java", "c", "cpp",
                                "bash", "shell", "json", "yaml", "markdown", "sql"}
                code_lang = lang if lang in notion_langs else "plain text"
                code_lines = []
            else:
                in_code_block = False
                blocks.append({
                    "object": "block", "type": "code",
                    "code": {
                        "rich_text": _rich_text('\n'.join(code_lines)),
                        "language": code_lang
                    }
                })
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # 구분선
        if line.strip() in ('---', '***', '___'):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 헤딩
        if line.startswith('# '):
            blocks.append({
                "object": "block", "type": "heading_1",
                "heading_1": {"rich_text": _rich_text(line[2:].strip())}
            })
            i += 1
            continue

        if line.startswith('## '):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": _rich_text(line[3:].strip())}
            })
            i += 1
            continue

        if line.startswith('### '):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(line[4:].strip())}
            })
            i += 1
            continue

        # 이미지
        img_match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
        if img_match:
            alt, url = img_match.group(1), img_match.group(2)
            if url.startswith('http'):
                blocks.append({
                    "object": "block", "type": "image",
                    "image": {"type": "external", "external": {"url": url}}
                })
                if alt:
                    blocks.append({
                        "object": "block", "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": f"▲ {alt[:200]}"},
                                "annotations": {"italic": True, "color": "gray"}
                            }]
                        }
                    })
            i += 1
            continue

        # 인용구
        if line.startswith('> '):
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', line[2:].strip())
            blocks.append({
                "object": "block", "type": "quote",
                "quote": {"rich_text": _rich_text(text)}
            })
            i += 1
            continue

        # 불릿 리스트
        if re.match(r'^[-*] ', line):
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', line[2:].strip())
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _rich_text(text)}
            })
            i += 1
            continue

        # 번호 리스트
        if re.match(r'^\d+\. ', line):
            text = re.sub(r'^\d+\. ', '', line).strip()
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            blocks.append({
                "object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": _rich_text(text)}
            })
            i += 1
            continue

        # 표 → code block으로 변환
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].startswith('|'):
                if not re.match(r'^\|[-:\s|]+\|$', lines[i]):
                    table_lines.append(lines[i])
                i += 1
            if table_lines:
                blocks.append({
                    "object": "block", "type": "code",
                    "code": {
                        "rich_text": _rich_text('\n'.join(table_lines)),
                        "language": "plain text"
                    }
                })
            continue

        # 빈 줄
        if not line.strip():
            i += 1
            continue

        # 일반 단락
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', line.strip())
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        if text:
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(text)}
            })
        i += 1

    return blocks


def setup_notion_database_schema(database_id: str, notion_api_key: str) -> None:
    """DB에 날짜/업보트/arXiv/태그 속성 추가 (이미 있으면 무시)"""
    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    requests.patch(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        json={
            "properties": {
                "Published": {"date": {}},
                "Upvotes": {"number": {"format": "number"}},
                "arXiv": {"url": {}},
                "Tags": {"multi_select": {}},
            }
        },
        timeout=30,
    ).raise_for_status()


def post_to_notion(paper: dict, post_content: str, notion_api_key: str, database_id: str) -> str:
    """Notion 데이터베이스에 페이지 생성 (커버/아이콘/속성 포함)"""
    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    title = paper.get("title", "제목 없음")
    arxiv_id = paper.get("id", "")
    published = paper.get("publishedAt", "")[:10]
    upvotes = paper.get("upvotes", 0)
    thumbnail = paper.get("thumbnailUrl", "")
    tags = _extract_tags(post_content)

    all_blocks = markdown_to_notion_blocks(post_content)

    page_data = {
        "parent": {"database_id": database_id},
        "icon": {"type": "emoji", "emoji": "📄"},
        "properties": {
            "Name": {"title": [{"text": {"content": title[:255]}}]},
            "Upvotes": {"number": upvotes},
            "arXiv": {"url": f"https://arxiv.org/abs/{arxiv_id}"},
            "Tags": {"multi_select": [{"name": t} for t in tags[:5]]},
        },
        "children": all_blocks[:100],
    }

    if thumbnail:
        page_data["cover"] = {"type": "external", "external": {"url": thumbnail}}
    # HF 피처일 우선, 없으면 arXiv 발표일
    date_to_use = paper.get("fetch_date") or published
    if date_to_use:
        page_data["properties"]["Published"] = {"date": {"start": date_to_use}}

    resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=page_data)
    resp.raise_for_status()
    page_id = resp.json()["id"]

    # 나머지 블록 100개씩 추가
    remaining = all_blocks[100:]
    for j in range(0, len(remaining), 100):
        requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            json={"children": remaining[j:j+100]},
        ).raise_for_status()
        time.sleep(0.3)

    return page_id


# ============================================================
# 유틸
# ============================================================

def slugify(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s-]", "", title)
    title = re.sub(r"\s+", "-", title.strip())
    return title[:60]


# ============================================================
# 토큰 만료 알림
# ============================================================

def check_token_expiry_and_notify(refresh_token: str) -> None:
    """refresh_token 만료 7일 전 GitHub Issue 자동 생성"""
    import base64, json as _json

    payload_b64 = refresh_token.split(".")[1]
    padding = (4 - len(payload_b64) % 4) % 4
    payload = _json.loads(base64.b64decode(payload_b64 + "=" * padding))

    exp_dt = datetime.datetime.fromtimestamp(payload["exp"], tz=datetime.timezone.utc)
    days_left = (exp_dt - datetime.datetime.now(tz=datetime.timezone.utc)).days

    print(f"Velog refresh_token: {days_left}days left (expires {exp_dt.strftime('%Y-%m-%d')})")

    if days_left > 7:
        return

    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not github_token or not repo:
        print(f"WARNING: Velog refresh_token expires in {days_left} days! Update GitHub Secrets.")
        return

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": f"[Action Required] Velog refresh_token expires in {days_left} days",
            "body": (
                f"## Velog 토큰 갱신 필요\n\n"
                f"`refresh_token`이 **{days_left}일 후** 만료됩니다.\n\n"
                f"**만료 일시**: {exp_dt.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                f"### 갱신 방법\n"
                f"1. [velog.io](https://velog.io) 로그인\n"
                f"2. F12 → Application → Cookies → `https://velog.io`\n"
                f"3. `access_token`, `refresh_token` 값 복사\n"
                f"4. GitHub Secrets → `VELOG_ACCESS_TOKEN`, `VELOG_REFRESH_TOKEN` 업데이트\n"
            ),
        },
        timeout=30,
    )
    if resp.status_code == 201:
        print(f"GitHub Issue created: {resp.json()['html_url']}")
    else:
        print(f"GitHub Issue creation failed: {resp.status_code}")


# ============================================================
# 메인
# ============================================================

def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    notion_key = os.environ.get("NOTION_API_KEY", "")
    notion_db_id = os.environ.get("NOTION_DATABASE_ID", "")
    velog_access = os.environ.get("VELOG_ACCESS_TOKEN", "")
    velog_refresh = os.environ.get("VELOG_REFRESH_TOKEN", "")

    if not anthropic_key:
        print("ANTHROPIC_API_KEY 환경변수가 없습니다.")
        return
    if not notion_key:
        print("NOTION_API_KEY 없음 -> Notion 업로드 건너뜀")
    if not notion_db_id:
        print("NOTION_DATABASE_ID 없음 -> Notion 업로드 건너뜀")
    if not velog_access:
        print("VELOG_ACCESS_TOKEN 없음 -> Velog 업로드 건너뜀")

    use_notion = bool(notion_key and notion_db_id)
    use_velog = bool(velog_access and velog_refresh)

    if velog_refresh:
        check_token_expiry_and_notify(velog_refresh)

    if use_notion:
        try:
            setup_notion_database_schema(notion_db_id, notion_key)
        except Exception as e:
            print(f"DB schema setup failed (non-fatal): {e}")

    client = anthropic.Anthropic(api_key=anthropic_key)

    papers, fetch_date = fetch_daily_papers()
    today = datetime.date.fromisoformat(fetch_date)

    print(f"\nHuggingFace Daily Papers blog auto-generation")
    print(f"Fetch date: {fetch_date}")
    print(f"Notion: {'ON' if use_notion else 'OFF'} | Velog: {'ON' if use_velog else 'OFF'}\n")

    if SAVE_LOCAL:
        output_dir = OUTPUT_DIR / str(today.year) / f"{today.month:02d}"
        output_dir.mkdir(parents=True, exist_ok=True)

    llm_papers = filter_llm_papers(papers, client)
    llm_papers.sort(key=lambda p: p.get("upvotes", 0), reverse=True)
    llm_papers = llm_papers[:MAX_PAPERS]

    print(f"Selected {len(llm_papers)} LLM/NLP papers\n")
    for idx, p in enumerate(llm_papers, 1):
        print(f"  {idx}. [{p.get('upvotes',0):3d}] {p['title'][:70]}")
    print()

    success = 0
    for i, paper in enumerate(llm_papers, 1):
        arxiv_id = paper.get("id", "")
        title = paper.get("title", "")
        print(f"\n[{i}/{len(llm_papers)}] {title[:60]}...")

        print(f"  Loading arXiv...")
        arxiv_content = fetch_arxiv_content(arxiv_id)
        time.sleep(2)

        paper["fetch_date"] = fetch_date  # Notion Published 날짜용
        print(f"  Generating Korean post with Claude...")
        try:
            post_content = generate_korean_post(paper, arxiv_content, client, fetch_date)
        except Exception as e:
            print(f"  Post generation failed: {e}")
            continue

        if SAVE_LOCAL:
            filename = f"{fetch_date}-{slugify(title)}.md"
            filepath = output_dir / filename
            filepath.write_text(post_content, encoding="utf-8")
            print(f"  Saved locally: {filepath}")

        if use_notion:
            try:
                page_id = post_to_notion(paper, post_content, notion_key, notion_db_id)
                print(f"  Notion upload done: {page_id}")
            except Exception as e:
                print(f"  Notion upload failed: {e}")

        if use_velog:
            try:
                velog_url = post_to_velog(paper, post_content, velog_access, velog_refresh)
                print(f"  Velog upload done: {velog_url}")
            except Exception as e:
                print(f"  Velog upload failed: {e}")

        success += 1
        time.sleep(3)

    print(f"\n🎉 완료! {success}/{len(llm_papers)}편 처리됨")


if __name__ == "__main__":
    main()
