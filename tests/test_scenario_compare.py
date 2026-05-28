"""
시나리오 비교 엔진 테스트.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.engine.scenario_compare import ScenarioSpec, ScenarioComparator


def test_basic_spec_creation():
    """ScenarioSpec 기본 생성"""
    spec = ScenarioSpec(
        name="Test",
        service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6,
        own_vessels=1,
    )
    assert spec.name == "Test"
    assert spec.fuel_type == "LSFO"  # 기본값
    assert spec.year == 2026


def test_evaluate_single_scenario():
    """단일 시나리오 계산"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    spec = ScenarioSpec(
        name="베이스", service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6, own_vessels=1,
    )
    result = comp.evaluate(spec)
    assert result.spec.name == "베이스"
    assert result.fuel_cost > 0
    assert result.charter_hire > 0
    assert result.bsa_teu > 0
    # BSA = 14T선복 × 1/6
    assert abs(result.bsa_teu - result.capacity_teu / 6) < 1


def test_per_teu_unit_correct():
    """TEU당 단가 = 1척 운항원가 / 1척 선복"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    spec = ScenarioSpec(
        name="X", service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6, own_vessels=1,
    )
    r = comp.evaluate(spec)
    expected = r.total_voyage_cost / r.capacity_teu
    assert abs(r.per_teu_unit - expected) < 0.01


def test_own_plus_lending_equals_total():
    """자사 부담 + 임대 수익 = 1척 총원가"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    spec = ScenarioSpec(
        name="X", service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6, own_vessels=1,
    )
    r = comp.evaluate(spec)
    if r.slot_balance_teu > 0:
        # 임대 케이스
        assert abs(r.own_total_cost + r.slot_lending_revenue - r.total_voyage_cost) < 1
    else:
        # 임차 케이스
        assert abs(r.own_total_cost - r.slot_charter_cost - r.total_voyage_cost) < 1


def test_evaluate_many():
    """여러 시나리오 일괄 계산"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    specs = [
        ScenarioSpec(name="S1", service_code="SMX",
                     vessel_type="Jiangsu 4250",
                     total_vessels=6, own_vessels=1),
        ScenarioSpec(name="S2", service_code="SMX",
                     vessel_type="Daewoo 4600",
                     total_vessels=6, own_vessels=1),
    ]
    results = comp.evaluate_many(specs)
    assert len(results) == 2


def test_compute_diffs():
    """베이스 대비 차이 계산"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    specs = [
        ScenarioSpec(name="베이스", service_code="SMX",
                     vessel_type="Jiangsu 4250",
                     total_vessels=6, own_vessels=1),
        ScenarioSpec(name="변경", service_code="SMX",
                     vessel_type="Daewoo 4600",
                     total_vessels=6, own_vessels=1),
    ]
    results = comp.evaluate_many(specs)
    diffs = comp.compute_diffs(results[0], results[1:])
    assert len(diffs) == 1
    # 차이 키 존재
    assert "voyage_days_diff" in diffs[0]
    assert "per_teu_diff" in diffs[0]
    assert "total_voyage_pct" in diffs[0]


def test_bsa_override():
    """BSA 수기 조정 동작"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    spec = ScenarioSpec(
        name="X", service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6, own_vessels=1,
        bsa_override=1000,
    )
    r = comp.evaluate(spec)
    assert r.bsa_teu == 1000


def test_larger_vessel_lower_per_teu():
    """업사이징 → TEU당 단가 낮아져야 함 (일반적으로)"""
    mgr = MasterDataManager()
    comp = ScenarioComparator(mgr)
    small = comp.evaluate(ScenarioSpec(
        name="작은선형", service_code="SMX",
        vessel_type="Jiangsu 4250",
        total_vessels=6, own_vessels=1,
    ))
    big = comp.evaluate(ScenarioSpec(
        name="큰선형", service_code="SMX",
        vessel_type="Hyundai 5000",
        total_vessels=6, own_vessels=1,
    ))
    # 큰 선형이 TEU당 단가 낮음 (규모의 경제)
    assert big.per_teu_unit < small.per_teu_unit


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
