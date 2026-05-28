"""
SERVICE LIST (프로포마 스케줄) 로더.

원본 SERVICE_LIST.xls 구조:
- 한 파일에 여러 서비스가 연속으로 쌓여 있음
- 각 서비스 블록:
    [0행] 서비스명 헤더 (예: 'ANX  Service (ASIA NEW EXPRESS)')
    [1행] 컬럼 헤더 (SEQ, FRPORT, WHARF, TOPORT, BND, ETA, TBMANV, ETB, ...)
    [2행~] 구간별 데이터
    [공백 행]
    [다음 서비스 헤더]

각 구간(레그)의 컬럼:
    SEQ        구간 순번
    FRPORT     출발 항구
    WHARF      접안 부두
    TOPORT     도착 항구
    BND        방향 (S, N, E, W 등)
    ETA        예상 도착 시각
    TBMANV     접안 maneuvering 시간 (HH:MM)
    ETB        접안 완료 시각
    ETBDAY     ETB 요일
    TDMANV     이안 maneuvering 시간
    TML        터미널 작업시간 (HHH:MM)
    ETD        출항 시각
    ETDDAY     ETD 요일
    DISTANCE   해상 거리 (NM)
    SPEED      선속 (knot)
    SEATIME    항해시간 (HHH:MM)
    DIFF       시차
    SEABUFF    버퍼 타임 (HHH:MM)
    TOALTIME   총 구간 시간 (HHH:MM)

표준 출력 형식:
1) services_df: 서비스 마스터
    service_code   service_name
    ANX           ASIA NEW EXPRESS

2) legs_df: 구간별 상세 (long format)
    service_code  seq  from_port  to_port  bnd  distance_nm  speed_knot
    ANX           1    KRINC      KRPUS    S    406          18
    ...
    + 시간 컬럼들 (모두 분 단위로 변환)
"""

import re
from pathlib import Path
import pandas as pd
from .base import BaseDataLoader


# 컬럼 매핑 (원본 컬럼명 → 표준명)
COLUMN_MAP = {
    "SEQ": "seq",
    "FRPORT": "from_port",
    "WHARF": "wharf",
    "TOPORT": "to_port",
    "BND": "bnd",
    "ETA": "eta",
    "TBMANV": "tb_manv",
    "ETB": "etb",
    "ETBDAY": "etb_day",
    "TDMANV": "td_manv",
    "TML": "tml",
    "ETD": "etd",
    "ETDDAY": "etd_day",
    "DISTANCE": "distance_nm",
    "SPEED": "speed_knot",
    "SEATIME": "sea_time",
    "DIFF": "diff",
    "SEABUFF": "sea_buff",
    "TOALTIME": "total_time",
}


