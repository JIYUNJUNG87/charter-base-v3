"""
차터베이스(Charter Base) 양식 기반 데이터 모델.

회사 차터베이스 화면 구조를 그대로 반영:
- East/West 양방향 분리
- 5단계 손익 구조: 매출 → 한계이익 → 운항이익 → 월간손익
- 포트별 소석률/운임 매트릭스
- 컨테이너 타입(COC/SOC, 20ft/40ft) 구분
- 선형 정보 (시뮬레이션 변수)
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import date


Direction = Literal["E", "W"]


# ============================================================
# 1. 선형(투입 선박) 정보 - 시뮬레이션 변수 #4 대상
# ============================================================
@dataclass
class VesselType:
    """선형 정보. 선형을 바꾸면 선복량/연료소모/용선료가 함께 바뀜."""
    vessel_class: str                 # 예: "8000TEU", "14000TEU"
    capacity_teu: float               # 선복량 (TEU)
    daily_fuel_consumption: float     # 일일 연료 소모량 (ton/day)
    daily_charter_rate: float         # 일일 용선료 (USD/day)
    service_speed: float              # 항해속도 (knot)


# ============================================================
# 2. 선적정보 (차터베이스 '선적정보' 섹션)
# ============================================================
@dataclass
class LoadingInfo:
    """선적 정보 (방향별)"""
    own_capacity: float = 0.0         # 자사선복
    loaded_teu: float = 0.0           # 선적량
    coc_teu: float = 0.0              # COC (Carrier Owned Container)
    soc_teu: float = 0.0              # SOC (Shipper Owned Container)
    empty_container: float = 0.0      # 공컨테이너

    @property
    def total_loaded(self) -> float:
        return self.loaded_teu + self.empty_container

    @property
    def load_factor(self) -> float:
        """소석률 = 선적량 / 자사선복"""
        if self.own_capacity == 0:
            return 0.0
        return self.loaded_teu / self.own_capacity

    @property
    def total_load_factor(self) -> float:
        """총 소석률 = (선적량 + 공컨) / 자사선복"""
        if self.own_capacity == 0:
            return 0.0
        return self.total_loaded / self.own_capacity


# ============================================================
# 3. 운임 정보 (차터베이스 '평균운임' 라인)
# ============================================================
@dataclass
class RateInfo:
    """운임 정보 (방향별)"""
    avg_rate: float = 0.0             # 평균운임
    coc_avg_rate: float = 0.0         # COC 평균운임
    soc_avg_rate: float = 0.0         # SOC 평균운임


# ============================================================
# 4. 매출 (차터베이스 '매출' 섹션)
# ============================================================
@dataclass
class Revenue:
    """매출 (방향별)"""
    freight: float = 0.0              # 운임
    charter_revenue: float = 0.0      # 대선료 (선박을 빌려준 수익)
    slot_revenue: float = 0.0         # 선복임대료

    @property
    def total(self) -> float:
        return self.freight + self.charter_revenue + self.slot_revenue


# ============================================================
# 5. 화물변동비 (차터베이스 '화물변동비' 섹션)
# ============================================================
@dataclass
class CargoVariableCost:
    """화물변동비 (방향별) - 물동량에 비례"""
    handling: float = 0.0             # 하역비
    feeder: float = 0.0               # 지선료
    agency_commission: float = 0.0    # 대리점수수료
    equipment_transport: float = 0.0  # 장비이송비
    equipment_cost: float = 0.0       # 장비비

    @property
    def total(self) -> float:
        return (self.handling + self.feeder + self.agency_commission
                + self.equipment_transport + self.equipment_cost)


# ============================================================
# 6. 운항변동비 (차터베이스 '운항변동비' 섹션)
# ============================================================
@dataclass
class VoyageVariableCost:
    """운항변동비 (방향별) - 운항 자체에 비례"""
    port_charge: float = 0.0          # 항비
    fuel: float = 0.0                 # 연료비

    @property
    def total(self) -> float:
        return self.port_charge + self.fuel


# ============================================================
# 7. 운항고정비 (차터베이스 '운항고정비' 섹션)
# ============================================================
@dataclass
class VoyageFixedCost:
    """운항고정비 (방향별) - 운항 여부와 무관"""
    charter_hire: float = 0.0         # 용선료
    slot_charter: float = 0.0         # 선복임차료

    @property
    def total(self) -> float:
        return self.charter_hire + self.slot_charter


# ============================================================
# 8. 방향별 P&L (E 또는 W 한 방향)
# ============================================================
@dataclass
class DirectionalPnL:
    """단일 방향(East 또는 West)의 P&L"""
    direction: Direction
    loading: LoadingInfo = field(default_factory=LoadingInfo)
    rate: RateInfo = field(default_factory=RateInfo)
    revenue: Revenue = field(default_factory=Revenue)
    cargo_var_cost: CargoVariableCost = field(default_factory=CargoVariableCost)
    voyage_var_cost: VoyageVariableCost = field(default_factory=VoyageVariableCost)
    voyage_fixed_cost: VoyageFixedCost = field(default_factory=VoyageFixedCost)

    # ===== 5단계 손익 (차터베이스 양식 그대로) =====
    @property
    def contribution_margin(self) -> float:
        """한계이익 = 매출 - 화물변동비"""
        return self.revenue.total - self.cargo_var_cost.total

    @property
    def voyage_profit(self) -> float:
        """운항이익 = 한계이익 - 운항변동비 - 운항고정비"""
        return (self.contribution_margin
                - self.voyage_var_cost.total
                - self.voyage_fixed_cost.total)

    @property
    def total_cost(self) -> float:
        """총비용 = 화물변동비 + 운항변동비 + 운항고정비"""
        return (self.cargo_var_cost.total
                + self.voyage_var_cost.total
                + self.voyage_fixed_cost.total)

    @property
    def teu_unit_cost(self) -> float:
        """TEU 원가 = 운항원가 / 선적량"""
        if self.loading.loaded_teu == 0:
            return 0.0
        return self.total_cost / self.loading.loaded_teu


# ============================================================
# 9. 포트별 운임/물동량 (차터베이스 우측 패널)
# ============================================================
@dataclass
class PortPairData:
    """포트 페어별 데이터 (예: KRPUS → CNSHA)"""
    direction: Direction
    origin_port: str                  # 출발항 (예: KRPUS)
    destination_port: str             # 도착항 (예: CNSHA)
    loaded_teu: float = 0.0           # 선적량
    avg_rate: float = 0.0             # 평균운임
    load_factor: float = 0.0          # 구간 소석률


# ============================================================
# 10. 항로 베이스라인 (차터베이스 한 항로의 한 기간 전체)
# ============================================================
@dataclass
class RouteBaseline:
    """
    차터베이스의 한 항로/한 기간 전체 데이터.
    화면의 '차터 결과' 한 행에 해당.
    """
    service_code: str                 # 서비스 코드 (예: SIS2)
    route_cb_no: str                  # Route CB No (예: 080)
    route_name: str                   # 항로명
    period_start: date
    period_end: date

    vessel: VesselType                # 투입 선형

    east: DirectionalPnL              # East 방향 (수출)
    west: DirectionalPnL              # West 방향 (수입)

    port_pairs: list[PortPairData] = field(default_factory=list)

    # ===== 합계 (East + West) =====
    @property
    def total_revenue(self) -> float:
        return self.east.revenue.total + self.west.revenue.total

    @property
    def total_cargo_var_cost(self) -> float:
        return self.east.cargo_var_cost.total + self.west.cargo_var_cost.total

    @property
    def total_voyage_var_cost(self) -> float:
        return self.east.voyage_var_cost.total + self.west.voyage_var_cost.total

    @property
    def total_voyage_fixed_cost(self) -> float:
        return self.east.voyage_fixed_cost.total + self.west.voyage_fixed_cost.total

    @property
    def total_contribution_margin(self) -> float:
        return self.east.contribution_margin + self.west.contribution_margin

    @property
    def total_voyage_profit(self) -> float:
        return self.east.voyage_profit + self.west.voyage_profit

    @property
    def total_cost(self) -> float:
        return (self.total_cargo_var_cost
                + self.total_voyage_var_cost
                + self.total_voyage_fixed_cost)


# ============================================================
# 11. 시뮬레이션 시나리오 (4가지 케이스)
# ============================================================
@dataclass
class Scenario:
    """
    시뮬레이션 시나리오.
    팀에서 가장 자주 사용하는 4가지 케이스를 중심으로 설계.

    각 변수는 방향별(E/W)로 따로 조정 가능. None이면 양방향 동일 적용.
    """
    name: str = "Base"

    # ===== Case 1: 운임 변동 =====
    freight_change_e: float = 0.0        # E방향 운임 변동률
    freight_change_w: float = 0.0        # W방향 운임 변동률

    # ===== Case 2: 유가 변동 =====
    fuel_price_change: float = 0.0       # 유가 변동률 (양방향 공통)

    # ===== Case 3: 선적량 변동 =====
    volume_change_e: float = 0.0         # E방향 선적량 변동률
    volume_change_w: float = 0.0         # W방향 선적량 변동률

    # ===== Case 4: 투입 선형 변경 =====
    new_vessel: Optional[VesselType] = None  # 신규 선형 (None이면 미변경)

    def apply_freight_both(self, pct: float):
        """양방향 동일하게 운임 변동"""
        self.freight_change_e = pct
        self.freight_change_w = pct

    def apply_volume_both(self, pct: float):
        """양방향 동일하게 선적량 변동"""
        self.volume_change_e = pct
        self.volume_change_w = pct


# ============================================================
# 12. 시뮬레이션 결과
# ============================================================
@dataclass
class SimulationResult:
    scenario: Scenario
    baseline: RouteBaseline
    simulated: RouteBaseline

    @property
    def voyage_profit_change(self) -> float:
        return (self.simulated.total_voyage_profit
                - self.baseline.total_voyage_profit)

    @property
    def contribution_margin_change(self) -> float:
        return (self.simulated.total_contribution_margin
                - self.baseline.total_contribution_margin)
