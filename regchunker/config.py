# -*- coding: utf-8 -*-
"""청커 설정값.

환경변수로 재정의 가능:
    HWPX_INPUT_DIR      입력 폴더 (기본: ~/Downloads)
    HWPX_OUTPUT_DIR     출력 폴더 (기본: <프로젝트루트>/output)
    HWPX_MAX_CHARS      청크 상한 자수 (기본: 1400)
    HWPX_MIN_CHARS      청크 하한 자수 (기본: 30)
    HWPX_MAX_XML_BYTES  섹션 XML 크기 한도 (기본: 52428800 = 50 MB)

파일 패턴(INPUT_GLOB)은 머신마다 달라지는 값이 아니므로 환경변수로 뺴지 않는다.
변경이 필요하면 CLI 인자로 직접 넘기거나 이 파일의 상수를 수정한다.
"""
import os

# ── 입출력 경로 ────────────────────────────────────────────────────
_DEFAULT_INPUT = os.path.join(os.path.expanduser("~"), "Downloads")
DEFAULT_INPUT_DIR: str = os.environ.get("HWPX_INPUT_DIR", _DEFAULT_INPUT)
# 파일 명명 규칙 — 변경 시 CLI 인자로 넘기거나 이 값을 직접 수정
INPUT_GLOB: str = "*.HWPX"

_DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
OUTPUT_DIR: str = os.environ.get("HWPX_OUTPUT_DIR", _DEFAULT_OUTPUT)

# ── 청킹 파라미터 ──────────────────────────────────────────────────
# 조문 1차 청크 상한(자). 초과 시 항(①) 경계로 2차 분할.
# 한국어 기준 1,400자 ≈ 700~900 token.
MAX_CHARS: int = int(os.environ.get("HWPX_MAX_CHARS", "1400"))

# 청크 최소 길이(자). 이 미만 청크는 임베딩 품질 저하 원인.
MIN_CHARS: int = int(os.environ.get("HWPX_MIN_CHARS", "30"))

# ── ZIP 안전 제한 ──────────────────────────────────────────────────
# 단일 섹션 XML 최대 비압축 크기 (50 MB). ZIP 폭탄 방어.
MAX_XML_BYTES: int = int(os.environ.get("HWPX_MAX_XML_BYTES", str(50 * 1024 * 1024)))

# ── rhwp 백엔드 ────────────────────────────────────────────────────
# HWPX/HWP → '시각 순서' 마크다운 변환에 쓰는 rhwp CLI 바이너리 경로.
# XML 삽입 순서가 아닌 레이아웃(페이지) 순서로 본문·표를 추출한다.
# 환경변수 RHWP_BIN으로 재정의 가능./

_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
_RHWP_EXE = "rhwp.exe" if os.name == "nt" else "rhwp"
RHWP_BIN: str = os.environ.get(
    "RHWP_BIN",
    os.path.join(_REPO_ROOT, "vendor", "rhwp", "target", "release", _RHWP_EXE),
)
