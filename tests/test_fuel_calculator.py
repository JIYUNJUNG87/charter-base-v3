"""
연료비 계산기 검증 테스트.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.cost_calculators.fuel_calculator import FuelCostCalculator


def get_calc():
    return FuelCostCalculator(MasterDataManager())


def test_basic_calculation():
    """ANX 서비스 기본 계산"""
    calc = get_calc()
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    assert result.total_fuel_cost_usd > 0
    assert result.total_consumption_ton > 0
    assert len(result.leg_breakdowns) > 0


def test_all_modes_have_consumption():
    """4가지 모드 모두 소모량이 계산되어야 함"""
    calc = get_calc()
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    summary = result.summary()
    pct = summary["consumption_breakdown_pct"]
    # sea는 가장 큼, manv는 0이 아님, port는 0이 아님
    assert pct["sea"] > 50  # 항해가 가장 비중 큼
    assert pct["manv"] > 0
    assert pct["port"] > 0


def test_manv_ratio_affects_cost():
    """Maneuvering 비율 변경 시 연료비가 변해야 함"""
    mgr = MasterDataManager()
    calc_30 = FuelCostCalculator(mgr, {"manv_main_engine_ratio": 0.30})
    calc_50 = FuelCostCalculator(mgr, {"manv_main_engine_ratio": 0.50})

    r30 = calc_30.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    r50 = calc_50.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    # 50%가 더 비쌈
    assert r50.total_fuel_cost_usd > r30.total_fuel_cost_usd


def test_different_vessel_types_differ():
    """다른 선형은 다른 결과를 내야 함"""
    calc = get_calc()
    r1 = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    r2 = calc.calculate_service("ANX", "Samsung 4000", "LSFO")
    # 두 선형은 소모량 커브가 달라서 연료비도 다름
    assert r1.total_fuel_cost_usd != r2.total_fuel_cost_usd


def test_warnings_present():
    """가정값에 대한 경고가 항상 포함되어야 함"""
    calc = get_calc()
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    warning_text = " ".join(result.warnings)
    assert "Maneuvering" in warning_text  # MANV 가정 경고 필수


def test_port_mapping():
    """KRPUS 같은 항구는 KOR 단가로 매핑되어야 함"""
    calc = get_calc()
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    df = result.to_dataframe()
    # KRPUS로 도착하는 leg
    krpus_legs = df[df["to_port"] == "KRPUS"]
    if not krpus_legs.empty:
        assert krpus_legs.iloc[0]["bunker_port"] == "KOR"
    # CNSHA는 SHA로
    cnsha_legs = df[df["to_port"] == "CNSHA"]
    if not cnsha_legs.empty:
        assert cnsha_legs.iloc[0]["bunker_port"] == "SHA"


def test_time_total_matches_service():
    """계산된 시간 합계가 서비스 요약과 거의 일치해야 함"""
    calc = get_calc()
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    summary = result.summary()
    total = summary["time_breakdown_hours"]["total"]
    # ANX 총 시간은 약 672시간
    assert 600 < total < 700


def test_buffer_mode_in_port():
    """Buffer를 in_port 모드로 처리 시 main engine 없음"""
    mgr = MasterDataManager()
    calc = FuelCostCalculator(mgr, {"buffer_mode": "in_port"})
    result = calc.calculate_service("ANX", "Jiangsu 4250", "LSFO")
    # Buffer 비중이 작아야 함 (보조엔진만 가동)
    pct = result.summary()["consumption_breakdown_pct"]
    assert pct["buffer"] < 5  # buffer는 5% 미만


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
