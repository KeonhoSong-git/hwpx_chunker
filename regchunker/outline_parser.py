# -*- coding: utf-8 -*-
"""공문·매뉴얼체 문서 구조 파싱 -> 아웃라인 단위 청크 생성.

골격: 제목 + 문서번호 연혁 / 수신·발신 / 시달문 / (목차) / 본문(Ⅰ·1·가·…) / 붙임.
기본 청크 단위 = 최상위 아웃라인 절(대단원). 과대 절은 길이 경계로 2차 분할.
표·도해는 격리하지 않고 본문 청크에 has_table/has_figure 플래그로 표시한다.
"""
import re
from typing import List, Optional

from .config import MAX_CHARS, MIN_CHARS
from .parser import (Chunk, make_doc_id, infer_doc_type, parse_amendment_dates,
                     RE_ART, pick_title, _extract_gfm_tables, _finalize_figures)
from .normalize import normalize_figure_labels, strip_glyphs, _RE_ARROW, _RE_CIRCLED
from .patterns import (
    outline_level, marker_ordinal, is_toc_entry,
    RE_DOC_HISTORY, RE_RECIPIENT, RE_SENDER, RE_DISPATCH_END,
    RE_NEXT_MARKER, RE_ATTACH, RE_ATTACH_HEADER, RE_APPENDIX_REF,
    RE_TOC_HEADER, RE_BARE_ROMAN,
)


def _is_attach_boundary(p: str) -> bool:
    """별첨 그룹 경계 판정: 콜론형 목록 줄 OR 괄호형 섹션 헤더."""
    return bool(RE_ATTACH.match(p) or RE_ATTACH_HEADER.match(p))


def _merge_bare_roman(body):
    """맨몸 로마 마커('Ⅰ') + 다음 줄(제목)을 'Ⅰ. 제목' 한 줄로 합친다.

    매뉴얼류는 대단원 로마숫자를 단독 줄에 두고 제목을 다음 줄에 둔다.
    합쳐야 outline_level이 최상위(로마)로 인식해 절 경계를 잡는다.
    """
    out = []
    i, n = 0, len(body)
    while i < n:
        idx, p = body[i]
        m = RE_BARE_ROMAN.match(p)
        if m and i + 1 < n:
            nxt_idx, nxt = body[i + 1]
            if not RE_BARE_ROMAN.match(nxt) and not outline_level(nxt):
                out.append((idx, f"{m.group(1)}. {nxt.strip()}"))
                i += 2
                continue
        out.append((idx, p))
        i += 1
    return out


def _detect_toc(paras: List[str]):
    """목차 영역 인덱스 집합 반환.

    1) '목 차' 헤더 뒤로 페이지번호로 끝나는 항목 줄이 연속하는 구간.
    2) 헤더가 없어도 항목 줄이 5개+ 연속이면 목차로 간주.
    """
    n = len(paras)
    # 성능: is_toc_entry 결과를 미리 계산해 중복 호출 제거
    toc_flags = [is_toc_entry(p) for p in paras]

    idx: set = set()
    i = 0
    while i < n:
        if RE_TOC_HEADER.match(paras[i]):
            j = i + 1
            run: List[int] = []
            miss = 0
            while j < n:
                if toc_flags[j] or len(paras[j].strip()) <= 2:
                    run.append(j)
                    miss = 0
                else:
                    miss += 1
                    if miss >= 2:
                        break
                    run.append(j)
                j += 1
            # 항목으로 끝나도록 꼬리의 비항목 줄 잘라내기
            while run and not toc_flags[run[-1]]:
                run.pop()
            if sum(1 for k in run if toc_flags[k]) >= 3:
                idx.add(i)
                idx.update(run)
                i = (run[-1] + 1) if run else j
                continue
        i += 1

    # 헤더 없는 목차: 항목 줄 5개+ 연속
    run_start = None
    for k in range(n):
        if toc_flags[k]:
            if run_start is None:
                run_start = k
        else:
            if run_start is not None and k - run_start >= 5:
                idx.update(range(run_start, k))
            run_start = None
    if run_start is not None and n - run_start >= 5:
        idx.update(range(run_start, n))
    return idx


def _looks_tabular(lines: List[str]) -> bool:
    """연속한 짧은 셀 단락이 표로 흩어진 흔적인지 판정."""
    run = best = 0
    for ln in lines:
        if 0 < len(ln.strip()) <= 15 and not ln.strip().endswith("."):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best >= 4


