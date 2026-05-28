"""
RouteBaseline에 실제 운항원가를 자동으로 채워주는 통합 모듈.

기존 흐름 (v2):
  baseline 데이터 (운항변동비/고정비가 비어있거나 mock)
  → 시나리오 적용 → 시뮬레이션 결과

새 흐름 (v3):
  baseline + 서비스코드/선형 → 실제 운항원가 계산 → baseline에 자동 주입
  → 시나리오 적용 → 시뮬레이션 결과

새 흐름 (v3.1 - ServiceContext 통합):
  baseline + ServiceContext(BSA 기반) → 자사 부담 + 임대/임차 계산
  → baseline에 BSA 기반으로 주입 → 시나리오 적용
"""

from datetime import date
from copy import deepcopy
from dataclasses import dataclass, field

from ..engine.models import (
    RouteBaseline, VoyageVariableCost, VoyageFixedCost, Revenue,
)
from ..engine.service_context import ServiceContext
from ..data_loaders import MasterDataManager
from .voyage_cost_calculator import VoyageCostCalculator, OwnCostBreakdown
from .cost_allocator import CostAllocator, DirectionalCostAllocation


@dataclass
class ContextEnrichResult:
    """ServiceContext 기반 통합 결과"""
    ctx: ServiceContext
    own_breakdown: OwnCostBreakdown
    full_alloc: DirectionalCostAllocation
    warnings: list = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "service_code": self.ctx.service_code,
            "bsa_teu": self.ctx.effective_bsa_teu,
            "vessel_capacity_teu_14t": self.ctx.vessel_capacity_teu_14t,
            "per_teu_unit_usd": self.own_breakdown.per_teu_unit,
            "own_total_cost_usd": self.own_breakdown.own_total_cost,
            "slot_balance_teu": self.own_breakdown.slot_balance_teu,
            "slot_lending_revenue_usd": self.own_breakdown.slot_lending_revenue,
            "slot_charter_cost_usd": self.own_breakdown.slot_charter_cost,
            "net_voyage_cost_usd": self.own_breakdown.net_voyage_cost,
            "warnings": self.warnings,
        }


