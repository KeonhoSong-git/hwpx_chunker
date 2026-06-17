# -*- coding: utf-8 -*-
"""HWPX/HWP에서 단락 텍스트와 표를 '시각(페이지) 순서'로 추출한다.

기존 구현은 Contents/section*.xml을 직접 파싱했으나, XML 삽입 순서가
화면 표시 순서와 달라 본문·표·이미지가 뒤섞이는 한계가 있었다.
이 모듈은 rhwp(러스트 HWP/HWPX 레이아웃 엔진)의 `export-markdown`
서브커맨드를 호출해 페이지 순서대로 렌더된 마크다운을 얻고, 이를
단락 목록과 표(Table)로 다시 파싱한다.

rhwp `export-markdown` 출력 형식:
  · 페이지별 파일  {파일명}_NNN.md (단일 페이지면 {파일명}.md)
  · 본문 단락       빈 줄로 구분된 평문 줄 (아웃라인 마커는 줄머리에 그대로)
  · 표              GFM 마크다운 (| … | + | --- | …), 셀 내 줄바꿈은 <br>
  · 이미지          ![image n](…) 또는 [[RHWP_IMAGE:n]] 토큰 → 제거

공개 API(이전과 동일):
    read_paragraphs(path)              → List[str]
    read_paragraphs_and_tables(path)   → (List[str], List[Table])
    markdown_table_to_html(md)         → str
"""
import glob
import html as _html
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import List, Tuple

from .config import RHWP_BIN

# HWPML paragraph 네임스페이스 (도형/텍스트박스 추출용)
_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_RE_SECTION_XML = re.compile(r"section\d+\.xml$", re.I)
_RE_CIRCLED = re.compile(r"^[①-⑳]")   # ①~⑳로 시작하는 화살표 라벨
_RE_WORD = re.compile(r"[가-힣A-Za-z]")  # 의미 있는 도형 텍스트 판별(글자 포함 여부)

# ── 마크다운 스캔 패턴 ─────────────────────────────────────────────
_RE_GFM_ROW   = re.compile(r"^\s*\|.*\|\s*$")
_RE_GFM_SEP   = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
_RE_MD_IMAGE  = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_IMG_TOKEN = re.compile(r"\[\[RHWP_IMAGE:\d+\]\]")
_RE_BR        = re.compile(r"\s*<br\s*/?>\s*")
_RE_PAGE_NUM  = re.compile(r"_(\d+)\.md$", re.I)
_RE_WS        = re.compile(r"[ \t]+")
_RE_SEP_CELL  = re.compile(r":?-+:?")           # GFM 구분선 셀 판별(HTML 변환용)


# ── rhwp 호출 ─────────────────────────────────────────────────────

def _export_markdown_pages(path: str) -> List[Tuple[int, str]]:
    """rhwp export-markdown 실행 → [(페이지번호, 마크다운본문)] (페이지 오름차순).

    Raises:
        FileNotFoundError: rhwp 바이너리가 없을 때.
        RuntimeError: rhwp 실행 실패 또는 산출물이 없을 때.
    """
    if not os.path.isfile(RHWP_BIN):
        raise FileNotFoundError(
            f"rhwp 바이너리를 찾을 수 없습니다: {RHWP_BIN}\n"
            f"vendor/rhwp에서 `cargo build --release`로 빌드하거나 "
            f"RHWP_BIN 환경변수로 경로를 지정하세요."
        )

    tmp = tempfile.mkdtemp(prefix="rhwp_md_")
    try:
        proc = subprocess.run(
            [RHWP_BIN, "export-markdown", path, "-o", tmp],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"rhwp export-markdown 실패 (코드 {proc.returncode}): {err[:500]}"
            )

        md_files = glob.glob(os.path.join(tmp, "*.md"))
        if not md_files:
            raise RuntimeError(f"rhwp가 마크다운을 생성하지 않았습니다: {path}")

        def page_key(fp: str) -> int:
            m = _RE_PAGE_NUM.search(os.path.basename(fp))
            return int(m.group(1)) if m else 1

        pages: List[Tuple[int, str]] = []
        for fp in sorted(md_files, key=page_key):
            with open(fp, encoding="utf-8") as f:
                pages.append((page_key(fp), f.read()))
        return pages
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _clean_prose(line: str) -> str:
    """본문 줄 정제: 이미지 토큰·<br>·NBSP 제거 후 공백 정리. 빈 줄→''."""
    s = _RE_MD_IMAGE.sub("", line)
    s = _RE_IMG_TOKEN.sub("", s)
    s = _RE_BR.sub(" ", s)
    s = s.replace(" ", " ")
    return _RE_WS.sub(" ", s).strip()


