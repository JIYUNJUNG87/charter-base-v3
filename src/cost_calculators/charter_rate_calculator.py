"""
용선료 계산기.

산식:
  용선료 = 일일 용선료(HRCI) × 운항일수
  - 일일 용선료: HIRE 파일에서 (선형 카테고리, 연/월) 조회
  - 운항일수: SERVICE LIST의 TOALTIME 합계 ÷ 24

선형 → HIRE 카테고리 매칭:
  HIRE는 CA1~CA20 까지 모두 있으므로 정확한 매칭 가능.
  TEU 크기에 가장 가까운 카테고리 사용 (HireRateLoader가 자동 처리).
"""

from dataclasses import dataclass, field
from datetime import date
import pandas as pd

from ..data_loaders import MasterDataManager


# HIRE 카테고리 매핑 (HIRE 파일의 NAME 컬럼 기준 TEU)
HIRE_TEU_TO_CATEGORY = [
    (1040, "CA1"),  (1075, "CA2"),  (1100, "CA3"),  (1200, "CA4"),
    (1500, "CA5"),  (1720, "CA6"),  (1770, "CA7"),  (1900, "CA8"),
    (2350, "CA9"),  (2600, "CA10"), (2750, "CA11"), (3150, "CA12"),
    (3900, "CA13"), (4650, "CA14"), (5025, "CA15"), (5275, "CA16"),
    (5750, "CA17"), (6750, "CA18"), (7750, "CA19"), (99999, "CA20"),
]


def teu_to_hire_category(teu_size: int) -> str:
    """TEU → HIRE 카테고리 (전체 CA1~CA20 매핑)"""
    for upper, cat in HIRE_TEU_TO_CATEGORY:
        if teu_size <= upper:
            return cat
    return "CA20"


# ============================================================
# 결과 객체
# ============================================================
@dataclass
class CharterRateResult:
    """용선료 계산 결과"""
    service_code: str
    vessel_type: str
    teu_size: int
    matched_category: str
    category_name: str            # 예: "1,700teu Gless Topaz (5.0%)"

    voyage_hours: float           # 한 항차 총 시간
    voyage_days: float            # 한 항차 일수
    daily_charter_rate_usd: float # USD/day
    reference_year: int
    reference_month: int
    reference_month_label: str    # "Jan-26" 형식

    warnings: list[str] = field(default_factory=list)

    @property
    def total_charter_cost_usd(self) -> float:
        return self.daily_charter_rate_usd * self.voyage_days

    def to_dict(self) -> dict:
        return {
            "service_code": self.service_code,
            "vessel_type": self.vessel_type,
            "teu_size": self.teu_size,
            "matched_category": self.matched_category,
            "category_name": self.category_name,
            "voyage_hours": self.voyage_hours,
            "voyage_days": self.voyage_days,
            "daily_charter_rate_usd": self.daily_charter_rate_usd,
            "total_charter_cost_usd": self.total_charter_cost_usd,
            "reference_period": self.reference_month_label,
            "warnings": self.warnings,
        }


# ============================================================
# 메인 계산기
# ============================================================
class CharterRateCalculator:
    """HRCI 기반 용선료 계산기"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager

    def calculate_service(
        self,
        service_code: str,
        vessel_type: str,
        year: int,
        month: int,
    ) -> CharterRateResult:
        """서비스 한 항차의 용선료"""
        warnings = []

        # 1. 선형 정보
        info = self.data.vessel_spec.get_type_info(vessel_type)
        if info is None:
            raise ValueError(f"선형 정보 없음: {vessel_type}")
        teu_size = int(info.get("teu_nominal") or 0)

        # 2. HIRE 카테고리 매칭
        category = teu_to_hire_category(teu_size)

        # 카테고리 명세
        cats_df = self.data.hire.get_categories()
        cat_row = cats_df[cats_df["category"] == category]
        category_name = cat_row.iloc[0]["name"] if not cat_row.empty else ""

        # 3. 용선료 조회
        daily_rate = self.data.hire.get_rate(year, month, category)

        # 폴백: 해당 월 데이터 없으면 가장 가까운 월
        if daily_rate is None:
            rates_df = self.data.hire.get_rates()
            sub = rates_df[rates_df["category"] == category].copy()
            if sub.empty:
                raise ValueError(f"카테고리 {category}의 용선료 데이터 없음")
            target = date(year, month, 1)
            sub["diff_days"] = sub["month"].apply(
                lambda d: abs((d - target).days) if d else 999999
            )
            best = sub.sort_values("diff_days").iloc[0]
            daily_rate = float(best["daily_rate"])
            warnings.append(
                f"{year}-{month:02d} 용선료 데이터가 없어 가장 가까운 "
                f"{best['month_label']} 데이터 사용 (${daily_rate:,.0f}/day)"
            )

        # 4. 운항 시간 → 일수
        summary = self.data.service.get_service_summary(service_code)
        if summary is None:
            raise ValueError(f"서비스 정보 없음: {service_code}")
        voyage_hours = summary["total_time_hours"]
        voyage_days = voyage_hours / 24

        # 5. 결과
        month_label = pd.to_datetime(date(year, month, 1)).strftime("%b-%y")

        return CharterRateResult(
            service_code=service_code,
            vessel_type=vessel_type,
            teu_size=teu_size,
            matched_category=category,
            category_name=category_name,
            voyage_hours=voyage_hours,
            voyage_days=voyage_days,
            daily_charter_rate_usd=daily_rate,
            reference_year=year,
            reference_month=month,
            reference_month_label=month_label,
            warnings=warnings,
        )
