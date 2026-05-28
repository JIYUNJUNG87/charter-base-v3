"""
운항원가 통합 계산기 테스트.
선형별 항비/용선료 매칭이 정확히 동작하는지 검증.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.cost_calculators import (
    VoyageCostCalculator,
    PortChargeCalculator,
    CharterRateCalculator,
)
from src.cost_calculators.port_charge_calculator import teu_to_port_category
from src.cost_calculators.charter_rate_calculator import teu_to_hire_category


def test_teu_to_port_category():
    """TEU → PORT_CHARGE 카테고리 매핑"""
    assert teu_to_port_category(1030) == ("CA1", False)
    assert teu_to_port_category(4250) == ("CA14", False)
    assert teu_to_port_category(5000) == ("CA15", False)
    # 5000 초과는 폴백
    assert teu_to_port_category(6500) == ("CA15", True)
    assert teu_to_port_category(8000) == ("CA15", True)
    assert teu_to_port_category(14000) == ("CA15", True)


def test_teu_to_hire_category():
    """TEU → HIRE 카테고리 매핑"""
    assert teu_to_hire_category(1030) == "CA1"
    assert teu_to_hire_category(4250) == "CA14"
    assert teu_to_hire_category(8000) == "CA20"
    assert teu_to_hire_category(14000) == "CA20"


def test_port_charge_basic():
    """ANX × Jiangsu 4250 항비 계산"""
    mgr = MasterDataManager()
    calc = PortChargeCalculator(mgr)
    result = calc.calculate_service("ANX", "Jiangsu 4250")
    assert result.matched_category == "CA14"
    assert not result.is_category_fallback
    assert result.total_port_charge_usd > 0


def test_port_charge_fallback_for_large_vessel():
    """8000TEU 선형은 CA15로 폴백되어야 함"""
    mgr = MasterDataManager()
    calc = PortChargeCalculator(mgr)
    # 5000TEU 초과 선형 찾기 (Daewoo 8000)
    big = mgr.vessel_spec.find_types_by_teu(8000, 0.2)
    if big.empty:
        return
    target = big.iloc[0]["type_name"]
    result = calc.calculate_service("ANX", target)
    assert result.is_category_fallback
    assert result.matched_category == "CA15"
    # 폴백 경고 메시지 포함
    assert any("폴백" in w for w in result.warnings)


def test_charter_rate_matches_category():
    """용선료 카테고리 매칭"""
    mgr = MasterDataManager()
    calc = CharterRateCalculator(mgr)
    # 4250TEU
    r1 = calc.calculate_service("ANX", "Jiangsu 4250", 2026, 1)
    assert r1.matched_category == "CA14"
    assert r1.daily_charter_rate_usd > 0
    # 항차 일수가 합리적 (ANX는 약 28일)
    assert 25 < r1.voyage_days < 35


def test_charter_rate_larger_vessel_costs_more():
    """큰 선형은 용선료가 더 비싸야 함"""
    mgr = MasterDataManager()
    calc = CharterRateCalculator(mgr)
    r_small = calc.calculate_service("ANX", "Jiangsu 4250", 2026, 1)
    # 8000TEU 선형
    big = mgr.vessel_spec.find_types_by_teu(8000, 0.2)
    if big.empty:
        return
    r_big = calc.calculate_service("ANX", big.iloc[0]["type_name"], 2026, 1)
    assert r_big.daily_charter_rate_usd > r_small.daily_charter_rate_usd
    assert r_big.total_charter_cost_usd > r_small.total_charter_cost_usd


def test_voyage_cost_integration():
    """3가지 비용이 모두 계산되어 합산됨"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    r = calc.calculate("ANX", "Jiangsu 4250", 2026, 1, "LSFO")
    assert r.total_fuel_usd > 0
    assert r.total_port_charge_usd > 0
    assert r.total_charter_usd > 0
    # 총합 = 3개 합
    assert abs(r.grand_total_usd
               - (r.total_fuel_usd + r.total_port_charge_usd + r.total_charter_usd)) < 0.01


def test_voyage_cost_share_realistic():
    """차터베이스 양식의 운항변동비/고정비 구분"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    r = calc.calculate("ANX", "Jiangsu 4250", 2026, 1, "LSFO")
    # 운항변동비 = 연료 + 항비
    assert abs(r.total_voyage_variable_cost_usd
               - (r.total_fuel_usd + r.total_port_charge_usd)) < 0.01
    # 운항고정비 = 용선료
    assert r.total_voyage_fixed_cost_usd == r.total_charter_usd


def test_no_spurious_fallback_warnings():
    """정상 매핑된 항구에 폴백 경고가 잘못 붙지 않아야 함"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    r = calc.calculate("ANX", "Jiangsu 4250", 2026, 1, "LSFO")
    # ANX의 항구들은 모두 한국/중국/동남아라 매핑됨
    # 폴백 경고가 ANX 항구들에 대해 나오면 안 됨
    fallback_warnings = [w for w in r.all_warnings if "fallback" in w.lower() and "단가" in w]
    assert len(fallback_warnings) == 0


def test_compare_vessels():
    """여러 선형 비교 기능"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    df = calc.compare_vessels(
        "ANX",
        ["Samsung 4000", "Jiangsu 4250", "Daewoo 4600"],
        2026, 1,
    )
    assert len(df) == 3
    # 모두 정상 계산됨
    assert df["total_usd"].notna().all()


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