def _looks_figure(lines: List[str]) -> bool:
    """화살표 글리프 또는 흩어진 번호·초단문 라벨이 많으면 도해로 판정."""
    arrows = sum(1 for ln in lines if _RE_ARROW.search(ln))
    circled = sum(1 for ln in lines if _RE_CIRCLED.search(ln))
    tiny = sum(1 for ln in lines if 0 < len(ln.strip()) <= 2)
    return arrows >= 2 or (circled >= 3 and tiny >= 3) or tiny >= 6


def _pack(lines: List[str], max_chars: int, ctx: str) -> List[str]:
    """라인들을 max_chars 이하 덩어리로 패킹. 분할 시 ctx(헤딩)를 머리에 유지.

    NOTE: cur를 ctx로 초기화하지 않는다.
    lines[0]이 ctx와 같을 때 헤딩이 중복되는 버그를 방지한다.
    분할이 필요한 구간에서만 새 청크의 첫 줄에 ctx를 붙인다.
    """
    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return [text]
    ctx_clean = ctx.strip()
    out: List[str] = []
    cur = ""
    for ln in lines:
        if not cur:                              # 첫 줄 또는 분할 직후
            cur = ln.strip()
            continue
        cand = (cur + "\n" + ln).strip()
        if len(cand) > max_chars and cur != ctx_clean:
            out.append(cur)
            cur = (ctx_clean + "\n" + ln).strip()
        else:
            cur = cand
    if cur.strip():
        out.append(cur)
    return out


def _attach_top_level(lines: List[str]):
    """별첨 본문 lines의 내부 최상위 아웃라인 레벨 인덱스. 마커 없으면 None."""
    levels = [lv[1] for lv in (outline_level(p) for p in lines) if lv]
    return min(levels) if levels else None


def _split_attach_sections(lines: List[str], top_idx: int) -> List[List[str]]:
    """별첨 본문을 내부 최상위 절(Ⅰ/1/가 …) 단위로 분할.

    본문 세그멘테이션과 동일한 연속성 검사(1,2,3… 순서를 잇는 마커만 절 경계로
    승격, 1로 리셋되는 중첩 목록은 흡수)를 적용한다. 첫 절 앞 서문(제목 줄 등)은
    첫 절에 합쳐 보존한다.
    """
    sections: List[List[str]] = []
    preamble: List[str] = []
    cur: List[str] = []
    expected = None
    started = False
    for p in lines:
        lv = outline_level(p)
        is_top = lv is not None and lv[1] <= top_idx
        if is_top:
            num = marker_ordinal(lv[0], lv[2])
            if num is None:
                is_top = not started          # 서수 해석 실패 → 첫 절만 경계로
            elif expected is None:
                expected = num + 1
            elif num == expected:
                expected = num + 1
            else:
                is_top = False                # 비연속 → 중첩 목록으로 흡수
        if is_top:
            if cur:
                sections.append(cur)
            cur = [p]
            started = True
        elif started:
            cur.append(p)
        else:
            preamble.append(p)
    if cur:
        sections.append(cur)
    if preamble:
        if sections:
            sections[0] = preamble + sections[0]
        else:
            sections = [preamble]
    return sections