class ServiceScheduleLoader(BaseDataLoader):
    """프로포마 스케줄 로더"""

    def _parse(self) -> dict:
        # 확장자가 .xls여도 실제로 xlsx인 경우가 있어서 자동 감지
        raw = pd.read_excel(self.file_path, header=None)

        services = []
        legs = []

        # 서비스 헤더 행 찾기
        service_header_pattern = re.compile(r"^\s*(\S+)\s+Service\s*\((.*)\)", re.IGNORECASE)

        # 모든 서비스 헤더 행과 컬럼 헤더 행의 위치
        blocks = []  # [(header_row, code, name)]
        for idx in range(len(raw)):
            cell = raw.iloc[idx, 0]
            if pd.isna(cell):
                continue
            s = str(cell).strip()
            m = service_header_pattern.match(s)
            if m:
                blocks.append((idx, m.group(1).strip(), m.group(2).strip()))

        # 각 블록의 데이터 추출
        for i, (header_idx, code, name) in enumerate(blocks):
            services.append({
                "service_code": code,
                "service_name": name,
            })

            # 다음 블록 시작 전까지가 이 서비스의 영역
            end_idx = blocks[i + 1][0] if i + 1 < len(blocks) else len(raw)

            # header_idx + 1 행이 컬럼 헤더
            col_header_idx = header_idx + 1
            if col_header_idx >= end_idx:
                continue

            # 컬럼 매핑 만들기
            col_map = {}  # col_idx → 표준명
            header_row = raw.iloc[col_header_idx]
            for col_idx, val in enumerate(header_row):
                if pd.isna(val):
                    continue
                key = str(val).strip().upper()
                if key in COLUMN_MAP:
                    col_map[col_idx] = COLUMN_MAP[key]

            # 데이터 행 (col_header_idx + 1 부터 end_idx 전까지)
            for data_idx in range(col_header_idx + 1, end_idx):
                row = raw.iloc[data_idx]
                # SEQ 컬럼이 비어있으면 스킵
                seq_col_idx = next((c for c, n in col_map.items() if n == "seq"), None)
                if seq_col_idx is None:
                    continue
                seq_val = row.iloc[seq_col_idx]
                if pd.isna(seq_val):
                    continue

                leg = {"service_code": code}
                for col_idx, std_name in col_map.items():
                    val = row.iloc[col_idx]
                    leg[std_name] = self._normalize_value(std_name, val)
                legs.append(leg)

        services_df = pd.DataFrame(services).drop_duplicates(subset=["service_code"])
        legs_df = pd.DataFrame(legs)

        # 분 단위 컬럼 추가 (시간 계산 편의)
        if not legs_df.empty:
            for time_col in ["tb_manv", "td_manv", "tml", "sea_time", "sea_buff", "total_time"]:
                if time_col in legs_df.columns:
                    legs_df[f"{time_col}_min"] = legs_df[time_col].apply(self._time_to_minutes)

        return {
            "services": services_df,
            "legs": legs_df,
        }

    @staticmethod
    def _normalize_value(col_name: str, val):
        """컬럼별 값 정규화"""
        if pd.isna(val):
            return None
        if col_name in ("seq",):
            try:
                return int(str(val).strip())
            except (ValueError, TypeError):
                return None
        if col_name in ("distance_nm", "speed_knot"):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        if col_name in ("from_port", "to_port", "wharf", "bnd"):
            return str(val).strip()
        # 시간/일자는 문자열로 보존
        return str(val).strip() if not pd.isna(val) else None

    @staticmethod
    def _time_to_minutes(time_str) -> int | None:
        """
        시간 문자열을 분 단위로.
        '022:33' → 22*60 + 33 = 1353
        '01:00' → 60
        '-010:0' → -600 (음수도 지원, 시차용)
        """
        if time_str is None or pd.isna(time_str):
            return None
        s = str(time_str).strip()
        if not s:
            return None
        # 음수 처리
        sign = 1
        if s.startswith("-"):
            sign = -1
            s = s[1:]
        # HHH:MM 또는 HH:MM
        m = re.match(r"^(\d+):(\d+)$", s)
        if not m:
            return None
        try:
            hours = int(m.group(1))
            minutes = int(m.group(2))
            return sign * (hours * 60 + minutes)
        except ValueError:
            return None

    # ===== 조회 API =====
    def get_services(self) -> pd.DataFrame:
        return self.load()["services"]

    def get_legs(self, service_code: str | None = None) -> pd.DataFrame:
        df = self.load()["legs"]
        if service_code is None:
            return df
        return df[df["service_code"] == service_code].copy()

    def get_service_summary(self, service_code: str) -> dict | None:
        """서비스 1개의 요약 통계"""
        legs = self.get_legs(service_code)
        if legs.empty:
            return None

        total_distance = legs["distance_nm"].sum()
        avg_speed = legs["speed_knot"].mean()

        # 항해 시간 합계 (분)
        sea_min = legs["sea_time_min"].sum() if "sea_time_min" in legs.columns else 0
        port_min = legs["tml_min"].sum() if "tml_min" in legs.columns else 0
        manv_min = (
            (legs["tb_manv_min"].fillna(0).sum() if "tb_manv_min" in legs.columns else 0)
            + (legs["td_manv_min"].fillna(0).sum() if "td_manv_min" in legs.columns else 0)
        )
        buff_min = legs["sea_buff_min"].sum() if "sea_buff_min" in legs.columns else 0
        total_min = legs["total_time_min"].sum() if "total_time_min" in legs.columns else 0

        port_sequence = list(legs["from_port"]) + [legs.iloc[-1]["to_port"]]

        return {
            "service_code": service_code,
            "leg_count": len(legs),
            "total_distance_nm": total_distance,
            "avg_speed_knot": avg_speed,
            "sea_time_hours": sea_min / 60 if sea_min else 0,
            "port_time_hours": port_min / 60 if port_min else 0,
            "manv_time_hours": manv_min / 60,
            "buff_time_hours": buff_min / 60 if buff_min else 0,
            "total_time_hours": total_min / 60 if total_min else 0,
            "port_sequence": port_sequence,
            "unique_ports": list(set(port_sequence)),
        }
