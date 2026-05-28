"""
시뮬레이션 엔진과 운항원가 계산기 통합 테스트.
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.datasources.mock_source import MockDataSource
from src.cost_calculators import VoyageCostIntegrator, CostAllocator
from src.cost_calculators.voyage_cost_calculator import VoyageCostCalculator
from src.engine.calculator import apply_scenario
from src.engine.models import Scenario


# 대부분 서비스는 E/W로 표기되므로 SIS2를 기본 검증 대상으로 사용
DEFAULT_SERVICE = "SIS2"
DEFAULT_VESSEL = "Jiangsu 4250"

# ANX 처럼 S/N으로 표기하는 경우 매핑 룰
ANX_SN_MAPPING = {"S": "W", "N": "E"}  # 회사 정책에 따라 결정되어야 함


def get_baseline():
    src = MockDataSource()
    return src.get_baseline("SIS2", "080", date(2026,5,5), date(2026,5,20))


def test_direction_normalization_ew_direct():
    """E/W는 직접 매핑"""
    mgr = MasterDataManager()
    allocator = CostAllocator(mgr)
    assert allocator._normalize_direction("E") == "E"
    assert allocator._normalize_direction("W") == "W"
    assert allocator._normalize_direction("east") == "E"


def test_direction_normalization_sn_requires_mapping():
    """S/N은 매핑 없으면 None, 매핑 있으면 그대로 적용"""
    mgr = MasterDataManager()
    allocator = CostAllocator(mgr)
    assert allocator._normalize_direction("S") is None
    assert allocator._normalize_direction("N") is None
    mapping = {"S": "W", "N": "E"}
    assert allocator._normalize_direction("S", mapping) == "W"
    assert allocator._normalize_direction("N", mapping) == "E"
    mapping2 = {"S": "E", "N": "W"}
    assert allocator._normalize_direction("S", mapping2) == "E"


def test_allocation_sums_match_ew_service():
    """E/W로 직접 표기된 서비스(SIS2)의 분배 합계 일치"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    allocator = CostAllocator(mgr)

    cost = calc.calculate(DEFAULT_SERVICE, DEFAULT_VESSEL, 2026, 1, "LSFO")
    alloc = allocator.allocate(cost)

    assert abs(alloc.total_fuel - cost.total_fuel_usd) < 1
    assert abs(alloc.total_port_charge - cost.total_port_charge_usd) < 1
    assert abs(alloc.total_charter - cost.total_charter_usd) < 1
    assert alloc.unallocated_fuel == 0


def test_sn_service_unallocated_without_mapping():
    """S/N 서비스에 매핑 없이 분배하면 unallocated + 경고"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    allocator = CostAllocator(mgr)

    cost = calc.calculate("ANX", "Jiangsu 4250", 2026, 1, "LSFO")
    alloc = allocator.allocate(cost)

    assert alloc.unallocated_fuel > 0
    assert alloc.east_fuel == 0
    assert alloc.west_fuel == 0
    assert any("sn_mapping" in w for w in alloc.warnings)


def test_sn_service_with_mapping():
    """S/N 서비스도 매핑 제공하면 정상 분배"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    allocator = CostAllocator(mgr)

    cost = calc.calculate("ANX", "Jiangsu 4250", 2026, 1, "LSFO")
    alloc = allocator.allocate(cost, sn_mapping=ANX_SN_MAPPING)

    assert alloc.unallocated_fuel == 0
    assert alloc.east_fuel > 0
    assert alloc.west_fuel > 0
    assert abs(alloc.total_fuel - cost.total_fuel_usd) < 1


def test_baseline_enrichment_overwrite():
    """overwrite=True면 mock 값을 덮어씀"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    baseline = get_baseline()

    enriched, _ = integrator.enrich_baseline(
        baseline, DEFAULT_SERVICE, DEFAULT_VESSEL, 2026, 1, "LSFO",
        overwrite=True,
    )

    assert enriched.east.voyage_var_cost.fuel > 0
    assert enriched.east.voyage_var_cost.port_charge > 0
    assert enriched.east.voyage_fixed_cost.charter_hire > 0


def test_baseline_enrichment_preserve():
    """overwrite=False면 기존 값 보존"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    baseline = get_baseline()

    baseline.east.voyage_var_cost.fuel = 12345
    enriched, _ = integrator.enrich_baseline(
        baseline, DEFAULT_SERVICE, DEFAULT_VESSEL, 2026, 1, "LSFO",
        overwrite=False,
    )

    assert enriched.east.voyage_var_cost.fuel == 12345
    assert enriched.east.voyage_var_cost.port_charge > 0


def test_vessel_change_affects_costs():
    """선형 변경 시 비용이 변해야 함"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    baseline = get_baseline()

    enriched1, _ = integrator.enrich_baseline(
        baseline, DEFAULT_SERVICE, "Samsung 4000", 2026, 1, "LSFO",
        overwrite=True,
    )
    enriched2, _ = integrator.simulate_vessel_change(
        baseline, DEFAULT_SERVICE, "Daewoo 4600", 2026, 1, "LSFO",
    )

    assert (enriched1.east.voyage_var_cost.fuel
            != enriched2.east.voyage_var_cost.fuel)


def test_enriched_baseline_works_with_scenario():
    """채워진 baseline이 시나리오 시뮬레이션에서 정상 동작"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    baseline = get_baseline()

    enriched, _ = integrator.enrich_baseline(
        baseline, DEFAULT_SERVICE, DEFAULT_VESSEL, 2026, 1, "LSFO",
        overwrite=True,
    )

    scenario = Scenario(fuel_price_change=0.20)
    result = apply_scenario(enriched, scenario)

    assert (result.simulated.east.voyage_var_cost.fuel
            > result.baseline.east.voyage_var_cost.fuel)
    assert (result.simulated.total_voyage_profit
            < result.baseline.total_voyage_profit)


def test_anx_with_sn_mapping_via_integrator():
    """ANX(S/N 표기)도 통합기에서 매핑 전달하면 정상 동작"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    baseline = get_baseline()

    enriched, alloc = integrator.enrich_baseline(
        baseline, "ANX", "Jiangsu 4250", 2026, 1, "LSFO",
        overwrite=True,
        sn_mapping=ANX_SN_MAPPING,
    )

    assert enriched.east.voyage_var_cost.fuel > 0
    assert enriched.west.voyage_var_cost.fuel > 0
    assert alloc.unallocated_fuel == 0


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
