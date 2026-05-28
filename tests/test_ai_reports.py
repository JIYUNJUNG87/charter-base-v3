"""
AI 리포트 검증 테스트.
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loaders import MasterDataManager
from src.datasources.mock_source import MockDataSource
from src.cost_calculators import VoyageCostIntegrator, VoyageCostCalculator
from src.engine.models import Scenario
from src.engine.calculator import apply_scenario
from src.ai_reports import (
    SimulationReportGenerator, VesselRecommendationGenerator, ReportConfig,
)


def get_simulation_data():
    """공통 시뮬레이션 데이터"""
    mgr = MasterDataManager()
    integrator = VoyageCostIntegrator(mgr)
    src = MockDataSource()
    baseline = src.get_baseline("SIS2", "080", date(2026,5,5), date(2026,5,20))
    enriched, _ = integrator.enrich_baseline(
        baseline, "SIS2", "Jiangsu 4250", 2026, 1, "LSFO", overwrite=True,
    )
    scenario = Scenario(fuel_price_change=0.20)
    result = apply_scenario(enriched, scenario)
    return enriched, result.simulated, scenario


def test_config_no_api_key():
    """API 키 없으면 has_api False"""
    config = ReportConfig(api_key=None)
    # 환경변수 영향 없게 임시 처리
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert config.has_api() == False
    finally:
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_config_with_api_key():
    config = ReportConfig(api_key="test-key")
    assert config.has_api() == True
    assert config.get_api_key() == "test-key"


def test_simulation_report_template_mode():
    """API 키 없이 시뮬레이션 리포트 생성"""
    baseline, simulated, scenario = get_simulation_data()
    gen = SimulationReportGenerator(ReportConfig(api_key=None))
    rep = gen.generate_from_result(
        baseline, simulated, scenario, "SIS2", "Jiangsu 4250",
    )
    assert rep.generated_by == "template"
    assert "## 📋 요약" in rep.content
    assert "## 📊 주요 변화" in rep.content
    assert "## ⚠️ 리스크" in rep.content
    assert "## 💡 의사결정 권고" in rep.content


def test_simulation_report_contains_numbers():
    """리포트에 실제 숫자가 포함되는지"""
    baseline, simulated, scenario = get_simulation_data()
    gen = SimulationReportGenerator(ReportConfig(api_key=None))
    rep = gen.generate_from_result(
        baseline, simulated, scenario, "SIS2", "Jiangsu 4250",
    )
    # 매출 숫자가 포함되어야 함 (517,544)
    assert "517" in rep.content
    # 시나리오 정보 포함
    assert "유가" in rep.content


def test_simulation_report_warnings():
    """API 키 없을 때 경고 포함"""
    baseline, simulated, scenario = get_simulation_data()
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        gen = SimulationReportGenerator(ReportConfig(api_key=None))
        rep = gen.generate_from_result(
            baseline, simulated, scenario, "SIS2", "Jiangsu 4250",
        )
        assert any("API 키 없음" in w for w in rep.warnings)
    finally:
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_vessel_recommendation_template():
    """선형 추천 리포트 템플릿"""
    mgr = MasterDataManager()
    calc = VoyageCostCalculator(mgr)
    types_df = mgr.vessel_spec.find_types_by_teu(4500, 0.15)
    types_df = types_df.dropna(subset=["aux_at_sea", "aux_at_port"])

    vessel_results = []
    for _, row in types_df.head(4).iterrows():
        try:
            cost = calc.calculate("SIS2", row["type_name"], 2026, 1, "LSFO")
            vessel_results.append({
                "type_name": row["type_name"],
                "teu": int(row["teu_nominal"]),
                "fuel": cost.total_fuel_usd,
                "port_charge": cost.total_port_charge_usd,
                "charter": cost.total_charter_usd,
                "total": cost.grand_total_usd,
                "warnings": cost.all_warnings,
            })
        except Exception:
            continue

    assert len(vessel_results) >= 2

    gen = VesselRecommendationGenerator(ReportConfig(api_key=None))
    rep = gen.generate_from_comparison(
        service_code="SIS2",
        voyage_days=42.0,
        total_distance_nm=11266,
        vessel_results=vessel_results,
    )
    assert "## 🎯 추천" in rep.content
    assert "TEU당" in rep.content
    assert "🏆" in rep.content  # 추천 선형 표시


def test_data_masking():
    """민감 데이터 마스킹 동작"""
    config = ReportConfig(mask_sensitive_data=True)
    gen = SimulationReportGenerator(config)

    data = {
        "baseline": {"total_revenue": 1_000_000, "operating_profit": 500_000},
        "simulated": {"total_revenue": 1_100_000},
    }
    masked = gen._mask_data(data)
    # 1,000,000이 1.0(백만 단위)로 변환
    assert masked["baseline"]["total_revenue"] == 1.0
    assert masked["baseline"]["operating_profit"] == 0.5


def test_template_fallback_on_api_error():
    """API 호출 실패 시 템플릿으로 폴백"""
    baseline, simulated, scenario = get_simulation_data()
    # 잘못된 API 키 (실제 호출 실패할 것)
    config = ReportConfig(
        api_key="invalid-key-xxxxxx",
        use_template_fallback=True,
    )
    gen = SimulationReportGenerator(config)
    rep = gen.generate_from_result(
        baseline, simulated, scenario, "SIS2", "Jiangsu 4250",
    )
    # 템플릿으로 폴백되어 정상 생성
    assert rep.generated_by == "template"
    assert "## 📋 요약" in rep.content


def test_scenario_text_generation():
    """시나리오 → 텍스트 변환"""
    gen = SimulationReportGenerator(ReportConfig(api_key=None))

    # 운임 양방향 동일
    text = gen._scenario_to_text({
        "freight_change_e": 0.10, "freight_change_w": 0.10,
        "fuel_price_change": 0, "volume_change_e": 0, "volume_change_w": 0,
    })
    assert "운임 변동: +10%" in text

    # 방향별 다름
    text = gen._scenario_to_text({
        "freight_change_e": 0.05, "freight_change_w": -0.05,
        "fuel_price_change": 0.20, "volume_change_e": 0, "volume_change_w": 0,
    })
    assert "E 운임 변동: +5%" in text
    assert "W 운임 변동: -5%" in text
    assert "유가 변동: +20%" in text


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
