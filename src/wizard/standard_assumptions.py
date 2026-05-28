"""
프로포마 표준 가정값.

기존 SERVICE_LIST에서 통계 추출:
- 항구별 평균 정박시간 (TML)
- Maneuvering 표준 시간
- 표준 선속

신규 항로 작성 시 합리적 기본값으로 사용.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager


# 기본 표준값 (회사 운영 정책 기준, 통계 데이터 없을 때 사용)
DEFAULT_STANDARDS = {
    "speed_knot": 15.0,
    "tb_manv_minutes": 60,        # 접안 maneuvering 1시간
    "td_manv_minutes": 60,        # 이안 maneuvering 1시간
    "tml_minutes_default": 720,   # 정박 12시간 (항구 데이터 없을 때)
    "sea_buff_minutes": 120,      # 버퍼 2시간
}


@dataclass
class StandardAssumptions:
    """프로포마 작성 시 사용할 표준 가정값"""
    speed_knot: float = DEFAULT_STANDARDS["speed_knot"]
    tb_manv_minutes: int = DEFAULT_STANDARDS["tb_manv_minutes"]
    td_manv_minutes: int = DEFAULT_STANDARDS["td_manv_minutes"]
    sea_buff_minutes: int = DEFAULT_STANDARDS["sea_buff_minutes"]

    def to_dict(self) -> dict:
        return {
            "speed_knot": self.speed_knot,
            "tb_manv_minutes": self.tb_manv_minutes,
            "td_manv_minutes": self.td_manv_minutes,
            "sea_buff_minutes": self.sea_buff_minutes,
        }


class StandardValueExtractor:
    """기존 서비스 데이터에서 표준값 추출"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager
        self._port_dwell_times = None
        self._build()

    def _build(self):
        """항구별 평균 정박시간 매트릭스 구축"""
        legs = self.data.service.get_legs()

        # 도착항(to_port) 기준 TML(정박시간) 평균
        # to_port에 도착해서 정박하는 시간이 TML이므로
        df = legs[["to_port", "tml_min"]].dropna()
        df = df[df["tml_min"] > 0]

        stats = df.groupby("to_port")["tml_min"].agg(
            ["mean", "median", "count"]
        ).reset_index()
        stats.columns = ["port", "mean_minutes", "median_minutes", "sample_count"]
        self._port_dwell_times = stats

    def get_port_dwell_time(
        self, port: str, use_median: bool = True
    ) -> tuple[int, int]:
        """
        항구의 표준 정박시간 (분).
        Returns: (분 단위 정박시간, 샘플 수)
        샘플이 없으면 DEFAULT_STANDARDS["tml_minutes_default"] 반환.
        """
        if self._port_dwell_times is None:
            return DEFAULT_STANDARDS["tml_minutes_default"], 0

        match = self._port_dwell_times[self._port_dwell_times["port"] == port]
        if match.empty:
            return DEFAULT_STANDARDS["tml_minutes_default"], 0

        row = match.iloc[0]
        minutes = row["median_minutes"] if use_median else row["mean_minutes"]
        # 5분 단위로 반올림
        rounded = int(round(minutes / 5) * 5)
        return rounded, int(row["sample_count"])

    def get_dwell_times_for_ports(
        self, ports: list[str]
    ) -> dict[str, tuple[int, int]]:
        """여러 항구의 정박시간 일괄 조회"""
        return {p: self.get_port_dwell_time(p) for p in ports}

    def get_overall_speed_stats(self) -> dict:
        """전체 서비스의 선속 통계"""
        legs = self.data.service.get_legs()
        speeds = legs["speed_knot"].dropna()
        # 비합리적 값(0, 150 등) 제거
        speeds = speeds[(speeds >= 8) & (speeds <= 30)]
        if speeds.empty:
            return {"median": DEFAULT_STANDARDS["speed_knot"]}
        return {
            "median": round(float(speeds.median()), 1),
            "mean": round(float(speeds.mean()), 1),
            "p25": round(float(speeds.quantile(0.25)), 1),
            "p75": round(float(speeds.quantile(0.75)), 1),
        }

    def get_manv_stats(self) -> dict:
        """Maneuvering 시간 통계"""
        legs = self.data.service.get_legs()
        tb = legs["tb_manv_min"].dropna()
        td = legs["td_manv_min"].dropna()
        tb = tb[(tb > 0) & (tb < 500)]  # 합리적 범위
        td = td[(td > 0) & (td < 500)]

        return {
            "tb_median_min": int(tb.median()) if not tb.empty else 60,
            "td_median_min": int(td.median()) if not td.empty else 60,
        }

    def suggest_assumptions(self) -> StandardAssumptions:
        """현재 회사 운영 데이터 기반 추천 표준값"""
        speed = self.get_overall_speed_stats()
        manv = self.get_manv_stats()
        return StandardAssumptions(
            speed_knot=speed.get("median", DEFAULT_STANDARDS["speed_knot"]),
            tb_manv_minutes=manv.get("tb_median_min", 60),
            td_manv_minutes=manv.get("td_median_min", 60),
            sea_buff_minutes=DEFAULT_STANDARDS["sea_buff_minutes"],
        )