def _clean_cell_row(line: str) -> str:
    """표 행 줄 정제: 셀 내 <br>·이미지 토큰 제거(파이프 구조는 유지)."""
    s = _RE_MD_IMAGE.sub("", line)
    s = _RE_IMG_TOKEN.sub("", s)
    s = _RE_BR.sub(" ", s)
    return s.strip()


def _table_signature(block: List[str]) -> Tuple[str, ...]:
    """표 블록 → 비어있지 않은 셀 내용 튜플(구분선·빈 셀 무시).

    페이지 경계를 넘는 표는 rhwp가 각 페이지마다 같은 표 전체를 다시
    렌더하므로, 빈 행 개수만 다른 '같은 표'를 동일 시그니처로 묶어
    중복 제거에 쓴다.
    """
    cells: List[str] = []
    for row in block:
        if _RE_GFM_SEP.match(row):
            continue
        for c in row.strip().strip("|").split("|"):
            c = c.strip()
            if c:
                cells.append(c)
    return tuple(cells)


# ── HTML 변환(이전과 동일) ─────────────────────────────────────────

def markdown_table_to_html(md: str) -> str:
    """GFM 마크다운 테이블 → HTML <table> 요소 (외부 의존성 없음).

    첫 줄을 헤더(<th>), 나머지를 본문(<td>)으로 변환한다.
    두 번째 줄이 GFM 구분선(|---|)이 아니면 전체를 <td>로 처리한다.
    셀 내용은 html.escape()로 안전하게 이스케이프한다.
    태그 사이 공백/줄바꿈 없이 한 줄로 직렬화한다 — 들여쓰기 공백이
    표 안 텍스트 노드가 되면 일부 렌더러가 표 밖으로 밀어내(foster parenting)
    상단에 빈 줄 덩어리로 표시되는 문제를 막는다.
    """
    lines = [ln.strip() for ln in md.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return f"<pre>{_html.escape(md)}</pre>"

    def parse_row(line: str) -> List[str]:
        return [c.strip() for c in line.strip("|").split("|")]

    def cells(line: str, tag: str) -> str:
        return "".join(f"<{tag}>{_html.escape(c)}</{tag}>" for c in parse_row(line))

    sep_cells = [c.strip() for c in lines[1].strip("|").split("|") if c.strip()]
    is_gfm = bool(sep_cells) and all(_RE_SEP_CELL.fullmatch(c) for c in sep_cells)

    parts: List[str] = ["<table>"]
    if is_gfm:
        parts.append(f"<thead><tr>{cells(lines[0], 'th')}</tr></thead>")
        data_lines = lines[2:]
    else:
        data_lines = lines

    if data_lines:
        parts.append("<tbody>")
        for ln in data_lines:
            parts.append(f"<tr>{cells(ln, 'td')}</tr>")
        parts.append("</tbody>")

    parts.append("</table>")
    return "".join(parts)


def markdown_table_to_xml(md: str) -> str:
    """GFM 마크다운 테이블 → 시맨틱 XML (<table><header|row><cell>…).

    HTML(<table>/<th>/<td>)과 달리 표현 중립적인 행/셀 구조로 직렬화한다.
    헤더 행은 <header>, 본문 행은 <row>로 구분한다(속성 미사용 — JSON 문자열
    그대로 붙여넣어도 \\" 이스케이프 없이 XML 파서가 읽을 수 있게 함).
    태그 사이 공백/줄바꿈 없이 한 줄로 직렬화한다(트리 뷰어에 불필요한
    공백 텍스트 노드가 생기지 않도록). 셀 내용은 이스케이프한다.
    """
    lines = [ln.strip() for ln in md.strip().splitlines() if ln.strip()]
    if not lines:
        return "<table/>"

    def parse_row(line: str) -> List[str]:
        return [c.strip() for c in line.strip("|").split("|")]

    def cells(line: str) -> str:
        return "".join(f"<cell>{_html.escape(c)}</cell>" for c in parse_row(line))

    has_header = False
    if len(lines) >= 2:
        sep_cells = [c.strip() for c in lines[1].strip("|").split("|") if c.strip()]
        has_header = bool(sep_cells) and all(_RE_SEP_CELL.fullmatch(c) for c in sep_cells)

    parts: List[str] = ["<table>"]
    if has_header:
        parts.append(f"<header>{cells(lines[0])}</header>")
        data_lines = lines[2:]
    else:
        data_lines = lines
    for ln in data_lines:
        parts.append(f"<row>{cells(ln)}</row>")
    parts.append("</table>")
    return "".join(parts)


# ── 도형(figure) 직렬화 ────────────────────────────────────────────
# 도형 텍스트는 본문 단락 스트림에 이 접두 토큰을 단 한 줄로 실어 나르다,
# 청크 확정 단계에서 별도 필드(figure_*)로 분리되고 본문 텍스트에선 제거된다.
FIGURE_PREFIX = "[[RHWP_FIGURE]]"
_FIGURE_SEP = " / "


def figure_boxes_from_line(line: str):
    """단락 줄이 도형 토큰이면 박스 텍스트 리스트, 아니면 None."""
    if not line.startswith(FIGURE_PREFIX):
        return None
    body = line[len(FIGURE_PREFIX):]
    return [b for b in body.split(_FIGURE_SEP) if b]


def figure_to_markdown(boxes: List[str]) -> str:
    """도형 박스 리스트 → 마크다운 불릿 목록."""
    return "\n".join(f"- {b}" for b in boxes)


def figure_to_html(boxes: List[str]) -> str:
    """도형 박스 리스트 → HTML <figure>(공백·줄바꿈 없이 한 줄)."""
    items = "".join(f"<li>{_html.escape(b)}</li>" for b in boxes)
    return f'<figure class="diagram"><ul>{items}</ul></figure>'


def figure_to_xml(boxes: List[str]) -> str:
    """도형 박스 리스트 → 시맨틱 XML <figure>(속성·공백 미사용, 한 줄)."""
    items = "".join(f"<item>{_html.escape(b)}</item>" for b in boxes)
    return f"<figure>{items}</figure>"


# ── 표 데이터 컨테이너 ─────────────────────────────────────────────

@dataclass
class Table:
    """HWPX 문서에서 추출한 단일 표.

    Attributes:
        section:   추출 원본 페이지 식별자 (예: page003)
        table_idx: 문서 내 0-based 순번
        markdown:  GFM 마크다운 형식 텍스트
    """
    section: str
    table_idx: int
    markdown: str

    def to_html(self) -> str:
        """마크다운 → HTML <table> 요소 문자열."""
        return markdown_table_to_html(self.markdown)


# ── 도형/텍스트박스(drawing object) 텍스트 복구 ────────────────────
# rhwp 백엔드는 흐름도·조직도 등 도형 그룹(<hp:drawText>)을 마크다운·SVG
# 양쪽에서 통째로 버린다. 원본 HWPX(zip)의 section XML을 직접 읽어 도형
# 텍스트를 문서 순서대로 복구하고, 각 도형이 박힌 '직전 본문'을 앵커로
# rhwp 단락 스트림의 해당 위치에 끼워넣는다(위치 보존).

def _drawing_object_blocks(path: str) -> List[Tuple[str, List[str]]]:
    """HWPX의 도형 텍스트 블록을 [(앵커본문, [박스텍스트…])] 로 반환.

    앵커본문 = 도형 그룹 직전에 나온 본문 텍스트(문서 순서). 도형이 표 셀
    안에 박혀 있어도 셀 텍스트가 앵커가 되어 올바른 위치를 가리킨다.
    HWPX(zip)가 아니거나 파싱 실패 시 [] 반환(rhwp 본문은 영향 없음).
    """
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return []
    blocks: List[Tuple[str, List[str]]] = []
    seen: set = set()                        # 동일 박스셋 중복 도형 방지
    with zf:
        secs = sorted(n for n in zf.namelist() if _RE_SECTION_XML.search(n))
        for name in secs:
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError:
                continue
            events: List[Tuple[str, str]] = []   # ('body'|'box', text)

            def walk(el):
                if el.tag == _HP + "drawText":
                    box = "".join(t.text or "" for t in el.iter(_HP + "t")).strip()
                    if box:
                        events.append(("box", box))
                    return                       # 도형 내부 단락은 박스로만 취급
                if el.tag == _HP + "t" and el.text:
                    events.append(("body", el.text))
                for child in el:
                    walk(child)

            walk(root)
            i = 0
            while i < len(events):
                if events[i][0] != "box":
                    i += 1
                    continue
                start = i
                boxes: List[str] = []
                while i < len(events) and events[i][0] == "box":
                    boxes.append(events[i][1])
                    i += 1
                # 도형 그룹 직전의 연속 본문 텍스트 = 앵커
                anc: List[str] = []
                k = start - 1
                while k >= 0 and events[k][0] == "body":
                    anc.append(events[k][1])
                    k -= 1
                anchor = "".join(reversed(anc)).strip()
                # 글자(한글/영문)가 있는 박스만 유지 — 스크린샷 위 ①②③ 콜아웃
                # 같은 마커-only 도형은 의미 텍스트가 없어 노이즈이므로 버린다.
                kept = [b for b in _order_boxes(boxes) if _RE_WORD.search(b)]
                if kept:
                    fp = tuple(kept)
                    if fp not in seen:
                        seen.add(fp)
                        blocks.append((anchor, kept))
    return blocks


def _order_boxes(boxes: List[str]) -> List[str]:
    """도형 박스를 읽기 좋게 정렬: 일반 라벨(노드) 먼저, ①②③ 화살표는 번호순."""
    nodes = [b for b in boxes if not _RE_CIRCLED.match(b)]
    arrows = [b for b in boxes if _RE_CIRCLED.match(b)]
    arrows.sort(key=lambda b: ord(b[0]))     # ①=0x2460 … ⑳ 순
    return nodes + arrows


def _splice_drawing_blocks(paras: List[str], blocks: List[Tuple[str, List[str]]]) -> None:
    """도형 텍스트 블록을 앵커 본문 바로 뒤(없으면 끝)에 끼워넣는다(in-place)."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", "", s)

    search_from = 0
    head = 0                                  # 빈 앵커(문서 맨앞 도형) 삽입 커서
    for anchor, boxes in blocks:
        if not boxes:
            continue
        block_text = FIGURE_PREFIX + _FIGURE_SEP.join(boxes)
        nanchor = norm(anchor)
        if not nanchor:                      # 선행 본문 없음 = 문서 시작(표지 등)
            paras.insert(head, block_text)
            head += 1
            search_from = max(search_from, head)
            continue
        # 앵커가 여러 rhwp 단락에 걸칠 수 있어 꼬리를 점진 축소하며 매칭한다.
        pos = -1
        for klen in (28, 18, 12, 8, 5):
            key = nanchor[-klen:]
            for idx in range(search_from, len(paras)):
                if key in norm(paras[idx]):
                    pos = idx
                    break
            if pos >= 0:
                break
        if pos >= 0:
            paras.insert(pos + 1, block_text)
            search_from = pos + 2            # 다음 도형은 이 뒤에서 탐색
        else:
            paras.append(block_text)         # 앵커 매칭 실패 시 유실 방지로 끝에 추가


# ── 공개 API ──────────────────────────────────────────────────────

def read_paragraphs_and_tables(path: str) -> Tuple[List[str], List[Table]]:
    """HWPX/HWP 파일 경로 → (단락/테이블 텍스트 목록, Table 객체 목록).

    rhwp로 페이지 순서대로 렌더한 마크다운을 파싱한다. 표는 GFM 마크다운
    문자열로 단락 목록에도 포함되어 청크 맥락을 유지하며, 동시에 Table
    객체 목록에도 별도 수집된다.

    Raises:
        FileNotFoundError: rhwp 바이너리가 없을 때.
        RuntimeError: rhwp 실행 실패 또는 산출물이 없을 때.
    """
    paras: List[str] = []
    tables: List[Table] = []
    prev_tbl_sig: Tuple[str, ...] = ()   # 직전(연속) 표 시그니처 — 페이지 경계 중복 제거용

    for page_num, content in _export_markdown_pages(path):
        lines = content.splitlines()
        i, n = 0, len(lines)
        while i < n:
            # ── 표 블록: |…| 줄 + 다음 줄이 GFM 구분선 ──────────────
            if (
                _RE_GFM_ROW.match(lines[i])
                and i + 1 < n
                and _RE_GFM_SEP.match(lines[i + 1])
            ):
                block: List[str] = []
                while i < n and _RE_GFM_ROW.match(lines[i]):
                    block.append(_clean_cell_row(lines[i]))
                    i += 1
                sig = _table_signature(block)
                # 페이지를 가로지르는 표는 페이지마다 전체가 재렌더되므로,
                # 본문 사이 없이 연속으로 같은 내용이 또 나오면 건너뛴다.
                if sig and sig == prev_tbl_sig:
                    continue
                prev_tbl_sig = sig
                md = "\n".join(block)
                tables.append(
                    Table(section=f"page{page_num:03d}",
                          table_idx=len(tables), markdown=md)
                )
                paras.append(md)
                continue

            # ── 본문 줄 ──────────────────────────────────────────────
            txt = _clean_prose(lines[i])
            if txt:
                paras.append(txt)
                prev_tbl_sig = ()   # 본문이 끼면 연속성 끊김
            i += 1

    # rhwp가 누락한 도형/텍스트박스 텍스트를 원본 XML에서 복구해 끼워넣는다.
    _splice_drawing_blocks(paras, _drawing_object_blocks(path))

    return paras, tables


def read_paragraphs(path: str) -> List[str]:
    """HWPX/HWP 파일 경로 → 비어있지 않은 단락/테이블 텍스트 리스트.

    표(<hp:tbl>)는 GFM 마크다운 테이블 형식으로 변환해 단일 항목으로 포함한다.
    표 객체가 필요하면 read_paragraphs_and_tables()를 사용한다.

    Raises:
        FileNotFoundError: rhwp 바이너리가 없을 때.
        RuntimeError: rhwp 실행 실패 또는 산출물이 없을 때.
    """
    paras, _ = read_paragraphs_and_tables(path)
    return paras
