"""
ServiceContext 단위 테스트.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.engine.service_context import (
    ServiceContext, create_service_context_from_vessel,
    DAYS_PER_VESSEL, DEFAULT_WEIGHT_BASIS_TON,
)


def test_basic_creation():
    """기본 생성"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
    )
    assert ctx.service_code == "ANX"
    assert ctx.operation_type == "shared"  # 기본값
    assert ctx.weight_basis_ton == 14.0


def test_auto_bsa_calculation():
    """자동 BSA = 1척_선복 × (자사_척수 / 총_척수)"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
    )
    # 4000 × 1/6 = 666.67
    assert abs(ctx.auto_bsa_teu - 666.67) < 1.0


def test_bsa_override():
    """수기 BSA 적용"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
        own_bsa_teu=666,
    )
    assert ctx.effective_bsa_teu == 666  # 수기값
    assert abs(ctx.auto_bsa_teu - 666.67) < 1.0  # 자동값은 계산은 됨


def test_slot_balance_lender():
    """자사 제공 > BSA → 임대 (lender)"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
        own_bsa_teu=666,
    )
    # 제공 4000, BSA 666 → +3334
    assert ctx.slot_balance_teu > 0
    assert ctx.slot_position == "lender"


def test_slot_balance_renter():
    """BSA > 자사 제공 → 임차 (renter)"""
    ctx = ServiceContext(
        service_code="X",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=2000,
        own_vessels_deployed=1,
        own_bsa_teu=1500,  # 1척 2000인데 BSA 1500이면 +500. 임차 케이스 만들어야 함
    )
    # 제공 2000, BSA 1500 → +500, lender
    # 임차 케이스 따로
    ctx2 = ServiceContext(
        service_code="X",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=2000,
        own_vessels_deployed=1,
        own_bsa_teu=2500,  # BSA > 제공
    )
    assert ctx2.slot_balance_teu < 0
    assert ctx2.slot_position == "renter"


def test_charter_only():
    """순수 임차: 자사 배 없음"""
    ctx = ServiceContext(
        service_code="X",
        operation_type="charter_only",
        total_vessels_in_service=4,
        vessel_capacity_teu_14t=3000,
        own_vessels_deployed=0,
        own_bsa_teu=200,
    )
    # 자사 배 0척 → 제공 0
    # BSA 200 → 200 전체가 임차
    assert ctx.slot_balance_teu == -200
    assert ctx.slot_position == "renter"


def test_per_teu_unit_uses_full_capacity():
    """단가는 1척 운항원가 / 1척 전체 선복 (해석 B)"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
        own_bsa_teu=666,
    )
    # 1척 운항원가 $2,544,478 가정
    unit = ctx.own_per_teu_cost(
        fuel_cost=671_726,
        port_charge=290_752,
        charter_hire=1_582_000,
    )
    # 단가 = 2,544,478 / 4000 = 636.12
    assert abs(unit["per_teu_unit"] - 636.12) < 0.5
    # 자사 부담 = 666 × 636.12 = 423,656
    assert abs(unit["own_total_cost"] - 423_656) < 5


def test_lending_revenue_matches_total():
    """자사 부담 + 임대 수익 = 1척 전체 운항원가"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
        own_bsa_teu=666,
    )
    fuel, port, charter = 671_726, 290_752, 1_582_000
    total_per_vessel = fuel + port + charter

    unit = ctx.own_per_teu_cost(fuel, port, charter)
    lending = ctx.slot_lending_revenue(fuel, port, charter)

    # 자사 부담 + 임대 = 1척 전체
    assert abs((unit["own_total_cost"] + lending) - total_per_vessel) < 5


def test_expected_voyage_days():
    """7일 배수 = 총 척수 × 7"""
    ctx_4 = ServiceContext(service_code="X", total_vessels_in_service=4)
    ctx_6 = ServiceContext(service_code="X", total_vessels_in_service=6)
    assert ctx_4.expected_voyage_days == 28
    assert ctx_6.expected_voyage_days == 42


def test_validate_voyage_days_match():
    """실제 항차일수 = 이론값 → valid"""
    ctx = ServiceContext(service_code="X", total_vessels_in_service=4)
    v = ctx.validate_voyage_days(28.0)
    assert v["valid"]
    assert v["diff_hours"] == 0


def test_validate_voyage_days_mismatch():
    """실제 항차일수가 이론값과 다르면 invalid + 조정값 제공"""
    ctx = ServiceContext(service_code="X", total_vessels_in_service=4)
    v = ctx.validate_voyage_days(25.0)  # 이론 28, 실제 25
    assert not v["valid"]
    # 25 - 28 = -3일 = -72시간 (실제가 짧음)
    assert v["diff_hours"] == -72
    # 늘려야 함 (+72시간 추가)
    assert v["needs_adjustment_hours"] == 72


def test_create_from_vessel_uses_14t():
    """헬퍼는 14TON 기준 선복 우선 사용"""
    vessel_info = {
        "teu_nominal": 4249,
        "teu_at_14t": 2781,
    }
    ctx = create_service_context_from_vessel(
        service_code="ANX",
        vessel_spec_info=vessel_info,
        total_vessels=6,
        own_vessels=1,
    )
    assert ctx.vessel_capacity_teu_14t == 2781


def test_create_from_vessel_fallback_to_nominal():
    """14TON 없으면 디자인 TEU fallback"""
    vessel_info = {
        "teu_nominal": 4249,
        "teu_at_14t": None,
    }
    ctx = create_service_context_from_vessel(
        service_code="X",
        vessel_spec_info=vessel_info,
        total_vessels=6,
        own_vessels=1,
    )
    assert ctx.vessel_capacity_teu_14t == 4249


def test_summary_includes_key_info():
    """summary() 텍스트에 핵심 정보 포함"""
    ctx = ServiceContext(
        service_code="ANX",
        total_vessels_in_service=6,
        vessel_capacity_teu_14t=4000,
        own_vessels_deployed=1,
        own_bsa_teu=666,
    )
    s = ctx.summary()
    assert "ANX" in s
    assert "6척" in s
    assert "666" in s
    assert "수기 조정" in s


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
