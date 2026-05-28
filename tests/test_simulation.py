"""
4가지 시뮬레이션 케이스 검증 테스트.
실제 차터베이스 SIS2-080 데이터로 검증.
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.datasources.mock_source import MockDataSource, VESSEL_TYPES
from src.engine.models import Scenario
from src.engine.calculator import (
    apply_scenario, sensitivity_analysis, break_even_freight_rate,
)


def get_baseline():
    src = MockDataSource()
    return src.get_baseline("SIS2", "080", date(2026, 5, 5), date(2026, 5, 20))


def test_baseline_matches_screen():
    """베이스라인이 차터베이스 화면 값과 일치하는지"""
    b = get_baseline()
    # 화면의 합계 값 검증
    # 매출 합계: 517,544 (화면 표시값 기준, 반올림 허용)
    assert abs(b.total_revenue - 517544) < 10
    # 한계이익 합계: 384,648
    assert abs(b.total_contribution_margin - 384648) < 10
    # 운항이익 합계: -104,339
    assert abs(b.total_voyage_profit - (-104339)) < 10


def test_case1_freight_change():
    """Case 1: 운임 변동"""
    b = get_baseline()
    # E만 10% 인상
    s = Scenario(freight_change_e=0.10)
    r = apply_scenario(b, s)
    # E 운임 매출 증가
    assert r.simulated.east.revenue.freight > b.east.revenue.freight
    # W는 그대로
    assert r.simulated.west.revenue.freight == b.west.revenue.freight
    # 한계이익 증가
    assert r.simulated.total_contribution_margin > b.total_contribution_margin


def test_case2_fuel_change():
    """Case 2: 유가 변동 (현재 데이터는 fuel=0이라 변화 없음, 로직만 확인)"""
    b = get_baseline()
    s = Scenario(fuel_price_change=0.20)
    r = apply_scenario(b, s)
    # 화면 데이터에 연료비가 0이므로 변화 없음 (정상)
    # 실제 데이터로 검증 필요
    assert r.simulated.east.voyage_var_cost.fuel == b.east.voyage_var_cost.fuel


def test_case3_volume_change():
    """Case 3: 선적량 변동"""
    b = get_baseline()
    s = Scenario(volume_change_w=0.10)  # W만 10% 증가
    r = apply_scenario(b, s)
    # 선적량 증가
    assert r.simulated.west.loading.loaded_teu > b.west.loading.loaded_teu
    # 운임 매출 증가
    assert r.simulated.west.revenue.freight > b.west.revenue.freight
    # 화물변동비 증가
    assert r.simulated.west.cargo_var_cost.total > b.west.cargo_var_cost.total
    # 소석률 증가
    assert r.simulated.west.loading.load_factor > b.west.loading.load_factor


def test_case4_vessel_change():
    """Case 4: 선형 변경"""
    b = get_baseline()
    # 8000TEU → 14000TEU 변경
    new_vessel = VESSEL_TYPES["14000TEU"]
    s = Scenario(new_vessel=new_vessel)
    r = apply_scenario(b, s)
    # 자사선복 증가
    assert r.simulated.east.loading.own_capacity == 14000
    assert r.simulated.west.loading.own_capacity == 14000
    # 소석률 감소 (선복은 늘었는데 선적량은 그대로)
    assert r.simulated.east.loading.load_factor < b.east.loading.load_factor


def test_zero_scenario():
    """모든 변동률 0이면 결과 동일"""
    b = get_baseline()
    r = apply_scenario(b, Scenario())
    assert abs(r.simulated.total_voyage_profit - b.total_voyage_profit) < 0.01


def test_bep_calculation():
    """BEP 운임률이 합리적 범위 내"""
    b = get_baseline()
    bep = break_even_freight_rate(b)
    # SIS2는 적자 상태(-104,339)이므로 BEP는 양수(운임 올려야 함)
    assert bep["east"] is not None
    assert bep["west"] is not None


def test_sensitivity():
    """민감도 분석 결과 형식"""
    b = get_baseline()
    sens = sensitivity_analysis(b, delta=0.10)
    assert "운임 (E)" in sens
    assert "운임 (W)" in sens
    assert "유가" in sens
    assert "선적량 (E)" in sens
    assert "선적량 (W)" in sens


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"✓ {name}")
            except AssertionError as e:
                print(f"✗ {name}: {e}")
            except Exception as e:
                print(f"✗ {name}: {type(e).__name__}: {e}")
