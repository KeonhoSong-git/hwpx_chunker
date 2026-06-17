# -*- coding: utf-8 -*-
"""도해·플로우차트 잔재 정규화 패스.

HWPX의 hp:drawText(벡터 도형 텍스트)와 표+글리프형 흐름도가
read_paragraphs를 거치면 다음 형태로 깨진다:
  1) 화살표·PUA 글리프(화살표 + U+F00x)가 단락에 섞임
  2) 세로쓰기 라벨이 한 글자씩 단락으로 흩어짐('수','출','자')
  3) 번호 라벨(원문자)이 도형 배치 순서대로 뒤섞여 등장
정규화 목표: 잡음 글리프 제거 -> 세로쓰기 재조립 -> 번호순 정렬.
"""
import re
from typing import List, Tuple

# 화살표·도형 글리프(흐름 방향 표시). 의미는 메타로 보존하되 본문에선 제거.
_ARROW_GLYPHS = (
    "←↑→↓↔↕"   # ← ↑ → ↓ ↔ ↕
    "⇐⇒⇑⇓"               # ⇐ ⇒ ⇑ ⇓
    "▶◀▲▼▴▾"   # ▶ ◀ ▲ ▼ ▴ ▾
    "◂▸◁▷"               # ◂ ▸ ◁ ▷
    "↗↘↙↖"               # ↗ ↘ ↙ ↖
    "➡⟶⟵"                     # ➡ ⟶ ⟵
)
_RE_ARROW = re.compile("[" + re.escape(_ARROW_GLYPHS) + "]")
# 사설 사용 영역(PUA) — HWP 전용 글리프가 박히는 구간
# BMP: U+E000~U+F8FF / 보충 사설 영역: U+F0000~U+FFFFD, U+100000~U+10FFFD
_RE_PUA = re.compile("[-\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
# 원문자 ①~⑳ (U+2460 ~ U+2473)
_RE_CIRCLED = re.compile("[①-⑳]")
_CIRCLED_BASE = 0x2460


def strip_glyphs(text: str) -> str:
    """화살표·PUA 글리프 제거 후 공백 정리."""
    text = _RE_ARROW.sub(" ", text)
    text = _RE_PUA.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# 잡음 글리프(객체대체문자 ￼·BMP PUA·보충PUA·제로폭·방향제어·소프트하이픈) 통합 제거.
# strip_glyphs 가 놓치던 U+FFFC(Specials)·BMP PUA(E000~F8FF)까지 포함.
_RE_JUNK = re.compile(
    "[­​-‏‪-‮⁠﻿"      # 소프트하이픈·제로폭·방향제어
    "-"                                      # BMP 사설사용영역
    "\U000f0000-\U000ffffd\U00100000-\U0010fffd"         # 보충 사설사용영역
    "￹-�]"                                     # Specials (U+FFFC 객체대체문자 포함)
)


# 기계 플레이스홀더 마커: [[RHWP_FIGURE]] 등 [[대문자_토큰]] (도해/그림 자리). 본문에서 제거.
# (<<화면 개요>> 처럼 작성자가 쓴 한글 강조는 내용이므로 건드리지 않는다.)
_RE_MARK = re.compile(r"\[\[[A-Z][A-Z0-9_]*\]\]")


def scrub(text: str):
    """본문/라벨용 최종 정리: 잡음 글리프 제거 + 과다 공백 축소. 의미 문자는 보존."""
    if not isinstance(text, str) or not text:
        return text
    text = _RE_JUNK.sub("", text)
    text = _RE_MARK.sub("", text)
    text = re.sub(r"[ \t ]{2,}", " ", text)
    return text.strip()


def circled_to_int(ch: str):
    """'①'->1 … '⑳'->20. 아니면 None."""
    if _RE_CIRCLED.fullmatch(ch):
        return ord(ch) - _CIRCLED_BASE + 1
    return None


def reassemble_vertical(paras: List[str], min_run: int = 3, max_len: int = 2) -> List[str]:
    """세로쓰기로 흩어진 초단문 단락을 한 토큰으로 재조립.

    연속한 '길이<=max_len' 단락이 min_run개 이상이면 이어붙여 하나로 본다.
    예: ['수','출','자'] -> ['수출자'].  그 외 단락은 그대로 보존.
    """
    out: List[str] = []
    i, n = 0, len(paras)
    while i < n:
        j = i
        while j < n and 0 < len(paras[j].strip()) <= max_len:
            j += 1
        if j - i >= min_run:
            out.append("".join(p.strip() for p in paras[i:j]))
            i = j
        else:
            out.append(paras[i])
            i += 1
    return out


def sort_numbered_steps(items: List[str]) -> List[str]:
    """원문자 라벨이 붙은 단계들을 번호순으로 정렬.

    번호가 없는 항목은 원래 상대순서를 유지해 뒤로 보낸다(안정 정렬).
    """
    def key(idx_item: Tuple[int, str]):
        idx, item = idx_item
        m = _RE_CIRCLED.search(item)
        if m:
            return (0, circled_to_int(m.group(0)), idx)
        return (1, 0, idx)

    return [it for _, it in sorted(enumerate(items), key=key)]


def normalize_figure_labels(paras: List[str]) -> List[str]:
    """도형 라벨 단락 묶음 정규화: 글리프 제거 -> 세로쓰기 재조립 -> 번호 정렬."""
    cleaned = [c for c in (strip_glyphs(p) for p in paras) if c]
    merged = reassemble_vertical(cleaned)
    return sort_numbered_steps(merged)
