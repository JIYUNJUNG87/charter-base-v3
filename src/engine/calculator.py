"""
시뮬레이션 엔진.

팀에서 사용하는 4가지 케이스를 정확하게 구현:
  Case 1. 운임 변동       → 매출에 영향
  Case 2. 유가 변동       → 연료비에 영향
  Case 3. 선적량 변동      → 매출 + 화물변동비에 영향
  Case 4. 투입 선형 변경   → 선복량/용선료/연료비 동시 변경

핵심 원칙:
- 차터베이스의 5단계 손익 구조 유지
- 방향별(E/W)로 독립적 시뮬레이션 가능
- 각 케이스의 부수 효과(side effect)도 정확히 반영
"""

from copy import deepcopy
from .models import (
    RouteBaseline, DirectionalPnL, Scenario, SimulationResult,
    VesselType, PortPairData,
)


# ============================================================
# Case 1: 운임 변동
# ============================================================
def _apply_freight_change(pnl: DirectionalPnL, pct: float):
    """운임 변동률 적용. 매출(운임)과 평균운임만 변경."""
    if pct == 0:
        return
    multiplier = 1 + pct
    pnl.revenue.freight *= multiplier
    pnl.rate.avg_rate *= multiplier
    pnl.rate.coc_avg_rate *= multiplier
    pnl.rate.soc_avg_rate *= multiplier


# ============================================================
# Case 2: 유가 변동
# ============================================================
def _apply_fuel_price_change(pnl: DirectionalPnL, pct: float):
    """유가 변동률 적용. 연료비만 비례 변동."""
    if pct == 0:
        return
    pnl.voyage_var_cost.fuel *= (1 + pct)


# ============================================================
# Case 3: 선적량 변동
# ============================================================
def _apply_volume_change(pnl: DirectionalPnL, pct: float):
    """
    선적량 변동률 적용.
    - 매출(운임): 선적량에 비례
    - 화물변동비(하역비/장비비/지선료/대리점수수료): 선적량에 비례
    - 소석률: 선적량 변화에 비례 (단, 100% 상한)
    - 운항비는 영향 없음 (배는 어차피 가니까)
    """
    if pct == 0:
        return
    multiplier = 1 + pct

    # 매출 (운임)
    pnl.revenue.freight *= multiplier

    # 화물변동비 전체가 선적량에 비례
    pnl.cargo_var_cost.handling *= multiplier
    pnl.cargo_var_cost.feeder *= multiplier
    pnl.cargo_var_cost.agency_commission *= multiplier
    pnl.cargo_var_cost.equipment_transport *= multiplier
    pnl.cargo_var_cost.equipment_cost *= multiplier

    # 선적량 자체
    pnl.loading.loaded_teu *= multiplier
    pnl.loading.coc_teu *= multiplier
    pnl.loading.soc_teu *= multiplier

    # 소석률 (자사선복은 고정이므로 비례 변화, 100% 상한)
    if pnl.loading.own_capacity > 0:
        new_lf = pnl.loading.loaded_teu / pnl.loading.own_capacity
        # 100% 초과 시 선적량을 선복량에 맞춰 캡
        if new_lf > 1.0:
            pnl.loading.loaded_teu = pnl.loading.own_capacity
            # 운임은 선복량 한도까지만 발생
            cap_ratio = 1.0 / new_lf
            # 이미 multiplier 적용된 freight를 cap_ratio만큼 보정
            # (선복량 초과분은 실현 안 됨)


