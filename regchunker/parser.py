# -*- coding: utf-8 -*-
"""법규체 문서 구조 파싱 → 조문 단위 청크 생성.

계층: 제목 + 연혁 / 장 → (절) → 조(항·호·목) / 부칙 / 별표.
기본 청크 단위 = 조(條). 과대 조문은 항(①) 경계로 2차 분할(부모-자식).
"""
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from .config import MAX_CHARS

# ---- 도메인 패턴 ----
# 조문 헤딩: '제N조(제목' 또는 '제N조 <삭제>' (가지조문 '의M' 포함).
RE_ART = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:[\(\（]|<\s*삭\s*제)")
RE_ART_TITLE = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[\(\（]([^\)\）]*)[\)\）]")
RE_CHAP = re.compile(r"^제\s*(\d+)\s*장\s*(.*)")
RE_SEC = re.compile(r"^제\s*(\d+)\s*절\s*(.*)")
RE_BUCHIK = re.compile(r"^부\s*칙")
RE_HIST = re.compile(r"^(제\s*정|개\s*정|전부개정|일부개정)")
RE_HANG = re.compile(r"([①-⑳])")
RE_DELETED = re.compile(r"삭\s*제")
RE_APPENDIX = re.compile(r"(별표|별지|서식)")
RE_AMEND = re.compile(r"[<\(](?:개정|신설|전문개정)\s*([0-9.\s,]+?)\s*[>\)]")
# 연혁 표 셀에 한 줄로 나열된 '제정/개정 : 날짜' 항목 (예: '개 정(3) : 1997. 3. 5')
RE_HIST_ENTRY = re.compile(
    r"(제\s*정|개\s*정\s*(?:\(\d+\))?|전부개정|일부개정)"
    r"\s*:\s*"
    r"(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2})"
)

_DOC_TYPES = ("정관", "규정", "기준", "요령", "지침", "세칙", "내규")


@dataclass
class Chunk:
    chunk_id: str = ""
    doc_id: str = ""
    doc_title: str = ""
    doc_type: str = ""
    source_file: str = ""
    enacted: str = ""
    last_amended: str = ""
    doc_family: str = "법규체"             # 법규체 | 공문체
    unit: str = "조"                       # 조 | 부칙 | 연혁 | 헤더 | 본문 | 붙임 | 목차
    chapter_no: Optional[str] = None
    chapter_title: Optional[str] = None
    section_no: Optional[str] = None
    section_title: Optional[str] = None
    article_no: Optional[str] = None
    article_branch: Optional[str] = None    # 가지조문 '의N'
    article_label: str = ""
    article_title: str = ""
    hierarchy_path: str = ""
    recipient: str = ""                     # 공문체 수신
    sender: str = ""                        # 공문체 발신
    is_deleted: bool = False
    has_appendix_ref: bool = False
    has_table: bool = False
    has_figure: bool = False
    amendment_dates: List[str] = field(default_factory=list)
    split_index: int = 0
    split_total: int = 1
    char_len: int = 0
    text: str = ""
    table_markdown: List[str] = field(default_factory=list)  # 청크 내 GFM 표 블록(등장순). 표 없으면 []
    table_html: List[str] = field(default_factory=list)      # 청크 내 HTML <table> 블록(등장순). 표 없으면 []
    table_xml: List[str] = field(default_factory=list)       # 청크 내 표의 시맨틱 XML(<table><row><cell>) 블록(등장순)
    figure_markdown: List[str] = field(default_factory=list)  # 청크 내 도형 마크다운(불릿) 블록(등장순). 도형 없으면 []
    figure_html: List[str] = field(default_factory=list)      # 청크 내 도형 HTML(<figure>) 블록(등장순)
    figure_xml: List[str] = field(default_factory=list)       # 청크 내 도형 시맨틱 XML(<figure>) 블록(등장순)

    def to_dict(self) -> dict:
        return asdict(self)