class VoyageCostIntegrator:
    """
    실제 운항원가를 시뮬레이션 baseline에 통합.
    """

    def __init__(self, data_manager: MasterDataManager, fuel_assumptions: dict = None):
        self.data = data_manager
        self.cost_calc = VoyageCostCalculator(data_manager, fuel_assumptions)
        self.allocator = CostAllocator(data_manager)

    def enrich_baseline(
        self,
        baseline: RouteBaseline,
        service_code: str,
        vessel_type: str,
        year: int,
        month: int,
        fuel_type: str = "LSFO",
        overwrite: bool = False,
        sn_mapping: dict = None,
    ) -> tuple[RouteBaseline, DirectionalCostAllocation]:
        """
        baseline의 운항변동비/고정비를 실제 계산값으로 채움.

        Parameters
        ----------
        baseline : 차터베이스 양식 P&L (Case 4 시뮬레이션의 입력)
        service_code : ANX, SIS2 등 서비스 코드
        vessel_type : 선형 타입명 (예: "Jiangsu 4250")
        year, month : 단가/용선료 기준 시점
        fuel_type : LSFO 등
        overwrite : True면 기존 값을 덮어씀, False면 0인 항목만 채움
        sn_mapping : S/N → E/W 매핑 (남북 노선용, 예: {"S": "W", "N": "E"})

        Returns
        -------
        (enriched_baseline, allocation): 채워진 baseline + 분배 결과
        """
        # 1) 운항원가 계산
        cost = self.cost_calc.calculate(
            service_code, vessel_type, year, month, fuel_type
        )

        # 2) E/W 분배 (sn_mapping 전달)
        alloc = self.allocator.allocate(cost, sn_mapping=sn_mapping)

        # 3) baseline에 주입
        enriched = deepcopy(baseline)

        # East 방향
        self._inject(enriched.east.voyage_var_cost,
                     fuel=alloc.east_fuel,
                     port_charge=alloc.east_port_charge,
                     overwrite=overwrite)
        self._inject_fixed(enriched.east.voyage_fixed_cost,
                           charter_hire=alloc.east_charter,
                           overwrite=overwrite)

        # West 방향
        self._inject(enriched.west.voyage_var_cost,
                     fuel=alloc.west_fuel,
                     port_charge=alloc.west_port_charge,
                     overwrite=overwrite)
        self._inject_fixed(enriched.west.voyage_fixed_cost,
                           charter_hire=alloc.west_charter,
                           overwrite=overwrite)

        return enriched, alloc

    @staticmethod
    def _inject(target: VoyageVariableCost, fuel: float, port_charge: float,
                overwrite: bool):
        """운항변동비 항목 주입"""
        if overwrite or target.fuel == 0:
            target.fuel = fuel
        if overwrite or target.port_charge == 0:
            target.port_charge = port_charge

    @staticmethod
    def _inject_fixed(target: VoyageFixedCost, charter_hire: float,
                       overwrite: bool):
        """운항고정비 항목 주입"""
        if overwrite or target.charter_hire == 0:
            target.charter_hire = charter_hire

    def simulate_vessel_change(
        self,
        baseline: RouteBaseline,
        service_code: str,
        new_vessel_type: str,
        year: int,
        month: int,
        fuel_type: str = "LSFO",
        sn_mapping: dict = None,
    ) -> tuple[RouteBaseline, DirectionalCostAllocation]:
        """
        선형 변경 시뮬레이션의 정확도를 높이는 함수.
        새 선형으로 운항원가를 다시 계산해서 baseline에 반영.

        v2의 Scenario(new_vessel=...) 보다 훨씬 정확:
          - v2: 단순 비율 기반 (용선료 1.4배 등)
          - v3: 실제 HRCI + PORT_CHARGE + 연료 소모 커브 기반
        """
        return self.enrich_baseline(
            baseline, service_code, new_vessel_type,
            year, month, fuel_type, overwrite=True,
            sn_mapping=sn_mapping,
        )

    # ============================================================
    # v3.1: ServiceContext (BSA) 기반 통합
    # ============================================================
    def enrich_baseline_with_context(
        self,
        baseline: RouteBaseline,
        ctx: ServiceContext,
        vessel_type: str,
        year: int,
        month: int,
        fuel_type: str = "LSFO",
        overwrite: bool = True,
        sn_mapping: dict = None,
        bunker_port: str = None,
        port_fuel_type: str = None,
    ) -> tuple[RouteBaseline, "ContextEnrichResult"]:
        """
        ServiceContext를 적용한 BSA 기반 P&L 통합.

        Parameters
        ----------
        fuel_type : 항해/Maneuvering 유종 (메인엔진)
        bunker_port : 벙커링 공급 항구
        port_fuel_type : 정박/Buffer 유종 (None이면 fuel_type과 동일)
        """
        # 1) 1척 기준 운항원가 계산
        cost = self.cost_calc.calculate(
            ctx.service_code, vessel_type, year, month, fuel_type,
            bunker_port=bunker_port,
            port_fuel_type=port_fuel_type,
        )

        # 2) ServiceContext 적용 → 자사 부담 + 임대/임차
        own_breakdown = cost.apply_service_context(ctx)

        # 3) E/W 분배 (1척 기준 원본을 우선 분배)
        full_alloc = self.allocator.allocate(cost, sn_mapping=sn_mapping)

        # 4) E/W 비율 계산 (1척 기준 분배의 비율을 자사 부담에 그대로 적용)
        total_fuel = full_alloc.east_fuel + full_alloc.west_fuel
        total_port = full_alloc.east_port_charge + full_alloc.west_port_charge
        total_charter = full_alloc.east_charter + full_alloc.west_charter

        # E/W 비율 (자사 부담을 같은 비율로 분배)
        def split(east_val, west_val, total_val, own_amount):
            if total_val == 0:
                return 0.0, 0.0
            e_ratio = east_val / total_val
            return own_amount * e_ratio, own_amount * (1 - e_ratio)

        own_fuel_e, own_fuel_w = split(
            full_alloc.east_fuel, full_alloc.west_fuel,
            total_fuel, own_breakdown.own_fuel,
        )
        own_port_e, own_port_w = split(
            full_alloc.east_port_charge, full_alloc.west_port_charge,
            total_port, own_breakdown.own_port_charge,
        )
        own_charter_e, own_charter_w = split(
            full_alloc.east_charter, full_alloc.west_charter,
            total_charter, own_breakdown.own_charter_hire,
        )

        # 임대/임차도 운항원가 비율로 E/W 분배 (단순화)
        own_total_e = own_fuel_e + own_port_e + own_charter_e
        own_total_w = own_fuel_w + own_port_w + own_charter_w
        own_total = own_total_e + own_total_w

        def split_amount(amount):
            if own_total == 0:
                return amount / 2, amount / 2
            e_ratio = own_total_e / own_total
            return amount * e_ratio, amount * (1 - e_ratio)

        lending_e, lending_w = split_amount(own_breakdown.slot_lending_revenue)
        charter_e, charter_w = split_amount(own_breakdown.slot_charter_cost)

        # 5) baseline에 주입
        enriched = deepcopy(baseline)

        # 자사 부담 운항원가 (E/W)
        self._inject_var(enriched.east.voyage_var_cost, own_fuel_e, own_port_e, overwrite)
        self._inject_var(enriched.west.voyage_var_cost, own_fuel_w, own_port_w, overwrite)
        self._inject_fixed_charter(enriched.east.voyage_fixed_cost, own_charter_e, overwrite)
        self._inject_fixed_charter(enriched.west.voyage_fixed_cost, own_charter_w, overwrite)

        # 임대 수익 → slot_revenue (매출)
        if overwrite or enriched.east.revenue.slot_revenue == 0:
            enriched.east.revenue.slot_revenue = lending_e
        if overwrite or enriched.west.revenue.slot_revenue == 0:
            enriched.west.revenue.slot_revenue = lending_w

        # 임차 비용 → slot_charter (운항고정비)
        if overwrite or enriched.east.voyage_fixed_cost.slot_charter == 0:
            enriched.east.voyage_fixed_cost.slot_charter = charter_e
        if overwrite or enriched.west.voyage_fixed_cost.slot_charter == 0:
            enriched.west.voyage_fixed_cost.slot_charter = charter_w

        result = ContextEnrichResult(
            ctx=ctx,
            own_breakdown=own_breakdown,
            full_alloc=full_alloc,
            warnings=full_alloc.warnings.copy(),
        )

        # 7일 배수 검증 결과 추가
        validation = ctx.validate_voyage_days(cost.charter.voyage_days)
        if not validation["valid"]:
            result.warnings.append(
                f"7일 배수 미일치: 이론 {validation['expected_days']}일, "
                f"실제 {validation['actual_days']:.1f}일 "
                f"({validation['needs_adjustment_hours']:+.1f}h 조정 필요)"
            )

        return enriched, result

    @staticmethod
    def _inject_var(target: VoyageVariableCost, fuel: float, port: float, overwrite: bool):
        if overwrite or target.fuel == 0:
            target.fuel = fuel
        if overwrite or target.port_charge == 0:
            target.port_charge = port

    @staticmethod
    def _inject_fixed_charter(target: VoyageFixedCost, charter: float, overwrite: bool):
        if overwrite or target.charter_hire == 0:
            target.charter_hire = charter
