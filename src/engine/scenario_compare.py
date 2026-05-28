"""
다중 시나리오 비교 엔진.

SMX 업사이징 양식과 같이 여러 시나리오를 동시에 계산하고 비교.

시나리오 = 항로 + 선형 + ServiceContext(BSA) + 기준 시점.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..engine.service_context import ServiceContext
from ..data_loaders import MasterDataManager
from ..cost_calculators import VoyageCostCalculator, VoyageCostIntegrator
from ..cost_calculators.voyage_cost_calculator import OwnCostBreakdown


@dataclass
class ScenarioSpec:
    """한 시나리오의 정의"""
    name: str                           # "SMX 현재", "4.2K 업사이징" 등
    service_code: str
    vessel_type: str
    year: int = 2026
    month: int = 1
    fuel_type: str = "LSFO"

    # 공동운항/BSA
    total_vessels: int = 1
    own_vessels: int = 1
    bsa_override: Optional[float] = None    # None이면 자동 산정
    weight_basis_ton: float = 14.0

    # 벙커링 항구 (선택)
    bunker_port: Optional[str] = None

    # 정박/Buffer 유종 (선택, None이면 fuel_type과 동일)
    port_fuel_type: Optional[str] = None

    # S/N 매핑 (해당 항로가 S/N 표기일 때)
    sn_mapping: Optional[dict] = None

    def short_summary(self) -> str:
        return (f"{self.service_code} × {self.vessel_type} "
                f"({self.own_vessels}/{self.total_vessels}척)")


@dataclass
class ScenarioResult:
    """한 시나리오의 계산 결과"""
    spec: ScenarioSpec

    # 기본 정보
    voyage_days: float
    total_distance_nm: float
    leg_count: int

    # 1척 운항원가
    fuel_cost: float
    port_charge: float
    charter_hire: float
    total_voyage_cost: float

    # ServiceContext 적용 결과 (BSA 기반)
    capacity_teu: float                # 1척 선복 (14T)
    bsa_teu: float                     # 자사 BSA
    per_teu_unit: float                # TEU당 단가
    own_total_cost: float              # 자사 부담
    slot_balance_teu: float
    slot_lending_revenue: float
    slot_charter_cost: float
    net_voyage_cost: float

    # 시간 분포
    sea_hours: float
    manv_hours: float
    buffer_hours: float
    terminal_hours: float

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.spec.name,
            "service_code": self.spec.service_code,
            "vessel_type": self.spec.vessel_type,
            "voyage_days": self.voyage_days,
            "total_distance_nm": self.total_distance_nm,
            "leg_count": self.leg_count,
            "fuel_cost": self.fuel_cost,
            "port_charge": self.port_charge,
            "charter_hire": self.charter_hire,
            "total_voyage_cost": self.total_voyage_cost,
            "capacity_teu": self.capacity_teu,
            "bsa_teu": self.bsa_teu,
            "per_teu_unit": self.per_teu_unit,
            "own_total_cost": self.own_total_cost,
            "slot_balance_teu": self.slot_balance_teu,
            "slot_lending_revenue": self.slot_lending_revenue,
            "slot_charter_cost": self.slot_charter_cost,
            "net_voyage_cost": self.net_voyage_cost,
            "sea_hours": self.sea_hours,
            "manv_hours": self.manv_hours,
            "buffer_hours": self.buffer_hours,
            "terminal_hours": self.terminal_hours,
            "warnings": self.warnings,
        }


class ScenarioComparator:
    """여러 시나리오를 동시 계산하고 비교"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager
        self.cost_calc = VoyageCostCalculator(data_manager)

    def evaluate(self, spec: ScenarioSpec) -> ScenarioResult:
        """한 시나리오 계산"""
        # 1) 운항원가 계산 (1척 기준)
        cost = self.cost_calc.calculate(
            spec.service_code, spec.vessel_type,
            spec.year, spec.month, spec.fuel_type,
            bunker_port=spec.bunker_port,
            port_fuel_type=spec.port_fuel_type,
        )

        # 2) ServiceContext 구성
        vessel_info = self.data.vessel_spec.get_type_info(spec.vessel_type)
        if vessel_info is None:
            raise ValueError(f"선형 정보 없음: {spec.vessel_type}")

        capacity_14t = vessel_info.get("teu_at_14t") or vessel_info.get("teu_nominal")

        # 운영형태 자동 판단
        if spec.own_vessels == 0:
            op_type = "charter_only"
        elif spec.own_vessels == spec.total_vessels:
            op_type = "owned"
        else:
            op_type = "shared"

        ctx = ServiceContext(
            service_code=spec.service_code,
            operation_type=op_type,
            total_vessels_in_service=spec.total_vessels,
            vessel_capacity_teu_14t=float(capacity_14t),
            own_vessels_deployed=spec.own_vessels,
            own_bsa_teu=spec.bsa_override,
            weight_basis_ton=spec.weight_basis_ton,
        )

        # 3) ServiceContext 적용
        own = cost.apply_service_context(ctx)

        # 4) 시간 분포 계산 (leg별 합산)
        legs = self.data.service.get_legs(spec.service_code)
        sea_min = legs["sea_time_min"].fillna(0).sum()
        manv_min = (legs["tb_manv_min"].fillna(0) + legs["td_manv_min"].fillna(0)).sum()
        buffer_min = legs["sea_buff_min"].fillna(0).sum()
        terminal_min = legs["tml_min"].fillna(0).sum()

        # 5) 거리/구간
        total_dist = legs["distance_nm"].fillna(0).sum()

        return ScenarioResult(
            spec=spec,
            voyage_days=cost.charter.voyage_days,
            total_distance_nm=float(total_dist),
            leg_count=len(legs),
            fuel_cost=cost.total_fuel_usd,
            port_charge=cost.total_port_charge_usd,
            charter_hire=cost.total_charter_usd,
            total_voyage_cost=cost.grand_total_usd,
            capacity_teu=ctx.vessel_capacity_teu_14t,
            bsa_teu=ctx.effective_bsa_teu,
            per_teu_unit=own.per_teu_unit,
            own_total_cost=own.own_total_cost,
            slot_balance_teu=own.slot_balance_teu,
            slot_lending_revenue=own.slot_lending_revenue,
            slot_charter_cost=own.slot_charter_cost,
            net_voyage_cost=own.net_voyage_cost,
            sea_hours=sea_min / 60,
            manv_hours=manv_min / 60,
            buffer_hours=buffer_min / 60,
            terminal_hours=terminal_min / 60,
            warnings=cost.all_warnings,
        )

    def evaluate_many(self, specs: list[ScenarioSpec]) -> list[ScenarioResult]:
        """여러 시나리오 일괄 계산"""
        results = []
        for spec in specs:
            try:
                results.append(self.evaluate(spec))
            except Exception as e:
                # 실패한 시나리오는 None으로 (UI에서 처리)
                pass
        return results

    def compute_diffs(self, base: ScenarioResult,
                      compares: list[ScenarioResult]) -> list[dict]:
        """베이스 대비 비교 시나리오들의 차이값 계산"""
        diffs = []
        for c in compares:
            diff = {
                "name": c.spec.name,
                "voyage_days_diff": c.voyage_days - base.voyage_days,
                "distance_diff": c.total_distance_nm - base.total_distance_nm,
                "fuel_diff": c.fuel_cost - base.fuel_cost,
                "port_diff": c.port_charge - base.port_charge,
                "charter_diff": c.charter_hire - base.charter_hire,
                "total_voyage_diff": c.total_voyage_cost - base.total_voyage_cost,
                "per_teu_diff": c.per_teu_unit - base.per_teu_unit,
                "own_cost_diff": c.own_total_cost - base.own_total_cost,
                "net_cost_diff": c.net_voyage_cost - base.net_voyage_cost,
                # 변화율 (%)
                "total_voyage_pct": ((c.total_voyage_cost - base.total_voyage_cost)
                                     / base.total_voyage_cost * 100
                                     if base.total_voyage_cost else 0),
                "per_teu_pct": ((c.per_teu_unit - base.per_teu_unit)
                                / base.per_teu_unit * 100
                                if base.per_teu_unit else 0),
            }
            diffs.append(diff)
        return diffs