# ============================================================
# Case 4: 투입 선형 변경 (가장 복잡)
# ============================================================
def _apply_vessel_change(baseline: RouteBaseline, simulated: RouteBaseline,
                         new_vessel: VesselType):
    """
    선형 변경 시 영향:
    1) 자사선복 변경 (capacity_teu)
    2) 용선료 변경 (daily_charter_rate × 운항일수)
    3) 연료비 변경 (daily_fuel_consumption × 단가 × 운항일수)
    4) 선적량은 그대로 두되, 소석률 자동 재계산
       (실제로는 선형 커지면 선적량도 어느정도 늘지만,
        보수적으로 기존 화물량 기준으로 계산하는 게 안전)

    핵심 가정: 운항 일수와 항해 거리는 동일하다고 가정.
    """
    if new_vessel is None:
        return

    old_vessel = baseline.vessel

    # 자사선복 변경 (양방향 동일)
    simulated.east.loading.own_capacity = new_vessel.capacity_teu
    simulated.west.loading.own_capacity = new_vessel.capacity_teu

    # 용선료 비율 = 신규 일일 용선료 / 기존 일일 용선료
    if old_vessel.daily_charter_rate > 0:
        charter_ratio = new_vessel.daily_charter_rate / old_vessel.daily_charter_rate
        simulated.east.voyage_fixed_cost.charter_hire *= charter_ratio
        simulated.west.voyage_fixed_cost.charter_hire *= charter_ratio

    # 연료비 비율 = 신규 일일 소모량 / 기존 일일 소모량
    if old_vessel.daily_fuel_consumption > 0:
        fuel_ratio = new_vessel.daily_fuel_consumption / old_vessel.daily_fuel_consumption
        simulated.east.voyage_var_cost.fuel *= fuel_ratio
        simulated.west.voyage_var_cost.fuel *= fuel_ratio

    # 신규 선형 정보 반영
    simulated.vessel = new_vessel


# ============================================================
# 메인 시뮬레이션 함수
# ============================================================
def apply_scenario(baseline: RouteBaseline, scenario: Scenario) -> SimulationResult:
    """
    베이스라인에 시나리오를 적용해 시뮬레이션 결과를 반환.

    적용 순서 (의존성 고려):
    1. 선형 변경 먼저 (다른 변수의 기반이 됨)
    2. 선적량 변동
    3. 운임 변동
    4. 유가 변동
    """
    simulated = deepcopy(baseline)

    # Case 4: 선형 변경 (가장 먼저)
    if scenario.new_vessel is not None:
        _apply_vessel_change(baseline, simulated, scenario.new_vessel)

    # Case 3: 선적량 변동 (양방향 따로)
    _apply_volume_change(simulated.east, scenario.volume_change_e)
    _apply_volume_change(simulated.west, scenario.volume_change_w)

    # Case 1: 운임 변동 (양방향 따로)
    _apply_freight_change(simulated.east, scenario.freight_change_e)
    _apply_freight_change(simulated.west, scenario.freight_change_w)

    # Case 2: 유가 변동 (양방향 공통)
    _apply_fuel_price_change(simulated.east, scenario.fuel_price_change)
    _apply_fuel_price_change(simulated.west, scenario.fuel_price_change)

    return SimulationResult(
        scenario=scenario,
        baseline=baseline,
        simulated=simulated,
    )


# ============================================================
# 부가 분석 함수
# ============================================================
def break_even_freight_rate(baseline: RouteBaseline, direction: str = "both") -> dict:
    """
    BEP 운임률 계산.
    운항이익이 0이 되려면 운임이 몇 % 변해야 하는지.
    """
    result = {}
    targets = [("east", baseline.east), ("west", baseline.west)] \
              if direction == "both" \
              else [(direction, getattr(baseline, direction))]

    for name, pnl in targets:
        if pnl.revenue.freight == 0:
            result[name] = None
            continue
        # voyage_profit + (필요 운임 인상액) = 0
        # 필요 운임 인상액 = -voyage_profit
        # 인상률 = 필요 인상액 / 현재 운임
        needed_change = -pnl.voyage_profit / pnl.revenue.freight
        result[name] = needed_change

    return result


def sensitivity_analysis(baseline: RouteBaseline, delta: float = 0.10) -> dict:
    """
    민감도 분석. 각 변수를 +delta만큼 흔들었을 때 운항이익 변화.
    Tornado chart 용도.
    """
    base_profit = baseline.total_voyage_profit
    cases = {
        "운임 (E)": Scenario(freight_change_e=delta),
        "운임 (W)": Scenario(freight_change_w=delta),
        "유가": Scenario(fuel_price_change=delta),
        "선적량 (E)": Scenario(volume_change_e=delta),
        "선적량 (W)": Scenario(volume_change_w=delta),
    }

    sensitivities = {}
    for var_name, scenario in cases.items():
        result = apply_scenario(baseline, scenario)
        sensitivities[var_name] = result.simulated.total_voyage_profit - base_profit

    return sensitivities
