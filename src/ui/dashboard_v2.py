"""
차터베이스 시뮬레이션 대시보드.

회사 차터베이스 화면의 익숙한 레이아웃을 유지하면서,
4가지 핵심 시뮬레이션(운임/유가/선적량/선형)을 빠르게 돌릴 수 있도록 설계.

실행: streamlit run src/ui/dashboard.py
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import DATA_SOURCE
from src.datasources.base import DataSourceFactory
from src.datasources.mock_source import VESSEL_TYPES
from src.engine.models import Scenario
from src.engine.calculator import (
    apply_scenario, sensitivity_analysis, break_even_freight_rate,
)


st.set_page_config(
    page_title="차터베이스 시뮬레이션",
    page_icon="🚢",
    layout="wide",
)


# ============================================================
# 데이터 로딩
# ============================================================
@st.cache_resource
def get_data_source():
    return DataSourceFactory.create(DATA_SOURCE)


# ============================================================
# P&L 표 렌더링 (차터베이스 화면과 동일한 구조)
# ============================================================
def render_pnl_table(baseline, simulated=None):
    """차터베이스 양식의 P&L 표 (E/W/합계 컬럼)"""

    def fmt(v):
        if v == 0:
            return "0"
        return f"{v:,.0f}"

    def fmt_delta(base_v, sim_v):
        delta = sim_v - base_v
        if delta == 0:
            return ""
        return f"({delta:+,.0f})"

    rows = []

    # 선적정보
    rows.append(("선적정보", "자사선복", baseline.east.loading.own_capacity, baseline.west.loading.own_capacity))
    rows.append(("선적정보", "선적량", baseline.east.loading.loaded_teu, baseline.west.loading.loaded_teu))
    rows.append(("선적정보", "COC", baseline.east.loading.coc_teu, baseline.west.loading.coc_teu))
    rows.append(("선적정보", "SOC", baseline.east.loading.soc_teu, baseline.west.loading.soc_teu))
    rows.append(("선적정보", "소석률 (%)", baseline.east.loading.load_factor * 100, baseline.west.loading.load_factor * 100))
    rows.append(("선적정보", "평균운임", baseline.east.rate.avg_rate, baseline.west.rate.avg_rate))

    # 매출
    rows.append(("매출", "운임", baseline.east.revenue.freight, baseline.west.revenue.freight))
    rows.append(("매출", "매출 합계", baseline.east.revenue.total, baseline.west.revenue.total))

    # 화물변동비
    rows.append(("화물변동비", "하역비", baseline.east.cargo_var_cost.handling, baseline.west.cargo_var_cost.handling))
    rows.append(("화물변동비", "대리점수수료", baseline.east.cargo_var_cost.agency_commission, baseline.west.cargo_var_cost.agency_commission))
    rows.append(("화물변동비", "장비이송비", baseline.east.cargo_var_cost.equipment_transport, baseline.west.cargo_var_cost.equipment_transport))
    rows.append(("화물변동비", "장비비", baseline.east.cargo_var_cost.equipment_cost, baseline.west.cargo_var_cost.equipment_cost))
    rows.append(("화물변동비", "화물변동비 합계", baseline.east.cargo_var_cost.total, baseline.west.cargo_var_cost.total))

    # 한계이익
    rows.append(("한계이익", "한계이익", baseline.east.contribution_margin, baseline.west.contribution_margin))

    # 운항변동비
    rows.append(("운항변동비", "항비", baseline.east.voyage_var_cost.port_charge, baseline.west.voyage_var_cost.port_charge))
    rows.append(("운항변동비", "연료비", baseline.east.voyage_var_cost.fuel, baseline.west.voyage_var_cost.fuel))

    # 운항고정비
    rows.append(("운항고정비", "용선료", baseline.east.voyage_fixed_cost.charter_hire, baseline.west.voyage_fixed_cost.charter_hire))
    rows.append(("운항고정비", "선복임차료", baseline.east.voyage_fixed_cost.slot_charter, baseline.west.voyage_fixed_cost.slot_charter))
    rows.append(("운항고정비", "운항고정비 합계", baseline.east.voyage_fixed_cost.total, baseline.west.voyage_fixed_cost.total))

    # 운항이익
    rows.append(("운항이익", "운항이익", baseline.east.voyage_profit, baseline.west.voyage_profit))

    # DataFrame 변환
    if simulated is None:
        df = pd.DataFrame(rows, columns=["분류", "항목", "E", "W"])
        df["합계"] = df["E"] + df["W"]
        return df

    # 시뮬레이션 결과 컬럼 추가
    sim_rows = []
    sim_rows.append((simulated.east.loading.own_capacity, simulated.west.loading.own_capacity))
    sim_rows.append((simulated.east.loading.loaded_teu, simulated.west.loading.loaded_teu))
    sim_rows.append((simulated.east.loading.coc_teu, simulated.west.loading.coc_teu))
    sim_rows.append((simulated.east.loading.soc_teu, simulated.west.loading.soc_teu))
    sim_rows.append((simulated.east.loading.load_factor * 100, simulated.west.loading.load_factor * 100))
    sim_rows.append((simulated.east.rate.avg_rate, simulated.west.rate.avg_rate))
    sim_rows.append((simulated.east.revenue.freight, simulated.west.revenue.freight))
    sim_rows.append((simulated.east.revenue.total, simulated.west.revenue.total))
    sim_rows.append((simulated.east.cargo_var_cost.handling, simulated.west.cargo_var_cost.handling))
    sim_rows.append((simulated.east.cargo_var_cost.agency_commission, simulated.west.cargo_var_cost.agency_commission))
    sim_rows.append((simulated.east.cargo_var_cost.equipment_transport, simulated.west.cargo_var_cost.equipment_transport))
    sim_rows.append((simulated.east.cargo_var_cost.equipment_cost, simulated.west.cargo_var_cost.equipment_cost))
    sim_rows.append((simulated.east.cargo_var_cost.total, simulated.west.cargo_var_cost.total))
    sim_rows.append((simulated.east.contribution_margin, simulated.west.contribution_margin))
    sim_rows.append((simulated.east.voyage_var_cost.port_charge, simulated.west.voyage_var_cost.port_charge))
    sim_rows.append((simulated.east.voyage_var_cost.fuel, simulated.west.voyage_var_cost.fuel))
    sim_rows.append((simulated.east.voyage_fixed_cost.charter_hire, simulated.west.voyage_fixed_cost.charter_hire))
    sim_rows.append((simulated.east.voyage_fixed_cost.slot_charter, simulated.west.voyage_fixed_cost.slot_charter))
    sim_rows.append((simulated.east.voyage_fixed_cost.total, simulated.west.voyage_fixed_cost.total))
    sim_rows.append((simulated.east.voyage_profit, simulated.west.voyage_profit))

    full_rows = []
    for i, (cat, item, base_e, base_w) in enumerate(rows):
        sim_e, sim_w = sim_rows[i]
        full_rows.append({
            "분류": cat,
            "항목": item,
            "E (현재)": base_e,
            "E (시뮬)": sim_e,
            "W (현재)": base_w,
            "W (시뮬)": sim_w,
            "합계 (현재)": base_e + base_w,
            "합계 (시뮬)": sim_e + sim_w,
        })
    return pd.DataFrame(full_rows)


# ============================================================
# 메인 화면
# ============================================================
def main():
    st.title("🚢 차터베이스 시뮬레이션")
    st.caption(f"데이터 소스: `{DATA_SOURCE}` | 운임·유가·선적량·선형 4가지 시뮬레이션")

    source = get_data_source()

    # ===== 사이드바: 항로 선택 + 시나리오 변수 =====
    with st.sidebar:
        st.header("🔍 항로 선택")
        routes = source.get_route_list()
        route_labels = [
            f"{r['service_code']}-{r['route_cb_no']}" for r in routes
        ]
        selected_idx = st.selectbox(
            "항로",
            range(len(routes)),
            format_func=lambda i: route_labels[i],
            index=4,  # SIS2-080 기본 선택
        )
        selected = routes[selected_idx]

        st.divider()
        st.header("📊 시뮬레이션 변수")

        # ===== Case 1: 운임 =====
        with st.expander("1️⃣ 운임 변동", expanded=True):
            freight_mode = st.radio(
                "운임 조정 방식",
                ["양방향 동일", "방향별 따로"],
                key="freight_mode",
                horizontal=True,
            )
            if freight_mode == "양방향 동일":
                fr_both = st.slider("운임 변동률", -30, 30, 0, 1, format="%d%%") / 100
                fr_e, fr_w = fr_both, fr_both
            else:
                fr_e = st.slider("E 운임", -30, 30, 0, 1, format="%d%%") / 100
                fr_w = st.slider("W 운임", -30, 30, 0, 1, format="%d%%") / 100

        # ===== Case 2: 유가 =====
        with st.expander("2️⃣ 유가 변동", expanded=True):
            fuel_pct = st.slider("유가 변동률", -30, 50, 0, 1, format="%d%%") / 100

        # ===== Case 3: 선적량 =====
        with st.expander("3️⃣ 선적량 변동", expanded=True):
            vol_mode = st.radio(
                "선적량 조정 방식",
                ["양방향 동일", "방향별 따로"],
                key="vol_mode",
                horizontal=True,
            )
            if vol_mode == "양방향 동일":
                vol_both = st.slider("선적량 변동률", -30, 30, 0, 1, format="%d%%") / 100
                vol_e, vol_w = vol_both, vol_both
            else:
                vol_e = st.slider("E 선적량", -30, 30, 0, 1, format="%d%%") / 100
                vol_w = st.slider("W 선적량", -30, 30, 0, 1, format="%d%%") / 100

        # ===== Case 4: 선형 =====
        with st.expander("4️⃣ 투입 선형 변경", expanded=False):
            change_vessel = st.checkbox("선형 변경 시뮬레이션")
            new_vessel = None
            if change_vessel:
                vessel_options = list(VESSEL_TYPES.keys())
                selected_vessel = st.selectbox("신규 선형", vessel_options, index=1)
                new_vessel = VESSEL_TYPES[selected_vessel]
                st.caption(
                    f"선복량: {new_vessel.capacity_teu:,.0f} TEU  \n"
                    f"일 연료: {new_vessel.daily_fuel_consumption:.0f} ton  \n"
                    f"일 용선료: ${new_vessel.daily_charter_rate:,.0f}"
                )

    # ===== 시나리오 생성 =====
    scenario = Scenario(
        name="사용자 시나리오",
        freight_change_e=fr_e,
        freight_change_w=fr_w,
        fuel_price_change=fuel_pct,
        volume_change_e=vol_e,
        volume_change_w=vol_w,
        new_vessel=new_vessel,
    )

    # ===== 베이스라인 로딩 + 시뮬레이션 =====
    baseline = source.get_baseline(
        selected["service_code"],
        selected["route_cb_no"],
        date(2026, 5, 5),
        date(2026, 5, 20),
    )
    result = apply_scenario(baseline, scenario)

    # ===== 헤더 KPI =====
    st.subheader(f"📋 {baseline.route_name}")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "매출 합계",
            f"{result.simulated.total_revenue:,.0f}",
            f"{result.simulated.total_revenue - baseline.total_revenue:+,.0f}",
        )
    with col2:
        st.metric(
            "한계이익",
            f"{result.simulated.total_contribution_margin:,.0f}",
            f"{result.contribution_margin_change:+,.0f}",
        )
    with col3:
        st.metric(
            "운항이익",
            f"{result.simulated.total_voyage_profit:,.0f}",
            f"{result.voyage_profit_change:+,.0f}",
        )
    with col4:
        e_lf = result.simulated.east.loading.load_factor
        w_lf = result.simulated.west.loading.load_factor
        st.metric(
            "소석률 (E / W)",
            f"{e_lf:.1%} / {w_lf:.1%}",
        )

    st.divider()

    # ===== 탭 구성 (차터베이스 화면과 유사) =====
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 시뮬레이션 결과", "🌪️ 민감도 분석", "🎯 BEP 분석", "📍 포트별 데이터"
    ])

    with tab1:
        st.subheader("P&L 비교 (현재 vs 시뮬레이션)")
        df = render_pnl_table(baseline, result.simulated)

        # 한계이익/운항이익 행 강조
        def highlight_key_rows(row):
            if row["항목"] in ["한계이익", "운항이익"]:
                return ["background-color: #fef3c7"] * len(row)
            if row["항목"] in ["매출 합계", "화물변동비 합계", "운항고정비 합계"]:
                return ["background-color: #f3f4f6"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df.style.format({
                "E (현재)": "{:,.0f}",
                "E (시뮬)": "{:,.0f}",
                "W (현재)": "{:,.0f}",
                "W (시뮬)": "{:,.0f}",
                "합계 (현재)": "{:,.0f}",
                "합계 (시뮬)": "{:,.0f}",
            }).apply(highlight_key_rows, axis=1),
            use_container_width=True,
            hide_index=True,
            height=750,
        )

    with tab2:
        st.subheader("민감도 분석: 각 변수 +10% 시 운항이익 변화")
        sens = sensitivity_analysis(baseline, delta=0.10)
        sens_df = pd.DataFrame({
            "변수": list(sens.keys()),
            "운항이익 변화": list(sens.values()),
        }).sort_values("운항이익 변화", key=abs, ascending=True)

        fig = go.Figure(go.Bar(
            x=sens_df["운항이익 변화"],
            y=sens_df["변수"],
            orientation="h",
            marker_color=["#ef4444" if v < 0 else "#22c55e"
                          for v in sens_df["운항이익 변화"]],
            text=[f"{v:+,.0f}" for v in sens_df["운항이익 변화"]],
            textposition="outside",
        ))
        fig.update_layout(
            xaxis_title="운항이익 변화 (천 USD)",
            height=400,
            margin=dict(l=0, r=40, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.caption(
            "💡 막대가 가장 긴 변수가 수지에 가장 큰 영향을 주는 요인입니다."
        )

    with tab3:
        st.subheader("BEP(손익분기점) 분석")
        bep = break_even_freight_rate(baseline)
        col_e, col_w = st.columns(2)
        with col_e:
            if bep["east"] is not None:
                st.metric(
                    "E 방향 BEP 운임 변동",
                    f"{bep['east']:+.1%}",
                    help="현재 운항이익이 0이 되려면 E 운임이 이만큼 변해야 함",
                )
            else:
                st.info("E 방향: 운임 데이터 없음")
        with col_w:
            if bep["west"] is not None:
                st.metric(
                    "W 방향 BEP 운임 변동",
                    f"{bep['west']:+.1%}",
                )
            else:
                st.info("W 방향: 운임 데이터 없음")

        st.caption(
            "💡 BEP가 음수면 현재 운임이 BEP 대비 높다(흑자), "
            "양수면 운임이 그만큼 올라야 흑자 전환된다는 의미입니다."
        )

    with tab4:
        st.subheader("포트 페어별 선적량")
        port_df = pd.DataFrame([
            {
                "방향": p.direction,
                "출발항": p.origin_port,
                "도착항": p.destination_port,
                "선적량 (TEU)": p.loaded_teu,
            }
            for p in baseline.port_pairs
        ])
        col_e, col_w = st.columns(2)
        with col_e:
            st.markdown("**East 방향**")
            st.dataframe(
                port_df[port_df["방향"] == "E"].drop(columns=["방향"]),
                hide_index=True, use_container_width=True,
            )
        with col_w:
            st.markdown("**West 방향**")
            st.dataframe(
                port_df[port_df["방향"] == "W"].drop(columns=["방향"]),
                hide_index=True, use_container_width=True,
            )


if __name__ == "__main__":
    main()