def parse_outline_document(paras: List[str], fname: str) -> List[Chunk]:
    """단락 리스트 -> Chunk 리스트(연혁/헤더 + 본문 N + 붙임 M [+ 목차])."""
    if not paras:
        return []
    title = pick_title(paras, fname)
    doc_id = make_doc_id(fname)
    doc_type = infer_doc_type(title)
    chunks: List[Chunk] = []

    toc_idx = _detect_toc(paras)

    # ── 프런트매터 수집: 연혁 / 수신 / 발신 / 시달문 종결 ──
    history: List[str] = []
    recipient = sender = ""
    dispatch_end = -1
    next_marker = -1
    for i, p in enumerate(paras):
        if i in toc_idx:
            continue
        if RE_NEXT_MARKER.match(p) and next_marker < 0:
            next_marker = i
        if RE_DOC_HISTORY.search(p) and i < 30:
            history.append(p)
        mr = RE_RECIPIENT.match(p)
        if mr and not recipient:
            recipient = mr.group(2).strip()
        ms = RE_SENDER.match(p)
        if ms and not sender:
            sender = ms.group(2).strip()
        if RE_DISPATCH_END.search(p) and i < 40:
            dispatch_end = i

    enacted = next((h for h in history if re.search(r"제\s*정", h)), history[0] if history else "")
    last_amended = history[-1] if history else ""

    # ── 본문 시작 위치 결정 ──
    body_start = 1
    if next_marker >= 0:
        body_start = next_marker + 1
    elif dispatch_end >= 0:
        body_start = dispatch_end + 1
    # 붙임 시작 위치
    attach_start = next((i for i in range(body_start, len(paras))
                         if i not in toc_idx and _is_attach_boundary(paras[i])), len(paras))

    body = [(i, paras[i]) for i in range(body_start, attach_start) if i not in toc_idx]
    body = _merge_bare_roman(body)
    attach = [(i, paras[i]) for i in range(attach_start, len(paras)) if i not in toc_idx]

    # ── 최상위 레벨 결정(roman 우선, 없으면 num) ──
    levels_present = []
    top_name = None
    for _, p in body:
        lv = outline_level(p)
        if lv:
            levels_present.append(lv[1])
    top_idx = min(levels_present) if levels_present else None
    if top_idx is not None:
        from .patterns import OUTLINE_LEVELS
        top_name = OUTLINE_LEVELS[top_idx][0]
    top_ordered = top_name in ("roman", "num", "han", "enum")

    # ── 헤더(프런트매터) 청크 ──
    header_lines = [paras[i] for i in range(0, body_start) if i not in toc_idx]
    header_text = "\n".join(header_lines).strip()
    if header_text:
        chunks.append(Chunk(
            doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
            doc_family="공문체", unit="헤더", enacted=enacted, last_amended=last_amended,
            article_label="헤더", hierarchy_path="헤더",
            recipient=recipient, sender=sender,
            amendment_dates=parse_amendment_dates(header_text),
            char_len=len(header_text), text=header_text,
        ))

    # ── 본문 세그멘테이션(최상위 절 단위) ──
    def emit_section(heading: str, sec_lines: List[str], seq: int):
        if not heading and not sec_lines:
            return
        all_lines = ([heading] if heading else []) + sec_lines
        has_table = _looks_tabular(all_lines)
        has_figure = _looks_figure(all_lines)
        if has_figure:
            # 화살표·PUA 글리프 제거 + 세로쓰기 재조립만 수행.
            # "[도해]" 인공 마커는 text에 주입하지 않음 — has_figure 필드로 충분.
            labels = normalize_figure_labels(sec_lines)
            text_lines = ([heading] if heading else []) + (labels or sec_lines)
        else:
            text_lines = all_lines
        ctx = heading or (sec_lines[0] if sec_lines else "")
        # _pack 단 한 번 호출 → split_total 정확히 계산
        splits = _pack(text_lines, MAX_CHARS, ctx)
        split_total = len(splits)
        for si, st in enumerate(splits):
            if len(st) < MIN_CHARS:          # 극소 청크 → 임베딩 품질 저하 방지
                continue
            tbl_md, tbl_html, tbl_xml = _extract_gfm_tables(st)
            chunks.append(Chunk(
                doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
                doc_family="공문체", unit="본문", enacted=enacted, last_amended=last_amended,
                article_label=(heading[:40] if heading else f"본문#{seq}"),
                article_title=heading[:60] if heading else "",
                hierarchy_path=heading[:60] if heading else f"본문#{seq}",
                recipient=recipient, sender=sender,
                has_appendix_ref=bool(RE_APPENDIX_REF.search(st)),
                has_table=has_table or bool(tbl_md), has_figure=has_figure,
                amendment_dates=parse_amendment_dates(st),
                split_index=si, split_total=split_total,
                char_len=len(st), text=st,
                table_markdown=tbl_md, table_html=tbl_html, table_xml=tbl_xml,
            ))

    seq = 0
    cur_head: Optional[str] = None
    cur_lines: List[str] = []
    expected = None                 # 정렬형 최상위 절의 다음 기대 서수
    in_article = False              # 본문에 박힌 규정(제N조) 영역 진입 여부
    for _, p in body:
        # (a) 제N조 헤딩 = 무조건 절 경계. 본문에 박힌 규정/협약을 조 단위로 분절.
        if RE_ART.match(p):
            if cur_head is not None or cur_lines:
                seq += 1
                emit_section(cur_head, cur_lines, seq)
            cur_head, cur_lines = p, []
            in_article = True       # 이후 1.2.3.은 호·목이므로 절로 승격 금지
            continue
        # (b) 아웃라인 최상위 마커
        lv = outline_level(p)
        is_top = lv is not None and top_idx is not None and lv[1] <= top_idx
        if is_top and in_article:
            is_top = False          # 규정 영역 내부에서는 흡수(호·목)
        elif is_top and top_ordered:
            # 연속성 검사: 1,2,3… 순서를 이어가는 마커만 새 절로 승격.
            # 중첩 목록이 1로 리셋되는 경우(예: 정의 1.2.3.)는 본문에 흡수.
            num = marker_ordinal(lv[0], lv[2])
            if num is None:
                pass                # 서수 해석 실패 → 일반 절로 취급
            elif expected is None:
                expected = num + 1
            elif num == expected:
                expected = num + 1
            else:
                is_top = False      # 비연속 → 중첩 목록으로 보고 흡수
        if is_top:
            if cur_head is not None or cur_lines:
                seq += 1
                emit_section(cur_head, cur_lines, seq)
            cur_head, cur_lines = p, []
            in_article = False      # 새 최상위 절 시작 → 이전 조문 영역 종료
        else:
            cur_lines.append(p)
    if cur_head is not None or cur_lines:
        seq += 1
        emit_section(cur_head, cur_lines, seq)

    # ── 붙임/별첨 청크 ──
    if attach:
        groups: List[List[str]] = []
        g: List[str] = []
        for _, p in attach:
            if _is_attach_boundary(p) and g:
                groups.append(g)
                g = [p]
            else:
                g.append(p)
        if g:
            groups.append(g)
        for gi, grp in enumerate(groups):
            has_table = _looks_tabular(grp)
            head = grp[0]

            # 대형 참고자료성 별첨(길이 초과 + 내부 최상위 절 2개+)은 길이 대신
            # 내부 절(Ⅰ/1/가 …) 구조로 분할해 문단 중간 절단을 피한다.
            # 구조가 뚜렷하면 도해 판정·라벨 재정렬보다 우선한다(텍스트 본문 오판 방지).
            sections = None
            if len("\n".join(grp)) > MAX_CHARS:
                from .patterns import OUTLINE_LEVELS
                t_idx = _attach_top_level(grp[1:])
                # roman/num(Ⅰ·1 = 문서 절 헤딩)만 구조 분할 트리거.
                # han(가)·enum(①)은 항목/단계 수준이라 흐름도·목록을 과분할시킴.
                if t_idx is not None and OUTLINE_LEVELS[t_idx][0] in ("roman", "num"):
                    secs = _split_attach_sections(grp[1:], t_idx)
                    if len(secs) >= 2:
                        sections = secs

            if sections is not None:
                has_figure = False              # 구조 뚜렷 → 도해 아님
                splits = []
                for sec in sections:
                    splits.extend(_pack([head] + sec, MAX_CHARS, sec[0]))
            else:
                has_figure = _looks_figure(grp)
                if has_figure:
                    labels = normalize_figure_labels(grp[1:])
                    gtext = "\n".join([head] + (labels or grp[1:])).strip()
                else:
                    gtext = "\n".join(grp).strip()
                # _pack 단 한 번 호출 → split_total 정확히 계산
                splits = _pack(gtext.split("\n"), MAX_CHARS, head)
            split_total = len(splits)
            for si, st in enumerate(splits):
                if len(st) < MIN_CHARS:
                    continue
                tbl_md, tbl_html, tbl_xml = _extract_gfm_tables(st)
                chunks.append(Chunk(
                    doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
                    doc_family="공문체", unit="붙임", enacted=enacted, last_amended=last_amended,
                    article_label=f"붙임#{gi + 1}", article_title=head[:60],
                    hierarchy_path=f"붙임#{gi + 1}",
                    recipient=recipient, sender=sender,
                    has_appendix_ref=True, has_table=has_table or bool(tbl_md), has_figure=has_figure,
                    char_len=len(st), text=st,
                    split_index=si, split_total=split_total,
                    table_markdown=tbl_md, table_html=tbl_html, table_xml=tbl_xml,
                ))

    # ── 목차 청크(격리, 비분할) ──
    if toc_idx:
        toc_text = "\n".join(paras[i] for i in sorted(toc_idx)).strip()
        if toc_text:
            chunks.append(Chunk(
                doc_id=doc_id, doc_title=title, doc_type=doc_type, source_file=fname,
                doc_family="공문체", unit="목차", article_label="목차",
                hierarchy_path="목차", char_len=len(toc_text), text=toc_text,
            ))

    _finalize_figures(chunks)
    for c in chunks:
        c.chunk_id = f"{c.doc_id}::{c.article_label}::{c.split_index}"
    return chunks
