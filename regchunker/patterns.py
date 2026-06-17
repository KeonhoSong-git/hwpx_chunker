# -*- coding: utf-8 -*-
"""공문·매뉴얼체(아웃라인) 문서용 공유 패턴 모음.

법규체(parser.py)와 분리해 outline_parser/router/normalize가 공유한다.
아웃라인 마커 위계(상→하):
    Ⅰ.Ⅱ (로마, ASCII I./II. 포함)
  > 1. 2.        (아라비아)
  > 가. 나.       (한글)
  > □ ■          (사각)
  > ○ ● ㅇ ◦      (원)
  > - ⁃ ∙ · ▪ ‣ ※ ☞ ▷ ▶ △  (대시·기타 글머리)
  > ① ~ ⑳ / (1)(2) / 1)2)    (열거 항목)
"""
import re

# ── 아웃라인 마커(레벨별) ──────────────────────────────────────────
# 레벨 0: 로마숫자 대단원.  Ⅰ Ⅱ … (유니코드) + I. II. … (ASCII)
RE_LV_ROMAN = re.compile(
    r"^\s*(?:([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)|([IVX]{1,4}))[.\．·)]\s*(.*)$"
)
# 레벨 1: 1. 2. 3.  (대제목)
RE_LV_NUM = re.compile(r"^\s*(\d{1,2})[.\．](?!\d)\s*(.*)$")
# 레벨 2: 가. 나. … 하.
RE_LV_HAN = re.compile(r"^\s*([가-힣])[.\．)]\s*(.*)$")
# 레벨 3: □ ■ ◇ ◆
RE_LV_BOX = re.compile(r"^\s*([□■◇◆])\s*(.*)$")
# 레벨 4: ○ ● ㅇ ◦ ∘
RE_LV_CIRCLE = re.compile(r"^\s*([○●ㅇ◦∘])\s*(.*)$")
# 레벨 5: 대시·기타 글머리표
RE_LV_DASH = re.compile(r"^\s*([-‐⁃∙·•▪▫‣※☞▷▶◈△▴])\s*(.*)$")
# 레벨 6: 열거 항목  ① / (1) / 1)
RE_LV_ENUM = re.compile(r"^\s*([①-⑳]|\(\d{1,2}\)|\d{1,2}\))\s*(.*)$")

# 레벨 0..6 순서대로(라우팅·세그멘테이션에서 사용)
OUTLINE_LEVELS = [
    ("roman", RE_LV_ROMAN),
    ("num", RE_LV_NUM),
    ("han", RE_LV_HAN),
    ("box", RE_LV_BOX),
    ("circle", RE_LV_CIRCLE),
    ("dash", RE_LV_DASH),
    ("enum", RE_LV_ENUM),
]

# 줄 전체가 로마숫자 마커뿐인 '맨몸 마커'(제목은 다음 줄에 옴)
RE_BARE_ROMAN = re.compile(r"^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+)[.\．·)]?\s*$")

_ROMAN_MAP = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5,
              "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10,
              "I": 1, "V": 5, "X": 10}


def outline_level(line: str):
    """단락 한 줄 → (레벨이름, 레벨인덱스, 마커, 본문) 또는 None."""
    for idx, (name, rx) in enumerate(OUTLINE_LEVELS):
        m = rx.match(line)
        if not m:
            continue
        if name == "roman":
            marker = m.group(1) or m.group(2)
            body = m.group(3)
            # 'I am ...' 같은 영문 오탐 방지: 본문이 한글/숫자로 시작하거나 짧을 때만
            if m.group(2) and not _looks_like_heading(body):
                continue
            return (name, idx, marker, body.strip())
        marker, body = m.group(1), m.group(2)
        return (name, idx, marker, body.strip())
    return None


def _looks_like_heading(body: str) -> bool:
    b = body.strip()
    if not b:
        return True
    # 한글 포함 또는 콜론/괄호로 끝나는 짧은 제목 형태면 헤딩으로 인정
    return bool(re.search(r"[가-힣]", b)) or len(b) <= 40


def roman_value(marker: str) -> int:
    """로마 마커 → 정수(정렬용). 매핑 실패 시 0."""
    if marker in _ROMAN_MAP and len(marker) == 1:
        return _ROMAN_MAP[marker]
    val, prev = 0, 0
    for ch in reversed(marker):
        cur = _ROMAN_MAP.get(ch, 0)
        if cur < prev:
            val -= cur
        else:
            val += cur
            prev = cur
    return val


