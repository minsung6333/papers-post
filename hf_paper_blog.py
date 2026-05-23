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
from pathlib import Path
import anthropic
from bs4 import BeautifulSoup

# ===================== 설정 =====================
MODEL = "claude-sonnet-4-6"
MAX_PAPERS = 5       # 하루 최대 처리 논문 수
SAVE_LOCAL = True    # 로컬에도 .md 파일 저장할지 여부
OUTPUT_DIR = Path("./posts")
# =================================================

LLM_NLP_KEYWORDS = [
    "language model", "llm", "nlp", "transformer", "attention",
    "tokeniz", "fine-tun", "pre-train", "rlhf", "instruction",
    "reasoning", "chain-of-thought", "prompt", "agent", "rag",
    "retrieval", "generation", "summariz", "translation", "embedding",
    "in-context", "few-shot", "zero-shot", "alignment", "sft",
    "reinforcement learning", "reward model", "moe", "mixture of experts",
    "long-context", "context window", "inference", "decoding",
    "hallucination", "benchmark", "evaluation", "multimodal llm",
    "speech", "asr", "text-to-speech", "diffusion language",
]


# ============================================================
# 논문 수집
# ============================================================

def is_llm_nlp_paper(title: str, abstract: str) -> bool:
    text = (title + " " + abstract).lower()
    return any(kw in text for kw in LLM_NLP_KEYWORDS)


def fetch_daily_papers(date: str = None) -> list:
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://huggingface.co/api/papers?date={date}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    papers = resp.json()
    print(f"[{date}] 총 {len(papers)}편 논문 로드")
    return papers


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

    figures = []
    for img in soup.select("figure img, .ltx_figure img"):
        src = img.get("src", "")
        if src:
            if src.startswith("http"):
                figures.append(src)
            else:
                figures.append(f"https://arxiv.org/html/{arxiv_id}/{src.lstrip('/')}")

    captions = [cap.get_text(" ", strip=True)[:300] for cap in soup.select("figcaption")]

    return {
        "sections": sections,
        "figures": figures,
        "captions": captions,
        "full_text": soup.get_text(" ", strip=True)[:15000],
    }


# ============================================================
# 한국어 포스트 생성 (Claude API)
# ============================================================

def generate_korean_post(paper: dict, arxiv_content: dict, client: anthropic.Anthropic) -> str:
    title = paper.get("title", "")
    arxiv_id = paper.get("id", "")
    abstract = paper.get("summary", "")
    authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:5])
    upvotes = paper.get("upvotes", 0)
    published = paper.get("publishedAt", "")[:10]

    figures_md = "\n".join(
        f'![Figure {i+1}: {cap[:100]}]({url})'
        for i, (url, cap) in enumerate(
            zip(arxiv_content["figures"][:6],
                arxiv_content["captions"][:6] + [""]*6)
        )
    )

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
- 발표일: {published} | 업보트: {upvotes}
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

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


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


def post_to_notion(paper: dict, post_content: str, notion_api_key: str, database_id: str) -> str:
    """Notion 데이터베이스에 페이지 생성"""
    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    title = paper.get("title", "제목 없음")
    arxiv_id = paper.get("id", "")

    all_blocks = markdown_to_notion_blocks(post_content)

    # 첫 100개 블록으로 페이지 생성
    page_data = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {
                "title": [{"text": {"content": title[:255]}}]
            }
        },
        "children": all_blocks[:100]
    }

    resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=page_data)
    resp.raise_for_status()
    page_id = resp.json()["id"]

    # 나머지 블록 100개씩 추가
    remaining = all_blocks[100:]
    for j in range(0, len(remaining), 100):
        chunk = remaining[j:j+100]
        requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            json={"children": chunk}
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
# 메인
# ============================================================

def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    notion_key = os.environ.get("NOTION_API_KEY", "")
    notion_db_id = os.environ.get("NOTION_DATABASE_ID", "")

    if not anthropic_key:
        print("❌ ANTHROPIC_API_KEY 환경변수가 없습니다.")
        return
    if not notion_key:
        print("⚠️  NOTION_API_KEY 없음 → Notion 업로드 건너뜀")
    if not notion_db_id:
        print("⚠️  NOTION_DATABASE_ID 없음 → Notion 업로드 건너뜀")

    use_notion = bool(notion_key and notion_db_id)
    client = anthropic.Anthropic(api_key=anthropic_key)

    today = datetime.date.today()
    print(f"\n🚀 HuggingFace Daily Papers 블로그 자동 생성")
    print(f"📅 날짜: {today}")
    print(f"📬 Notion 업로드: {'✅ ON' if use_notion else '❌ OFF'}\n")

    if SAVE_LOCAL:
        output_dir = OUTPUT_DIR / str(today.year) / f"{today.month:02d}"
        output_dir.mkdir(parents=True, exist_ok=True)

    papers = fetch_daily_papers(str(today))

    llm_papers = [
        p for p in papers
        if is_llm_nlp_paper(p.get("title", ""), p.get("summary", ""))
    ]
    llm_papers.sort(key=lambda p: p.get("upvotes", 0), reverse=True)
    llm_papers = llm_papers[:MAX_PAPERS]

    print(f"🔍 LLM/NLP 관련 논문: {len(llm_papers)}편 선정\n")
    for idx, p in enumerate(llm_papers, 1):
        print(f"  {idx}. [{p.get('upvotes',0):3d}👍] {p['title'][:70]}")
    print()

    success = 0
    for i, paper in enumerate(llm_papers, 1):
        arxiv_id = paper.get("id", "")
        title = paper.get("title", "")
        print(f"\n[{i}/{len(llm_papers)}] {title[:60]}...")

        print(f"  📄 arXiv 로드 중...")
        arxiv_content = fetch_arxiv_content(arxiv_id)
        time.sleep(2)

        print(f"  ✍️  Claude로 번역 생성 중...")
        try:
            post_content = generate_korean_post(paper, arxiv_content, client)
        except Exception as e:
            print(f"  ❌ 포스트 생성 실패: {e}")
            continue

        if SAVE_LOCAL:
            filename = f"{today}-{slugify(title)}.md"
            filepath = output_dir / filename
            filepath.write_text(post_content, encoding="utf-8")
            print(f"  💾 로컬 저장: {filepath}")

        if use_notion:
            try:
                page_id = post_to_notion(paper, post_content, notion_key, notion_db_id)
                print(f"  ✅ Notion 업로드 완료: {page_id}")
            except Exception as e:
                print(f"  ❌ Notion 업로드 실패: {e}")

        success += 1
        time.sleep(3)

    print(f"\n🎉 완료! {success}/{len(llm_papers)}편 처리됨")


if __name__ == "__main__":
    main()
