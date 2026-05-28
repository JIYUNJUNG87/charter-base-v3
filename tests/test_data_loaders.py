"""
데이터 로더 통합 테스트.
모든 로더의 기본 기능과 실제 데이터로 시나리오를 검증.
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager


def test_manager_initialization():
    """매니저가 5개 로더를 모두 초기화하는지"""
    mgr = MasterDataManager()
    assert mgr.bunker is not None
    assert mgr.hire is not None
    assert mgr.port_charge is not None
    assert mgr.vessel_spec is not None
    assert mgr.service is not None


def test_bunker_data():
    mgr = MasterDataManager()
    df = mgr.bunker.load()
    assert len(df) > 0
    assert "LSFO" in mgr.bunker.get_available_fuel_types()
    assert "KOR" in mgr.bunker.get_available_ports()
    # 최신 LSFO 한국 단가가 존재
    latest = mgr.bunker.get_latest_price("LSFO", "KOR")
    assert latest is not None
    assert latest[1] > 0


def test_hire_data():
    mgr = MasterDataManager()
    cats = mgr.hire.get_categories()
    assert len(cats) == 20  # CA1 ~ CA20
    # 8000TEU 매칭 가능
    result = mgr.hire.get_rate_by_teu(2026, 1, 8000)
    assert result is not None
    cat, rate = result
    assert rate > 0


def test_port_charge_data():
    mgr = MasterDataManager()
    df = mgr.port_charge.load()
    assert len(df) > 0
    # 부산항이 존재
    busan = mgr.port_charge.get_charge("KRPUS", "CA8")
    assert busan is not None
    assert busan > 0


def test_vessel_spec_data():
    mgr = MasterDataManager()
    types = mgr.vessel_spec.get_types()
    assert len(types) > 0
    # Jiangsu 4250의 18노트 소모량 = 59.5
    cons = mgr.vessel_spec.get_consumption("Jiangsu 4250", 18)
    assert cons == 59.5
    # 보간 테스트: 18.5노트
    cons_interp = mgr.vessel_spec.get_consumption("Jiangsu 4250", 18.5)
    assert cons_interp is not None
    assert 59.5 < cons_interp < 70.5  # 18노트와 19노트 사이


def test_service_data():
    mgr = MasterDataManager()
    services = mgr.service.get_services()
    assert len(services) > 0
    # ANX 서비스 요약
    summary = mgr.service.get_service_summary("ANX")
    assert summary is not None
    assert summary["leg_count"] > 0
    assert summary["total_distance_nm"] > 0


def test_end_to_end_data_flow():
    """
    실제 시나리오:
    ANX 서비스의 첫 구간(KRINC→KRPUS, 406NM, 18노트)에 대해
    4500TEU급 선형이 투입된다고 가정하고 필요한 모든 데이터를 조회.
    """
    mgr = MasterDataManager()

    # 1. 서비스 정보
    anx_legs = mgr.service.get_legs("ANX")
    first_leg = anx_legs.iloc[0]
    assert first_leg["from_port"] == "KRINC"
    assert first_leg["to_port"] == "KRPUS"

    # 2. 선형 스펙 (4500TEU급)
    similar = mgr.vessel_spec.find_types_by_teu(4500, 0.10)
    assert len(similar) > 0
    vessel = similar.iloc[0]

    # 3. 18노트 소모량
    consumption = mgr.vessel_spec.get_consumption(vessel["type_name"], 18)
    assert consumption is not None

    # 4. 연료 단가 (한국)
    latest = mgr.bunker.get_latest_price("LSFO", "KOR")
    assert latest is not None

    # 5. 항비 (부산항, 4500TEU)
    charge = mgr.port_charge.get_charge_by_teu("KRPUS", 4500)
    assert charge is not None

    # 6. 용선료 (4500TEU, 2026년 1월)
    hire = mgr.hire.get_rate_by_teu(2026, 1, 4500)
    assert hire is not None

    print(f"\n  [End-to-End 시나리오 검증]")
    print(f"  - 첫 구간: {first_leg['from_port']} → {first_leg['to_port']} "
          f"({first_leg['distance_nm']}NM, {first_leg['speed_knot']}knot)")
    print(f"  - 투입 선형: {vessel['type_name']} ({vessel['teu_nominal']:.0f}TEU)")
    print(f"  - 18노트 소모량: {consumption:.1f} ton/day")
    print(f"  - LSFO 한국 단가: ${latest[1]:.1f}/ton ({latest[0]})")
    print(f"  - 부산항 항비: {charge}")
    print(f"  - 일일 용선료: {hire}")


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
