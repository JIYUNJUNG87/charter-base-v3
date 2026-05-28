"""
운항변동비 통합 계산기.

3가지 비용을 한 번에 계산:
  1. 연료비 (FuelCostCalculator)
  2. 항비 (PortChargeCalculator)
  3. 용선료 (CharterRateCalculator)

차터베이스 양식의 '운항변동비' + '운항고정비'를 포괄.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager
from ..engine.service_context import ServiceContext
from .fuel_calculator import FuelCostCalculator, ServiceFuelResult
from .port_charge_calculator import PortChargeCalculator, ServicePortChargeResult
from .charter_rate_calculator import CharterRateCalculator, CharterRateResult


@dataclass
class OwnCostBreakdown:
    """ServiceContext 적용 시 자사 부담 운항원가 분석"""
    bsa_teu: float
    capacity_teu: float                  # 1척 선복 (14T)
    per_teu_unit: float                  # TEU당 단가

    # 자사 부담 (BSA × 단가)
    own_fuel: float
    own_port_charge: float
    own_charter_hire: float

    # 선복 수지
    slot_balance_teu: float              # 양수: 임대, 음수: 임차
    slot_lending_revenue: float          # 임대 수익 (잉여 × 단가)
    slot_charter_cost: float             # 임차 비용 (부족 × 단가)

    @property
    def own_total_cost(self) -> float:
        return self.own_fuel + self.own_port_charge + self.own_charter_hire

    @property
    def net_voyage_cost(self) -> float:
        """순 운항원가 = 자사 부담 + 임차비 - 임대수익"""
        return self.own_total_cost + self.slot_charter_cost - self.slot_lending_revenue


@dataclass
class VoyageCostResult:
    """운항원가 통합 결과"""
    service_code: str
    vessel_type: str
    reference_year: int
    reference_month: int

    fuel: ServiceFuelResult
    port_charge: ServicePortChargeResult
    charter: CharterRateResult

    @property
    def total_fuel_usd(self) -> float:
        return self.fuel.total_fuel_cost_usd

    @property
    def total_port_charge_usd(self) -> float:
        return self.port_charge.total_port_charge_usd

    @property
    def total_charter_usd(self) -> float:
        return self.charter.total_charter_cost_usd

    @property
    def total_voyage_variable_cost_usd(self) -> float:
        """차터베이스 '운항변동비' = 연료비 + 항비"""
        return self.total_fuel_usd + self.total_port_charge_usd

    @property
    def total_voyage_fixed_cost_usd(self) -> float:
        """차터베이스 '운항고정비' = 용선료"""
        return self.total_charter_usd

    @property
    def grand_total_usd(self) -> float:
        return (self.total_fuel_usd + self.total_port_charge_usd
                + self.total_charter_usd)

    @property
    def all_warnings(self) -> list[str]:
        return self.fuel.warnings + self.port_charge.warnings + self.charter.warnings

    def summary(self) -> dict:
        total = self.grand_total_usd
        return {
            "service_code": self.service_code,
            "vessel_type": self.vessel_type,
            "teu_size": self.charter.teu_size,
            "reference_period": self.charter.reference_month_label,
            "voyage_days": self.charter.voyage_days,
            "costs": {
                "fuel_usd": self.total_fuel_usd,
                "port_charge_usd": self.total_port_charge_usd,
                "charter_hire_usd": self.total_charter_usd,
                "total_usd": total,
            },
            "cost_share_pct": {
                "fuel": self.total_fuel_usd / total * 100 if total else 0,
                "port_charge": self.total_port_charge_usd / total * 100 if total else 0,
                "charter_hire": self.total_charter_usd / total * 100 if total else 0,
            },
            "voyage_variable_cost_usd": self.total_voyage_variable_cost_usd,
            "voyage_fixed_cost_usd": self.total_voyage_fixed_cost_usd,
            "warnings": self.all_warnings,
        }

    def apply_service_context(self, ctx: ServiceContext) -> OwnCostBreakdown:
        """
        ServiceContext를 적용해 자사 부담 운항원가 + 선복 임대/임차 계산.

        핵심 (해석 B):
        - 단가 = 1척 운항원가 / 1척 전체 선복(14T)
        - 자사 부담 = BSA × 단가 (항목별로 비례 배분)
        - 잉여 → 임대 수익 / 부족 → 임차 비용

        Parameters
        ----------
        ctx : ServiceContext (총 척수, 자사 척수, BSA, 1척 선복 등)
        """
        capacity = ctx.vessel_capacity_teu_14t
        if capacity == 0:
            raise ValueError("ServiceContext의 vessel_capacity_teu_14t가 0입니다.")

        # TEU당 단가 (1척 기준)
        per_teu = self.grand_total_usd / capacity

        # 자사 부담 = BSA × 단가, 항목별로 비례
        bsa = ctx.effective_bsa_teu
        own_fuel = (self.total_fuel_usd / capacity) * bsa
        own_port = (self.total_port_charge_usd / capacity) * bsa
        own_charter = (self.total_charter_usd / capacity) * bsa

        # 선복 임대/임차
        balance = ctx.slot_balance_teu
        lending = max(0, balance) * per_teu
        charter = max(0, -balance) * per_teu

        return OwnCostBreakdown(
            bsa_teu=bsa,
            capacity_teu=capacity,
            per_teu_unit=per_teu,
            own_fuel=own_fuel,
            own_port_charge=own_port,
            own_charter_hire=own_charter,
            slot_balance_teu=balance,
            slot_lending_revenue=lending,
            slot_charter_cost=charter,
        )


class VoyageCostCalculator:
    """운항원가 통합 계산기"""

    def __init__(self, data_manager: MasterDataManager, fuel_assumptions: dict = None):
        self.data = data_manager
        self.fuel_calc = FuelCostCalculator(data_manager, fuel_assumptions)
        self.port_calc = PortChargeCalculator(data_manager)
        self.charter_calc = CharterRateCalculator(data_manager)

    def calculate(
        self,
        service_code: str,
        vessel_type: str,
        year: int,
        month: int,
        fuel_type: str = "LSFO",
        bunker_port: str = None,
        port_fuel_type: str = None,
    ) -> VoyageCostResult:
        """
        한 서비스/선형/시점의 운항원가 전체 계산.

        bunker_port: 벙커링 공급 항구
        fuel_type: 항해/Maneuvering 유종 (메인엔진)
        port_fuel_type: 정박/Buffer 유종 (보조엔진). None이면 fuel_type과 동일.
        """
        price_date = date(year, month, 1)

        fuel = self.fuel_calc.calculate_service(
            service_code, vessel_type, fuel_type, price_date,
            bunker_port=bunker_port,
            port_fuel_type=port_fuel_type,
        )
        port = self.port_calc.calculate_service(
            service_code, vessel_type, price_date
        )
        charter = self.charter_calc.calculate_service(
            service_code, vessel_type, year, month
        )

        return VoyageCostResult(
            service_code=service_code,
            vessel_type=vessel_type,
            reference_year=year,
            reference_month=month,
            fuel=fuel,
            port_charge=port,
            charter=charter,
        )

    def compare_vessels(
        self,
        service_code: str,
        vessel_types: list[str],
        year: int,
        month: int,
        fuel_type: str = "LSFO",
    ) -> pd.DataFrame:
        """여러 선형의 운항원가를 비교"""
        rows = []
        for vt in vessel_types:
            try:
                r = self.calculate(service_code, vt, year, month, fuel_type)
                rows.append({
                    "vessel_type": vt,
                    "teu_size": r.charter.teu_size,
                    "fuel_usd": r.total_fuel_usd,
                    "port_charge_usd": r.total_port_charge_usd,
                    "charter_usd": r.total_charter_usd,
                    "total_usd": r.grand_total_usd,
                    "warnings": len(r.all_warnings),
                })
            except Exception as e:
                rows.append({
                    "vessel_type": vt,
                    "teu_size": None,
                    "error": str(e),
                })
        return pd.DataFrame(rows)
