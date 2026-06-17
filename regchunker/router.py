# -*- coding: utf-8 -*-
"""문서 패밀리 라우팅: 법규체 vs 공문체.

우선순위:
  1) 파일명 접두/키워드 (가장 신뢰도 높음 — 혼합문서 오분류 방지)
  2) 본문 마커 밀도 (제N조 헤딩 비율 vs 아웃라인 마커 비율)
공문체가 제N조를 '인용'만 하는 경우가 많아 파일명을 먼저 본다.
"""
import re
from typing import List

from .parser import RE_ART
from .patterns import outline_level

# 파일명 키워드 → 패밀리
_LAW_KEYWORDS = ("규정", "정관", "기준", "요령", "지침", "세칙", "내규", "규칙", "규약")
_DOC_KEYWORDS = ("지시문서", "잠정조치", "업무매뉴얼", "업무지도", "매뉴얼",
                 "지도", "공고", "보도자료", "협약", "약칭", "안내", "계획")


def _fname_vote(fname: str):
    """파일명 기반 1차 판정. 결정 불가 시 None."""
    name = re.sub(r"\.HWPX$", "", fname, flags=re.I)
    # 접두 토큰(원문 파일명은 '_'로 분절)에 우선 가중
    head = name.split("_")[0] if "_" in name else name
    for kw in _DOC_KEYWORDS:
        if kw in head:
            return "공문체"
    for kw in _LAW_KEYWORDS:
        if kw in head:
            return "법규체"
    # 접두에서 못 정하면 전체 파일명
    doc_hit = any(kw in name for kw in _DOC_KEYWORDS)
    law_hit = any(kw in name for kw in _LAW_KEYWORDS)
    if doc_hit and not law_hit:
        return "공문체"
    if law_hit and not doc_hit:
        return "법규체"
    return None


def _density_vote(paras: List[str]) -> str:
    """본문 마커 밀도 기반 2차 판정."""
    art = sum(1 for p in paras if RE_ART.match(p))
    outline = sum(1 for p in paras if outline_level(p))
    # 제N조 헤딩이 일정 수 이상이고 아웃라인보다 우세하면 법규체
    if art >= 5 and art >= outline:
        return "법규체"
    return "공문체"


def route_document(fname: str, paras: List[str]) -> str:
    """파일명 우선 → 밀도 보조로 '법규체' | '공문체' 결정."""
    vote = _fname_vote(fname)
    if vote:
        return vote
    return _density_vote(paras)