def infer_doc_type(title: str) -> str:
    """문서 제목에서 규정 유형(정관/규정/…) 추출. 미분류 시 '기타'."""
    for t in _DOC_TYPES:
        if t in title:
            return t
    return "기타"


def history_table_entries(para: str) -> List[str]:
    """연혁 표 단락 → 개별 연혁 줄 리스트. 연혁 표가 아니면 [].

    rhwp 백엔드는 본문 앞 제정/개정 연혁 블록을 단일셀 GFM 표
    ('| 제 정 : 1989. 3.31 개 정(1) : 1995. 6.20 … |')로 렌더한다.
    줄단위 RE_HIST 매칭이 실패해 연혁이 통째로 누락되므로, 표 셀을
    평탄화해 '제정/개정 : 날짜' 항목들을 개별 줄로 복원한다.
    """
    s = para.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return []
    flat = s.replace("|", " ")
    entries = RE_HIST_ENTRY.findall(flat)
    if not entries:
        return []
    return [f"{re.sub(r'\s+', ' ', m.strip())} : {re.sub(r'\s+', '', d)}"
            for m, d in entries]


def parse_amendment_dates(text: str) -> List[str]:
    """<개정 2003.4.16., 2005.4.19.> → ['2003.4.16.', '2005.4.19.'] (중복 제거, 순서 보존)."""
    out: List[str] = []
    for grp in RE_AMEND.findall(text):
        for d in grp.split(","):
            d = d.strip()
            if not d:
                continue
            if not d.endswith("."):
                d += "."
            if d not in out:
                out.append(d)
    return out


# 파일명에서 제목 추출 시 걸러낼 보안 등급 레이블
_RE_SECURITY_LABEL = re.compile(
    r"^\s*(대외주의|대외비|비\s*밀|비공개|내부검토용|관계자외\s*비공개)\s*$"
)


def make_doc_id(fname: str) -> str:
    doc_id = re.sub(r"\.HWPX$", "", fname, flags=re.I)
    doc_id = re.sub(r"_\(?[0-9a-f]{6,}\)?$", "", doc_id)   # 끝의 해시 꼬리 제거
    # JSON 키·파일시스템 비허용 문자 → 언더스코어로 치환
    doc_id = re.sub(r'[<>:"/\\|?*\(\)\[\]\{\}\'`]', "_", doc_id)
    doc_id = re.sub(r"_+", "_", doc_id).strip("_")
    return doc_id


_RE_GFM_ROW = re.compile(r"^\|.*\|$")


