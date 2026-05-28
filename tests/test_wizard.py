"""
신규 항로 마법사 검증 테스트.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.wizard import (
    DistanceMatrix, StandardValueExtractor, ProformaBuilder,
)


def test_distance_matrix_forward():
    """정방향 거리 조회"""
    mgr = MasterDataManager()
    dm = DistanceMatrix(mgr)
    r = dm.get_distance("KRPUS", "CNSHA")
    assert r.found
    assert r.distance_nm > 0
    assert not r.is_reversed


def test_distance_matrix_reverse():
    """역방향 거리 조회 (정방향 없을 때)"""
    mgr = MasterDataManager()
    dm = DistanceMatrix(mgr)
    # VNSGN → KRPUS는 정방향 데이터 없음, KRPUS → VNSGN은 있음
    r = dm.get_distance("VNSGN", "KRPUS")
    assert r.found
    # is_reversed가 True거나 정방향 데이터가 새로 추가된 경우 둘 다 OK


def test_distance_matrix_missing():
    """존재하지 않는 항구 페어"""
    mgr = MasterDataManager()
    dm = DistanceMatrix(mgr)
    r = dm.get_distance("XYZ12", "ABC34")
    assert not r.found


def test_distance_matrix_filters_invalid():
    """1NM 같은 비합리적 거리는 필터링"""
    mgr = MasterDataManager()
    dm = DistanceMatrix(mgr)
    # 매트릭스의 모든 거리는 최소 임계값 이상이어야 함
    assert (dm._matrix["mean"] >= 5).all()


def test_standard_values_speed():
    """선속 통계가 합리적 범위"""
    mgr = MasterDataManager()
    sve = StandardValueExtractor(mgr)
    stats = sve.get_overall_speed_stats()
    assert "median" in stats
    assert 10 <= stats["median"] <= 25


def test_standard_values_dwell_time():
    """주요 항구의 정박시간 데이터 존재"""
    mgr = MasterDataManager()
    sve = StandardValueExtractor(mgr)
    # 부산은 가장 많이 등장하는 항구
    minutes, n = sve.get_port_dwell_time("KRPUS")
    assert n > 0
    assert minutes > 0


def test_standard_values_unknown_port():
    """미등록 항구는 기본값 반환"""
    mgr = MasterDataManager()
    sve = StandardValueExtractor(mgr)
    minutes, n = sve.get_port_dwell_time("XYZ12")
    assert n == 0
    assert minutes > 0  # 기본값


def test_build_from_scratch_basic():
    """처음부터 만들기 기본 동작"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="TEST1",
        service_name="Test Service",
        port_sequence=["KRPUS", "CNSHA", "VNSGN", "KRPUS"],
    )
    assert proforma.service_code == "TEST1"
    assert len(proforma.legs) == 3  # 4개 기항지 → 3구간
    assert proforma.total_distance_nm > 0
    assert proforma.total_time_hours > 0


def test_build_from_scratch_directions():
    """방향 자동 할당 (수출/수입 룰: KR→외국=W, 외국→KR=E)"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="TEST2",
        service_name="Test",
        port_sequence=["KRPUS", "CNSHA", "VNSGN", "THLCH", "KRPUS"],
        direction_pattern="ew",
    )
    # 기대값:
    # KRPUS→CNSHA: KR→외국 = W (수출)
    # CNSHA→VNSGN: 외국→외국 → 인접 따라감
    # VNSGN→THLCH: 외국→외국 → 인접 따라감
    # THLCH→KRPUS: 외국→KR = E (수입)
    directions = [leg.bnd for leg in proforma.legs]
    # 첫 구간은 수출, 마지막은 수입
    assert directions[0] == "W"
    assert directions[-1] == "E"


def test_direction_export_import_rule():
    """짚어준 케이스: KR↔KR 다음 구간 따라감 + KR→외국 = W"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="TEST_RULE",
        service_name="Test Rule",
        port_sequence=["KRPUS", "KRUSN", "KRKAN", "CNSHA", "KRPUS"],
        direction_pattern="ew",
    )
    directions = [leg.bnd for leg in proforma.legs]
    # KRPUS→KRUSN: KR→KR (다음 구간 따라 W)
    # KRUSN→KRKAN: KR→KR (다음 구간 따라 W)
    # KRKAN→CNSHA: KR→외국 (W)
    # CNSHA→KRPUS: 외국→KR (E)
    assert directions == ["W", "W", "W", "E"]


def test_build_from_scratch_sn():
    """S/N 방향 모드"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="TEST3",
        service_name="Test",
        port_sequence=["KRPUS", "VNSGN", "KRPUS"],
        direction_pattern="sn",
    )
    directions = {leg.bnd for leg in proforma.legs}
    assert directions == {"S", "N"}


def test_build_from_template():
    """기존 서비스 복제"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_template(
        new_service_code="SIS2_COPY",
        new_service_name="SIS2 Copy",
        template_service_code="SIS2",
    )
    # SIS2와 동일 구조여야 함
    original = mgr.service.get_legs("SIS2")
    assert len(proforma.legs) == len(original)


def test_build_from_template_with_overrides():
    """템플릿 + 항구 교체"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_template(
        new_service_code="SIS2_MOD",
        new_service_name="SIS2 Modified",
        template_service_code="SIS2",
        port_overrides={"INMUN": "INPIP"},
    )
    # INMUN이 INPIP로 바뀌었는지
    all_ports = set()
    for leg in proforma.legs:
        all_ports.add(leg.from_port)
        all_ports.add(leg.to_port)
    assert "INPIP" in all_ports
    assert "INMUN" not in all_ports


def test_proforma_to_legs_dataframe():
    """ServiceLoader 형식 DataFrame 변환"""
    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="TEST_DF",
        service_name="Test",
        port_sequence=["KRPUS", "CNSHA", "VNSGN", "KRPUS"],
    )
    df = proforma.to_legs_dataframe()
    # 필수 컬럼 존재
    required_cols = ["seq", "from_port", "to_port", "bnd",
                     "distance_nm", "speed_knot",
                     "sea_time_min", "tml_min", "tb_manv_min", "td_manv_min"]
    for col in required_cols:
        assert col in df.columns, f"누락된 컬럼: {col}"


def test_proforma_integrates_with_cost_calculator():
    """End-to-end: 신규 프로포마 → 운항원가 계산 정상 동작"""
    import pandas as pd
    from src.cost_calculators import VoyageCostCalculator

    mgr = MasterDataManager()
    builder = ProformaBuilder(mgr)
    proforma = builder.build_from_scratch(
        service_code="E2E_TEST",
        service_name="E2E",
        port_sequence=["KRPUS", "CNSHA", "VNSGN", "KRPUS"],
    )

    # 캐시 주입
    cache = mgr.service.load()
    new_services = pd.concat([
        cache["services"],
        pd.DataFrame([{"service_code": "E2E_TEST", "service_name": "E2E"}])
    ], ignore_index=True).drop_duplicates(subset=["service_code"], keep="last")
    new_legs = pd.concat([
        cache["legs"][cache["legs"]["service_code"] != "E2E_TEST"],
        proforma.to_legs_dataframe()
    ], ignore_index=True)
    mgr.service._cache = {"services": new_services, "legs": new_legs}

    # 운항원가 계산
    calc = VoyageCostCalculator(mgr)
    result = calc.calculate("E2E_TEST", "Jiangsu 4250", 2026, 1, "LSFO")
    assert result.total_fuel_usd > 0
    assert result.total_port_charge_usd > 0
    assert result.total_charter_usd > 0


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