# ── 공문 골격 패턴 ────────────────────────────────────────────────
# 문서번호 연혁: 부서-번호(YYYY.MM.DD) / 제정·개정 줄
RE_DOC_HISTORY = re.compile(
    r"(제\s*정|개\s*정|전부개정|일부개정|시\s*행)"
    r"|([가-힣A-Za-z]+\s*-\s*\d+\s*[\(（]\s*\d{4}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2})"
)
RE_RECIPIENT = re.compile(r"^\s*(수\s*신|받는\s*곳|수신자)\s*[:：]?\s*(.*)$")
RE_SENDER = re.compile(r"^\s*(발\s*신|보내는\s*곳|발신명의)\s*[:：]?\s*(.*)$")
# 시달문 종결: '…바랍니다', '…하시기 바랍니다', '통보합니다' 등
RE_DISPATCH_END = re.compile(r"(바랍니다|바람니다|통보합니다|알려드립니다|시달합니다)\.?\s*$")
# '다 음' / '- 다 음 -' 본문 시작 표지
RE_NEXT_MARKER = re.compile(r"^\s*[-‐]?\s*다\s*음\s*[-‐]?\s*$")
# 붙임/별첨/별지 (콜론형 목록 줄 + 일반 머리표)
#   "붙임 1. …", "별 첨 : 1. …", "첨부 2 …" 등 줄머리 형태
RE_ATTACH = re.compile(r"^\s*(붙\s*임|별\s*첨|별\s*지|첨\s*부)\s*\d*\s*[.\:：]?\s*(.*)$")
# 별첨 본문 섹션 헤더: "(별 첨 1)", "（붙임 2）", "[별첨 3]" 등 괄호로 감싼 형태.
# 본문 끝의 콜론형 '목록 줄'과 달리, 페이지가 바뀐 '실제 첨부 본문'의 머리다.
RE_ATTACH_HEADER = re.compile(
    r"^\s*[\(（\[]\s*(붙\s*임|별\s*첨|별\s*지|첨\s*부)\s*\d*\s*[\)）\]]"
)
RE_APPENDIX_REF = re.compile(r"(붙임|별첨|별지|별표|서식|첨부)")

# 조문 인용(공문 본문 안에서) — 헤딩이 아니라 인용일 뿐
RE_ARTICLE_CITE = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")

# ── 목차(ToC) 탐지 ────────────────────────────────────────────────
RE_TOC_HEADER = re.compile(r"^\s*(목\s*차|차\s*례|目\s*次|contents)\s*$", re.I)
# 목차 항목 줄: 본문 + 끝에 페이지번호. (리더 점선은 추출 시 공백 1개로 뭉개짐)
#   'Ⅰ. 부가가치세 … 일반 4' / '1. 사업자등록 현황 4' / 'Ⅴ. 신고 및 납부13'
RE_TOC_LINE = re.compile(r"^.*[가-힣A-Za-z\)）].{0,3}\d{1,3}\s*$")


def is_toc_entry(line: str) -> bool:
    """목차 항목 줄 판정: 한글/영문/괄호 본문 뒤 1~3자 이내에 페이지번호로 끝남."""
    s = line.strip()
    if len(s) > 70 or len(s) < 3:
        return False
    if not re.search(r"\d{1,3}\s*$", s):
        return False
    if not re.search(r"[가-힣A-Za-z]", s):
        return False
    # '명칭 : 값' 콜론 종결형(보증비율·코드 등)은 목차 아님.
    # 실제 목차 항목은 리더 점선(→공백)으로 페이지번호에 닿으며 콜론을 두지 않는다.
    if re.search(r"[:：]\s*\d{1,3}\s*$", s):
        return False
    return True


# ── 정렬 마커 서수(최상위 절 연속성 판정용) ───────────────────────
def marker_ordinal(level_name: str, marker: str):
    """정렬 가능한 마커 -> 정수 서수. 정렬 불가(□○- 등) -> None."""
    if level_name == "roman":
        return roman_value(marker)
    if level_name == "num":
        try:
            return int(marker)
        except ValueError:
            return None
    if level_name == "han":
        order = "가나다라마바사아자차카타파하"
        return order.index(marker) + 1 if marker in order else None
    if level_name == "enum":
        m = re.match(r"\((\d{1,2})\)|(\d{1,2})\)", marker)
        if m:
            return int(m.group(1) or m.group(2))
        if "①" <= marker <= "⑳":
            return ord(marker) - 0x2460 + 1
    return None
