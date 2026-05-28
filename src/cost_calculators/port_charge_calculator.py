"""
항비 계산기.

산식:
  항비 = Σ구간별 PORT_CHARGE[기항항구][선형 카테고리]

선형 → 카테고리 매칭 룰:
  TEU 크기에 따라 HIRE 파일의 CA1~CA20 중 하나로 매칭.
  PORT_CHARGE는 CA1~CA15까지만 신뢰성 있는 데이터가 있고,
  CA16은 의미가 불명확하여 사용하지 않음.
  CA15 초과 선형(5000TEU 이상)은 CA15로 폴백 + 경고 표시.

  주의: PORT_CHARGE.xls의 CA16 컬럼은 다른 카테고리와 패턴이 다르며,
        실제로 CA15급 큰 선형의 항비로 보기 어려운 값. 추후 확인 필요.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager


# ============================================================
# 선형 TEU → 항비 카테고리 매칭 (PORT_CHARGE는 CA15까지만 신뢰)
# ============================================================
# (TEU 상한, 카테고리) - HIRE 파일의 NAME 컬럼 기준
TEU_TO_PORT_CATEGORY = [
    (1040, "CA1"),    # 1,030teu
    (1075, "CA2"),    # 1,050teu
    (1100, "CA3"),    # 1,100teu
    (1200, "CA4"),    # 1,100teu Modern
    (1500, "CA5"),    # 1,300teu
    (1720, "CA6"),    # 1,700teu
    (1770, "CA7"),    # 1,740teu
    (1900, "CA8"),    # 1,800teu
    (2350, "CA9"),    # 2,200teu
    (2600, "CA10"),   # 2,500teu
    (2750, "CA11"),   # 2,700teu
    (3150, "CA12"),   # 2,800teu
    (3900, "CA13"),   # 3,500teu
    (4650, "CA14"),   # 4,300teu
    (5025, "CA15"),   # 5,000teu
]

# CA16 이상은 데이터가 없거나 신뢰성이 낮음 → CA15로 폴백
MAX_RELIABLE_CATEGORY = "CA15"


def teu_to_port_category(teu_size: int) -> tuple[str, bool]:
    """
    TEU 크기로 항비 카테고리 매칭.
    반환: (카테고리, 폴백 여부)
    """
    if teu_size <= 0:
        return (MAX_RELIABLE_CATEGORY, True)
    for upper, cat in TEU_TO_PORT_CATEGORY:
        if teu_size <= upper:
            return (cat, False)
    return (MAX_RELIABLE_CATEGORY, True)  # 폴백


# ============================================================
# 결과 객체
# ============================================================
@dataclass
class PortChargeBreakdown:
    """한 항구 기항의 항비 분석"""
    leg_seq: int
    port: str                      # 기항 항구 코드
    category: str                  # 적용된 카테고리
    charge_usd: float              # 항비 (USD)
    is_fallback: bool = False      # 카테고리 폴백 적용 여부
    fallback_from: str = ""        # 원래 매칭됐던 카테고리
    data_missing: bool = False     # 해당 항구의 데이터 자체가 없음


@dataclass
class ServicePortChargeResult:
    """서비스 전체의 항비 결과"""
    service_code: str
    vessel_type: str
    teu_size: int
    matched_category: str           # 이 선형에 적용된 항비 카테고리
    is_category_fallback: bool      # 카테고리 자체가 폴백인지

    leg_breakdowns: list[PortChargeBreakdown] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_port_charge_usd(self) -> float:
        return sum(b.charge_usd for b in self.leg_breakdowns)

    @property
    def missing_ports(self) -> list[str]:
        return [b.port for b in self.leg_breakdowns if b.data_missing]

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "seq": b.leg_seq,
            "port": b.port,
            "category": b.category,
            "charge_usd": b.charge_usd,
            "fallback": "Yes" if b.is_fallback else "",
            "fallback_from": b.fallback_from,
            "data_missing": "❌" if b.data_missing else "",
        } for b in self.leg_breakdowns])

    def summary(self) -> dict:
        return {
            "service_code": self.service_code,
            "vessel_type": self.vessel_type,
            "teu_size": self.teu_size,
            "matched_category": self.matched_category,
            "is_category_fallback": self.is_category_fallback,
            "total_port_charge_usd": self.total_port_charge_usd,
            "leg_count": len(self.leg_breakdowns),
            "missing_ports": self.missing_ports,
            "warnings": self.warnings,
        }


# ============================================================
# 메인 계산기
# ============================================================
class PortChargeCalculator:
    """항비 계산기"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager

    def calculate_service(
        self,
        service_code: str,
        vessel_type: str,
        target_date: date | None = None,
    ) -> ServicePortChargeResult:
        """
        서비스 전체의 항비 계산.
        각 leg의 도착 항구(to_port)에서 발생하는 항비 합산.
        """
        # 1. 선형 정보 → TEU → 카테고리
        info = self.data.vessel_spec.get_type_info(vessel_type)
        if info is None:
            raise ValueError(f"선형 정보 없음: {vessel_type}")

        teu_size = int(info.get("teu_nominal") or 0)
        if teu_size == 0:
            raise ValueError(f"선형 '{vessel_type}'의 TEU 정보가 없습니다")

        matched_cat, is_cat_fallback = teu_to_port_category(teu_size)

        result = ServicePortChargeResult(
            service_code=service_code,
            vessel_type=vessel_type,
            teu_size=teu_size,
            matched_category=matched_cat,
            is_category_fallback=is_cat_fallback,
        )

        if is_cat_fallback:
            result.warnings.append(
                f"선형 {vessel_type} ({teu_size}TEU)은 PORT_CHARGE 데이터 범위(~5000TEU)를 "
                f"초과해 {matched_cat}로 폴백 처리. 실제 항비는 더 클 가능성 있음."
            )

        # 2. 서비스의 모든 leg
        legs = self.data.service.get_legs(service_code)
        if legs.empty:
            raise ValueError(f"서비스 없음: {service_code}")

        unmapped = set()
        for _, leg in legs.iterrows():
            to_port = str(leg.get("to_port") or "")
            seq = int(leg.get("seq") or 0)
            bd = self._calculate_leg(to_port, seq, matched_cat, target_date)
            result.leg_breakdowns.append(bd)
            if bd.data_missing:
                unmapped.add(to_port)

        if unmapped:
            result.warnings.append(
                f"PORT_CHARGE 데이터가 없는 항구 (항비 0으로 처리): {sorted(unmapped)}"
            )

        return result

    def _calculate_leg(
        self,
        port: str,
        seq: int,
        category: str,
        target_date: date | None,
    ) -> PortChargeBreakdown:
        """한 기항지의 항비"""
        # 직접 매칭
        charge = self.data.port_charge.get_charge(port, category, target_date)

        if charge is not None:
            return PortChargeBreakdown(
                leg_seq=seq, port=port, category=category, charge_usd=charge,
            )

        # 해당 항구에 그 카테고리가 없으면 가까운 카테고리로 폴백
        available_cats = self.data.port_charge.get_categories_for_port(port)
        # CA16은 신뢰성 낮으므로 제외
        available_cats = [c for c in available_cats if c != "CA16"]

        if not available_cats:
            # 항구 자체 데이터 없음
            return PortChargeBreakdown(
                leg_seq=seq, port=port, category=category,
                charge_usd=0.0, data_missing=True,
            )

        # 가장 가까운 카테고리 (작은 쪽으로 폴백 - 보수적)
        target_num = int(category.replace("CA", ""))
        # 우선 같거나 작은 카테고리 중 최대값을 찾기
        smaller_or_equal = [c for c in available_cats
                            if int(c.replace("CA", "")) <= target_num]
        if smaller_or_equal:
            best = max(smaller_or_equal, key=lambda c: int(c.replace("CA","")))
        else:
            # 모두 큰 카테고리만 있으면 가장 작은 것
            best = min(available_cats, key=lambda c: int(c.replace("CA","")))

        charge = self.data.port_charge.get_charge(port, best, target_date)
        return PortChargeBreakdown(
            leg_seq=seq, port=port, category=best,
            charge_usd=charge or 0.0,
            is_fallback=True, fallback_from=category,
        )
