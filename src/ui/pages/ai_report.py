"""
AI 리포트 페이지 (Streamlit multipage).

실행: streamlit run src/ui/dashboard.py → 사이드바에서 페이지 선택
"""

import sys
import os
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

from src.data_loaders import MasterDataManager
from src.datasources.mock_source import MockDataSource
from src.cost_calculators import VoyageCostCalculator, VoyageCostIntegrator
from src.engine.models import Scenario
from src.engine.calculator import apply_scenario
from src.ai_reports import (
    SimulationReportGenerator, VesselRecommendationGenerator,
    ReportConfig,
)


st.set_page_config(
    page_title="AI 리포트",
    page_icon="🤖",
    layout="wide",
)


from src.ui.shared import get_data_manager


def main():
    st.title("🤖 AI 리포트")
    st.caption("시뮬레이션 결과를 임원 보고용 자연어 분석으로 변환")

    mgr = get_data_manager()
    src = MockDataSource()

    # ============================================================
    # API 키 설정 (사이드바)
    # ============================================================
    with st.sidebar:
        st.header("⚙️ AI 설정")

        # 환경변수에 키가 있으면 자동 사용
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        has_env_key = bool(env_key)

        if has_env_key:
            st.success("✅ 환경변수에서 API 키 감지")
            use_api = st.checkbox("Claude API 사용", value=True)
            api_key = env_key if use_api else None
        else:
            st.caption("API 키 없으면 템플릿 리포트 생성됩니다.")
            api_key_input = st.text_input(
                "Anthropic API Key (선택)",
                type="password",
                help="입력 시 더 풍부한 분석. 비워두면 템플릿 사용.",
            )
            api_key = api_key_input.strip() if api_key_input else None

        st.divider()
        st.subheader("🔒 보안 옵션")
        mask_data = st.checkbox(
            "민감 데이터 마스킹",
            value=False,
            help="금액을 백만 USD 단위로 변환해서 전송",
        )

        if api_key:
            st.info(
                "💡 Anthropic 정책상 API 데이터는 학습에 사용되지 않습니다. "
                "필요시 마스킹 옵션을 활성화하세요."
            )

    config = ReportConfig(
        api_key=api_key,
        mask_sensitive_data=mask_data,
    )

    # ============================================================
    # 리포트 유형 선택
    # ============================================================
    report_type = st.radio(
        "리포트 유형",
        ["📊 시뮬레이션 결과 분석", "🚢 선형 추천 분석"],
        horizontal=True,
    )

    st.divider()

    # ============================================================
    # 공통: 항로/선형 선택
    # ============================================================
    services = mgr.service.get_services()["service_code"].tolist()
    baseline_routes = src.get_route_list()
    common = [r for r in baseline_routes if r["service_code"] in services]
    if not common:
        common = baseline_routes

    c1, c2, c3 = st.columns(3)
    with c1:
        route_idx = st.selectbox(
            "항로",
            range(len(common)),
            format_func=lambda i: f"{common[i]['service_code']}-{common[i]['route_cb_no']}",
        )
        service_code = common[route_idx]["service_code"]
        route_cb_no = common[route_idx]["route_cb_no"]

    types_df = mgr.vessel_spec.get_types().dropna(subset=["teu_nominal"])
    with c2:
        v_idx = st.selectbox(
            "선형",
            range(len(types_df)),
            format_func=lambda i: f"{types_df.iloc[i]['type_name']} ({int(types_df.iloc[i]['teu_nominal'])}TEU)",
        )
        vessel_type = types_df.iloc[v_idx]["type_name"]

    with c3:
        year = st.number_input("연도", 2024, 2027, 2026)
        month = st.number_input("월", 1, 12, 1)

    # 벙커링 / 유종 옵션 (한 줄로)
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        bunker_port = st.selectbox(
            "벙커링 항구",
            ["KOR", "HKG", "SIN", "SHA", "FJR", "RUS"],
            key="ai_bunker",
        )
    with bc2:
        fuel_type = st.selectbox(
            "항해 유종", ["LSFO", "380CST"],
            key="ai_sea_fuel",
        )
    with bc3:
        port_fuel_type = st.selectbox(
            "정박 유종", ["LSFO", "380CST", "LSMGO", "MGO"],
            key="ai_port_fuel",
        )

    # ============================================================
    # 시뮬레이션 결과 분석 리포트
    # ============================================================
    if "시뮬레이션 결과 분석" in report_type:
        st.subheader("시나리오 설정")
        c1, c2, c3 = st.columns(3)
        with c1:
            fr_pct = st.slider("운임 변동 (양방향)", -30, 30, 0, 1, format="%d%%") / 100
        with c2:
            fuel_pct = st.slider("유가 변동", -30, 50, 20, 1, format="%d%%") / 100
        with c3:
            vol_pct = st.slider("선적량 변동 (양방향)", -30, 30, 0, 1, format="%d%%") / 100

        if st.button("🚀 리포트 생성", type="primary"):
            with st.spinner("리포트 생성 중..."):
                # 베이스라인 + 운항원가 통합
                baseline = src.get_baseline(
                    service_code, route_cb_no,
                    date(year, month, 1), date(year, month, 28),
                )
                if service_code in services:
                    integrator = VoyageCostIntegrator(mgr)
                    has_sn = any(b in ("S", "N")
                                for b in mgr.service.get_legs(service_code)["bnd"].dropna().unique())
                    sn_mapping = {"S": "W", "N": "E"} if has_sn else None
                    baseline, _ = integrator.enrich_baseline(
                        baseline, service_code, vessel_type, year, month, fuel_type,
                        overwrite=True, sn_mapping=sn_mapping,
                    )

                # 시뮬레이션
                scenario = Scenario(
                    freight_change_e=fr_pct, freight_change_w=fr_pct,
                    fuel_price_change=fuel_pct,
                    volume_change_e=vol_pct, volume_change_w=vol_pct,
                )
                result = apply_scenario(baseline, scenario)

                # 리포트 생성
                gen = SimulationReportGenerator(config)
                rep = gen.generate_from_result(
                    baseline, result.simulated, scenario,
                    service_code, vessel_type,
                )

                # 표시
                badge = "🤖 Claude API" if rep.generated_by == "claude" else "📋 템플릿"
                st.caption(f"생성: {badge}")
                if rep.warnings:
                    for w in rep.warnings:
                        st.info(w)

                st.markdown(rep.content)

                # 다운로드
                st.download_button(
                    "📥 마크다운 다운로드",
                    rep.content,
                    file_name=f"report_{service_code}_{vessel_type}_{year}{month:02d}.md",
                    mime="text/markdown",
                )

    # ============================================================
    # 선형 추천 분석 리포트
    # ============================================================
    else:
        st.subheader("선형 후보 범위")
        c1, c2 = st.columns(2)
        with c1:
            target_teu = st.number_input(
                "기준 TEU", 1000, 20000,
                int(types_df.iloc[v_idx]["teu_nominal"]),
                step=500,
            )
        with c2:
            tolerance = st.slider("±허용 범위 (%)", 5, 50, 15, 5) / 100

        candidates = mgr.vessel_spec.find_types_by_teu(target_teu, tolerance)
        candidates = candidates.dropna(subset=["aux_at_sea", "aux_at_port"])
        st.caption(f"후보 선형: {len(candidates)}개")

        if not candidates.empty:
            with st.expander("후보 미리보기"):
                st.dataframe(
                    candidates[["type_name", "teu_nominal", "loa", "design_dwt"]],
                    hide_index=True, use_container_width=True,
                )

        if st.button("🚀 선형 추천 리포트 생성", type="primary",
                     disabled=candidates.empty):
            if service_code not in services:
                st.error("이 서비스의 프로포마 데이터가 없어 분석 불가합니다.")
            else:
                with st.spinner(f"{len(candidates)}개 선형 비교 중..."):
                    calc = VoyageCostCalculator(mgr)
                    vessel_results = []
                    for _, row in candidates.iterrows():
                        try:
                            cost = calc.calculate(
                                service_code, row["type_name"],
                                year, month, fuel_type,
                                bunker_port=bunker_port,
                                port_fuel_type=port_fuel_type if port_fuel_type != fuel_type else None,
                            )
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

                    summary = mgr.service.get_service_summary(service_code)
                    gen = VesselRecommendationGenerator(config)
                    rep = gen.generate_from_comparison(
                        service_code=service_code,
                        voyage_days=summary["total_time_hours"]/24,
                        total_distance_nm=summary["total_distance_nm"],
                        vessel_results=vessel_results,
                    )

                    badge = "🤖 Claude API" if rep.generated_by == "claude" else "📋 템플릿"
                    st.caption(f"생성: {badge}")
                    if rep.warnings:
                        for w in rep.warnings:
                            st.info(w)

                    st.markdown(rep.content)

                    st.download_button(
                        "📥 마크다운 다운로드",
                        rep.content,
                        file_name=f"vessel_recommendation_{service_code}_{year}{month:02d}.md",
                        mime="text/markdown",
                    )


if __name__ == "__main__":
    main()