def _extract_gfm_tables(text: str) -> Tuple[List[str], List[str], List[str]]:
    """청크 텍스트에서 GFM 테이블 블록을 추출해 (markdowns, htmls, xmls)을 반환.

    표가 없으면 ([], [], [])을 반환한다.
    한 청크에 표가 여러 개면 등장 순서대로 각각 별도 항목으로 담는다
    (i번째 markdown ↔ i번째 html ↔ i번째 xml 대응).
    """
    from .hwpx_reader import markdown_table_to_html, markdown_table_to_xml  # 순환 임포트 없음

    lines = text.splitlines()
    blocks: List[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        # 현재 줄과 다음 줄이 모두 |…| 패턴이고, 다음 줄이 구분선이면 테이블 블록 시작
        if _RE_GFM_ROW.match(ln) and i + 1 < len(lines):
            sep_parts = [c.strip() for c in lines[i + 1].strip().strip("|").split("|") if c.strip()]
            if sep_parts and all(re.match(r"^:?-+:?$", c) for c in sep_parts):
                block: List[str] = []
                j = i
                while j < len(lines) and _RE_GFM_ROW.match(lines[j].strip()):
                    block.append(lines[j].strip())
                    j += 1
                if block:
                    blocks.append("\n".join(block))
                i = j
                continue
        i += 1

    if not blocks:
        return [], [], []
    return (blocks,
            [markdown_table_to_html(b) for b in blocks],
            [markdown_table_to_xml(b) for b in blocks])


def _extract_figures(text: str) -> Tuple[str, List[str], List[str], List[str]]:
    """청크 텍스트에서 도형 토큰 줄을 분리해 (정제텍스트, md, html, xml)을 반환.

    도형 줄(FIGURE_PREFIX)은 본문 텍스트에서 제거되고 별도 필드로 빠진다.
    도형이 없으면 (원본텍스트, [], [], [])을 반환한다.
    """
    from .hwpx_reader import (figure_boxes_from_line, figure_to_markdown,
                              figure_to_html, figure_to_xml)

    md: List[str] = []
    html: List[str] = []
    xml: List[str] = []
    kept_lines: List[str] = []
    for line in text.splitlines():
        boxes = figure_boxes_from_line(line.strip())
        if boxes:
            md.append(figure_to_markdown(boxes))
            html.append(figure_to_html(boxes))
            xml.append(figure_to_xml(boxes))
        else:
            kept_lines.append(line)
    if not md:
        return text, [], [], []
    return "\n".join(kept_lines).strip(), md, html, xml


def _finalize_figures(chunks: List["Chunk"]) -> None:
    """모든 청크에서 도형 토큰을 분리해 figure_* 필드로 옮기고 본문은 정제(in-place).

    어떤 단위(조·부칙·연혁·본문)의 청크든 토큰이 본문에 새어나가지 않게 보장한다.
    """
    for c in chunks:
        clean, md, html, xml = _extract_figures(c.text)
        if md:
            c.text = clean
            c.char_len = len(clean)
            c.figure_markdown = md
            c.figure_html = html
            c.figure_xml = xml
            c.has_figure = True


def split_oversized(article_text: str) -> List[str]:
    """과대 조문을 항(①②) 경계로 분할. 조 제목(헤딩)을 각 조각에 컨텍스트로 유지."""
    parts = RE_HANG.split(article_text)
    if len(parts) <= 1:
        return [article_text]               # 항 마커 없음 → 분할 불가
    head = parts[0].strip()
    segs = []
    i = 1
    while i < len(parts):
        marker = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        segs.append((marker + body).strip())
        i += 2
    ctx = (head.split(")")[0] + ")") if ")" in head[:60] else head[:40]
    chunks, cur = [], head
    for s in segs:
        cand = (cur + "\n" + s).strip()
        if len(cand) > MAX_CHARS and cur != head:
            chunks.append(cur)
            cur = ctx + "\n" + s
        else:
            cur = cand
    if cur.strip():
        chunks.append(cur)
    return chunks


def pick_title(paras: List[str], fname: str) -> str:
    """첫 단락이 보안 등급 레이블이면 두 번째 단락을 문서 제목으로 사용.

    '대외주의', '대외비' 등 기관 보안 분류 라벨이 첫 줄에 오는 경우를 처리한다.
    """
    if not paras:
        return fname
    if _RE_SECURITY_LABEL.match(paras[0]) and len(paras) > 1:
        return paras[1]
    return paras[0]


def parse_document(paras: List[str], fname: str) -> List[Chunk]:
    """단락 리스트 → Chunk 리스트(연혁 1 + 조문 N + 부칙 M)."""
    title = pick_title(paras, fname)
    doc_type = infer_doc_type(title)
    doc_id = make_doc_id(fname)

    # 연혁 블록 수집
    hist: List[str] = []
    body_start = 1
    for i in range(1, len(paras)):
        if RE_HIST.match(paras[i]):
            hist.append(paras[i])
            body_start = i + 1
        elif history_table_entries(paras[i]):
            hist.extend(history_table_entries(paras[i]))
            body_start = i + 1
        elif RE_CHAP.match(paras[i]) or RE_ART.match(paras[i]):
            body_start = i
            break
        else:
            body_start = i + 1
    enacted = next((h for h in hist if h.startswith("제")), "")
    last_amended = hist[-1] if hist else ""

    chunks: List[Chunk] = []
    chap_no = chap_title = sec_no = sec_title = None
    in_buchik = False
    cur_art = None
    buchik_lines: List[str] = []

    def flush_article():
        nonlocal cur_art
        if not cur_art:
            return
        text = "\n".join(cur_art["lines"]).strip()
        tm = RE_ART_TITLE.match(text)
        atitle = tm.group(1).strip() if tm else ("삭제" if RE_DELETED.search(cur_art["head"]) else "")
        deleted = (atitle == "삭제") or (bool(RE_DELETED.search(text)) and len(text) < 120)
        sub_texts = [text] if len(text) <= MAX_CHARS else split_oversized(text)
        hpath = " > ".join(x for x in [
            f"제{chap_no}장 {chap_title}".strip() if chap_no else None,
            f"제{sec_no}절 {sec_title}".strip() if sec_no else None,
            f"제{cur_art['no']}조" + (f"의{cur_art['ui']}" if cur_art["ui"] else ""),
        ] if x)
        label = f"제{cur_art['no']}조" + (f"의{cur_art['ui']}" if cur_art["ui"] else "")
        for si, st in enumerate(sub_texts):
            tbl_md, tbl_html, tbl_xml = _extract_gfm_tables(st)
            chunks.append(Chunk(
                doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
                enacted=enacted, last_amended=last_amended, unit="조",
                chapter_no=chap_no, chapter_title=chap_title,
                section_no=sec_no, section_title=sec_title,
                article_no=cur_art["no"], article_branch=cur_art["ui"],
                article_label=label, article_title=atitle, hierarchy_path=hpath,
                is_deleted=deleted, has_appendix_ref=bool(RE_APPENDIX.search(text)),
                has_table=bool(tbl_md),
                amendment_dates=parse_amendment_dates(text),
                split_index=si, split_total=len(sub_texts),
                char_len=len(st), text=st,
                table_markdown=tbl_md, table_html=tbl_html, table_xml=tbl_xml,
            ))
        cur_art = None

    for p in paras[body_start:]:
        if RE_BUCHIK.match(p):
            flush_article()
            in_buchik = True
            buchik_lines.append(p)
            continue
        if in_buchik:
            buchik_lines.append(p)
            continue
        mc = RE_CHAP.match(p)
        if mc:
            flush_article()
            chap_no, chap_title = mc.group(1), mc.group(2).strip()
            sec_no = sec_title = None
            continue
        ms = RE_SEC.match(p)
        if ms:
            flush_article()
            sec_no, sec_title = ms.group(1), ms.group(2).strip()
            continue
        ma = RE_ART.match(p)
        if ma:
            flush_article()
            cur_art = {"no": ma.group(1), "ui": ma.group(2), "head": p, "lines": [p]}
            continue
        if cur_art:
            cur_art["lines"].append(p)
    flush_article()

    # 부칙: 부칙 마커 단위로 분할(시행일·경과조치 포함)
    if buchik_lines:
        groups, g = [], []
        for ln in buchik_lines:
            if RE_BUCHIK.match(ln) and g:
                groups.append(g)
                g = [ln]
            else:
                g.append(ln)
        if g:
            groups.append(g)
        for gi, grp in enumerate(groups):
            gtext = "\n".join(grp).strip()
            chunks.append(Chunk(
                doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
                enacted=enacted, last_amended=last_amended, unit="부칙",
                article_label=f"부칙#{gi + 1}", hierarchy_path="부칙",
                has_appendix_ref=bool(RE_APPENDIX.search(gtext)),
                amendment_dates=parse_amendment_dates(gtext),
                char_len=len(gtext), text=gtext,
            ))

    # 문서 레벨 연혁 청크
    hist_text = "\n".join([title] + hist)
    doc_meta = Chunk(
        doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
        enacted=enacted, last_amended=last_amended, unit="연혁",
        article_label="연혁", hierarchy_path="연혁",
        char_len=len(hist_text), text=hist_text,
    )

    result = [doc_meta] + chunks
    _finalize_figures(result)
    for c in result:
        c.chunk_id = f"{c.doc_id}::{c.article_label}::{c.split_index}"
    return result
