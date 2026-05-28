"""
차터베이스 시뮬레이션 대시보드 (v3).

기능:
1. 차터베이스 양식 P&L 표시 (E/W/합계)
2. 실데이터 운항원가 자동 통합 (연료비/항비/용선료)
3. 4가지 시뮬레이션 케이스 (운임/유가/선적량/선형)
4. 민감도 분석 (Tornado chart)
5. 선형 비교 (여러 선형 한꺼번에)
6. 데이터 경고 사항 투명하게 표시

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
import plotly.express as px

from config import DATA_SOURCE
from src.datasources.base import DataSourceFactory
from src.data_loaders import MasterDataManager
from src.cost_calculators import VoyageCostIntegrator, VoyageCostCalculator
from src.engine.models import Scenario
from src.engine.service_context import ServiceContext, DAYS_PER_VESSEL
from src.engine.calculator import (
    apply_scenario, sensitivity_analysis, break_even_freight_rate,
)


st.set_page_config(
    page_title="차터베이스 시뮬레이션",
    page_icon="🚢",
    layout="wide",
)


from src.ui.shared import (
    get_data_manager, get_baseline_source, get_integrator,
)


def fmt_money(v: float, sign: bool = False) -> str:
    if v == 0:
        return "-"
    if sign and v > 0:
        return f"+${v:,.0f}"
    if v < 0:
        return f"-${abs(v):,.0f}"
    return f"${v:,.0f}"


def detect_sn_mapping(service_code: str, mgr) -> tuple[bool, dict | None]:
    legs = mgr.service.get_legs(service_code)
    if legs.empty:
        return False, None
    bnds = legs["bnd"].dropna().unique()
    has_sn = any(b in ("S", "N") for b in bnds)
    if has_sn:
        return True, {"S": "W", "N": "E"}
    return False, None


def render_pnl_table(baseline, simulated=None):
    rows = []

    def add(category, item, base_e, base_w, sim_e=None, sim_w=None, is_kpi=False):
        rows.append({
            "분류": category,
            "항목": item,
            "E": base_e,
            "W": base_w,
            "합계": base_e + base_w,
            "E_sim": sim_e if sim_e is not None else base_e,
            "W_sim": sim_w if sim_w is not None else base_w,
            "is_kpi": is_kpi,
        })

    b = baseline
    s = simulated if simulated else baseline

    add("선적정보", "자사선복", b.east.loading.own_capacity, b.west.loading.own_capacity,
        s.east.loading.own_capacity, s.west.loading.own_capacity)
    add("선적정보", "선적량", b.east.loading.loaded_teu, b.west.loading.loaded_teu,
        s.east.loading.loaded_teu, s.west.loading.loaded_teu)
    add("선적정보", "소석률 (%)", b.east.loading.load_factor * 100, b.west.loading.load_factor * 100,
        s.east.loading.load_factor * 100, s.west.loading.load_factor * 100)
    add("선적정보", "평균운임", b.east.rate.avg_rate, b.west.rate.avg_rate,
        s.east.rate.avg_rate, s.west.rate.avg_rate)
    add("매출", "운임", b.east.revenue.freight, b.west.revenue.freight,
        s.east.revenue.freight, s.west.revenue.freight)
    add("매출", "매출 합계", b.east.revenue.total, b.west.revenue.total,
        s.east.revenue.total, s.west.revenue.total, is_kpi=True)
    add("화물변동비", "하역비", b.east.cargo_var_cost.handling, b.west.cargo_var_cost.handling,
        s.east.cargo_var_cost.handling, s.west.cargo_var_cost.handling)
    add("화물변동비", "대리점수수료", b.east.cargo_var_cost.agency_commission, b.west.cargo_var_cost.agency_commission,
        s.east.cargo_var_cost.agency_commission, s.west.cargo_var_cost.agency_commission)
    add("화물변동비", "장비이송비", b.east.cargo_var_cost.equipment_transport, b.west.cargo_var_cost.equipment_transport,
        s.east.cargo_var_cost.equipment_transport, s.west.cargo_var_cost.equipment_transport)
    add("화물변동비", "장비비", b.east.cargo_var_cost.equipment_cost, b.west.cargo_var_cost.equipment_cost,
        s.east.cargo_var_cost.equipment_cost, s.west.cargo_var_cost.equipment_cost)
    add("화물변동비", "화물변동비 합계", b.east.cargo_var_cost.total, b.west.cargo_var_cost.total,
        s.east.cargo_var_cost.total, s.west.cargo_var_cost.total)
    add("한계이익", "한계이익", b.east.contribution_margin, b.west.contribution_margin,
        s.east.contribution_margin, s.west.contribution_margin, is_kpi=True)
    add("운항변동비", "연료비", b.east.voyage_var_cost.fuel, b.west.voyage_var_cost.fuel,
        s.east.voyage_var_cost.fuel, s.west.voyage_var_cost.fuel)
    add("운항변동비", "항비", b.east.voyage_var_cost.port_charge, b.west.voyage_var_cost.port_charge,
        s.east.voyage_var_cost.port_charge, s.west.voyage_var_cost.port_charge)
    add("운항고정비", "용선료", b.east.voyage_fixed_cost.charter_hire, b.west.voyage_fixed_cost.charter_hire,
        s.east.voyage_fixed_cost.charter_hire, s.west.voyage_fixed_cost.charter_hire)
    add("운항고정비", "선복임차료", b.east.voyage_fixed_cost.slot_charter, b.west.voyage_fixed_cost.slot_charter,
        s.east.voyage_fixed_cost.slot_charter, s.west.voyage_fixed_cost.slot_charter)
    add("운항이익", "운항이익", b.east.voyage_profit, b.west.voyage_profit,
        s.east.voyage_profit, s.west.voyage_profit, is_kpi=True)

    return pd.DataFrame(rows)


def style_pnl_dataframe(df: pd.DataFrame, show_simulation: bool = False):
    if show_simulation:
        df_display = df.copy()
        df_display["합계_sim"] = df_display["E_sim"] + df_display["W_sim"]
        display_cols = ["분류", "항목", "E", "E_sim", "W", "W_sim", "합계", "합계_sim"]
        df_display = df_display[display_cols].rename(columns={
            "E": "E (현재)", "E_sim": "E (시뮬)",
            "W": "W (현재)", "W_sim": "W (시뮬)",
            "합계": "합계 (현재)", "합계_sim": "합계 (시뮬)",
        })
        format_dict = {
            "E (현재)": "{:,.0f}", "E (시뮬)": "{:,.0f}",
            "W (현재)": "{:,.0f}", "W (시뮬)": "{:,.0f}",
            "합계 (현재)": "{:,.0f}", "합계 (시뮬)": "{:,.0f}",
        }
    else:
        df_display = df[["분류", "항목", "E", "W", "합계"]].copy()
        format_dict = {"E": "{:,.0f}", "W": "{:,.0f}", "합계": "{:,.0f}"}

    is_kpi = df["is_kpi"].tolist()

    def highlight_kpi(row):
        idx = row.name
        if is_kpi[idx]:
            return ["background-color: #fef3c7; font-weight: bold"] * len(row)
        item = row.get("항목", "")
        if "합계" in str(item):
            return ["background-color: #f3f4f6"] * len(row)
        return [""] * len(row)

    return df_display.style.format(format_dict).apply(highlight_kpi, axis=1)


def main():
    st.title("🚢 차터베이스 시뮬레이션")
    st.caption(f"실데이터 기반 운항원가 통합 | 데이터 소스: `{DATA_SOURCE}`")

    mgr = get_data_manager()
    src = get_baseline_source()
    integrator = get_integrator()

    # ========================================================
    # 마법사에서 자동 셋업 정보 받기 (한 번만)
    # ========================================================
    autoload = st.session_state.get("dashboard_autoload")
    if autoload:
        # 프로포마 캐시 주입 (마법사에서 만든 임시 서비스)
        try:
            new_legs_df = autoload.get("proforma_legs_df")
            if new_legs_df is not None and not new_legs_df.empty:
                cache = mgr.service.load()
                new_services = pd.concat([
                    cache["services"],
                    pd.DataFrame([{
                        "service_code": autoload["service_code"],
                        "service_name": autoload["service_name"],
                    }])
                ], ignore_index=True).drop_duplicates(subset=["service_code"], keep="last")
                new_legs = pd.concat([
                    cache["legs"][cache["legs"]["service_code"] != autoload["service_code"]],
                    new_legs_df
                ], ignore_index=True)
                mgr.service._cache = {"services": new_services, "legs": new_legs}
        except Exception as e:
            st.warning(f"마법사 프로포마 주입 실패: {e}")

        st.success(
            f"✨ 마법사에서 가져온 항로 자동 적용됨: "
            f"**{autoload['service_code']}** × **{autoload['vessel_type']}** "
            f"({autoload['own_vessels']}/{autoload['total_vessels']}척, "
            f"BSA {autoload['bsa_teu']:,.0f}TEU)"
        )

    # 사이드바
    with st.sidebar:
        st.header("🔍 항로 / 선형")

        baseline_routes = src.get_route_list()
        service_codes = mgr.service.get_services()["service_code"].tolist()
        common_services = [r for r in baseline_routes
                          if r["service_code"] in service_codes]
        if not common_services:
            common_services = baseline_routes

        route_labels = [f"{r['service_code']}-{r['route_cb_no']}"
                       for r in common_services]
        # 마법사 autoload 시 마법사가 만든 서비스 코드를 우선
        if autoload:
            default_idx = next(
                (i for i, r in enumerate(common_services)
                 if r["service_code"] == autoload["service_code"]),
                next((i for i, r in enumerate(common_services)
                      if r["service_code"] == "SIS2"), 0)
            )
            # 마법사 서비스가 baseline_routes에 없으면 강제 추가
            if not any(r["service_code"] == autoload["service_code"]
                       for r in common_services):
                common_services = [{
                    "service_code": autoload["service_code"],
                    "route_cb_no": "WIZARD",
                }] + common_services
                route_labels = [
                    f"{autoload['service_code']}-WIZARD (마법사)"
                ] + route_labels
                default_idx = 0
        else:
            default_idx = next(
                (i for i, r in enumerate(common_services)
                 if r["service_code"] == "SIS2"), 0
            )
        selected_idx = st.selectbox(
            "항로 (서비스)", range(len(common_services)),
            format_func=lambda i: route_labels[i],
            index=default_idx,
            key="dash_route_idx",
        )
        selected_route = common_services[selected_idx]
        service_code = selected_route["service_code"]

        in_service_list = service_code in service_codes
        if in_service_list:
            summary = mgr.service.get_service_summary(service_code)
            st.caption(
                f"📍 프로포마: {summary['leg_count']}구간 · "
                f"{summary['total_distance_nm']:,.0f}NM · "
                f"{summary['total_time_hours']/24:.1f}일"
            )
        else:
            st.warning(f"⚠️ '{service_code}'의 프로포마 데이터가 없어 운항원가 자동 계산 불가")

        st.divider()
        types_df = mgr.vessel_spec.get_types()
        valid_types = types_df.dropna(subset=["teu_nominal"]).copy()
        def _make_vessel_label(r):
            warn = "" if (pd.notna(r["aux_at_sea"]) and pd.notna(r["aux_at_port"])) else "⚠️ "
            return f"{warn}{r['type_name']} ({int(r['teu_nominal'])}TEU)"
        valid_types["label"] = valid_types.apply(_make_vessel_label, axis=1)

        if autoload:
            default_vessel_idx = next(
                (i for i, n in enumerate(valid_types["type_name"])
                 if n == autoload["vessel_type"]),
                next((i for i, n in enumerate(valid_types["type_name"])
                      if n == "Jiangsu 4250"), 0)
            )
        else:
            default_vessel_idx = next(
                (i for i, n in enumerate(valid_types["type_name"])
                 if n == "Jiangsu 4250"), 0
            )
        vessel_idx = st.selectbox(
            "선형", range(len(valid_types)),
            format_func=lambda i: valid_types.iloc[i]["label"],
            index=default_vessel_idx,
            key="dash_vessel_idx",
        )
        vessel_type = valid_types.iloc[vessel_idx]["type_name"]
        vessel_teu = int(valid_types.iloc[vessel_idx]["teu_nominal"])
        vessel_capacity_14t = float(valid_types.iloc[vessel_idx]["teu_at_14t"]) \
            if pd.notna(valid_types.iloc[vessel_idx]["teu_at_14t"]) else float(vessel_teu)

        # 서비스 구조 (공동운항/BSA)
        st.divider()
        st.subheader("🚢 서비스 구조 (BSA)")
        col_total, col_own = st.columns(2)
        with col_total:
            total_vessels = st.number_input(
                "총 척수", 1, 20,
                value=autoload["total_vessels"] if autoload else 6,
                help="공동운항 합산",
                key="dash_total_vessels",
            )
        with col_own:
            own_vessels = st.number_input(
                "자사 척수", 0, total_vessels,
                value=min(autoload["own_vessels"], total_vessels) if autoload else 1,
                key="dash_own_vessels",
            )

        auto_bsa = vessel_capacity_14t * (own_vessels / total_vessels) if total_vessels > 0 else 0
        use_manual_bsa = st.checkbox(
            "BSA 수기 조정",
            help=f"자동: {auto_bsa:,.0f} TEU",
            key="dash_manual_bsa",
        )
        if use_manual_bsa:
            bsa_teu = st.number_input(
                "BSA (TEU)", min_value=0.0,
                value=float(autoload["bsa_teu"]) if autoload else float(round(auto_bsa)),
                step=10.0,
                key="dash_bsa",
            )
        else:
            bsa_teu = auto_bsa

        # 운영 형태 표시
        if own_vessels == 0:
            op_type = "charter_only"
            st.caption("🔵 순수 임차 (Slot Charter)")
        elif own_vessels == total_vessels:
            op_type = "owned"
            st.caption("🟢 자사 단독 운항")
        else:
            op_type = "shared"
            st.caption(f"🟡 공동운항 (BSA {bsa_teu:,.0f}TEU)")

        # 7일 배수 안내
        expected_days = total_vessels * DAYS_PER_VESSEL
        st.caption(f"⏱ 이론 항차일수: {expected_days}일 ({total_vessels}척 × 7일)")

        st.divider()
        st.subheader("📅 기준 시점")
        col_y, col_m = st.columns(2)
        with col_y:
            year = st.number_input(
                "연도", 2024, 2027,
                value=autoload["year"] if autoload else 2026,
                key="dash_year",
            )
        with col_m:
            month = st.number_input(
                "월", 1, 12,
                value=autoload["month"] if autoload else 1,
                key="dash_month",
            )

        bunker_ports = ["KOR", "HKG", "SIN", "SHA", "FJR", "RUS"]
        default_bunker_idx = (
            bunker_ports.index(autoload["bunker_port"])
            if autoload and autoload.get("bunker_port") in bunker_ports
            else 0
        )
        bunker_port = st.selectbox(
            "벙커링 항구",
            bunker_ports,
            index=default_bunker_idx,
            format_func=lambda p: {
                "KOR": "한국 (KOR)", "HKG": "홍콩 (HKG)",
                "SIN": "싱가포르 (SIN)", "SHA": "상하이 (SHA)",
                "FJR": "후자이라 (FJR)", "RUS": "러시아 (RUS)",
            }.get(p, p),
            help="실제 벙커링 항구. 모든 leg에 동일 단가 적용",
            key="dash_bunker_port",
        )

        col_sf, col_pf = st.columns(2)
        sea_fuels = ["LSFO", "380CST"]
        port_fuels = ["LSFO", "380CST", "LSMGO", "MGO"]
        default_sf = sea_fuels.index(autoload["fuel_type"]) if (
            autoload and autoload.get("fuel_type") in sea_fuels
        ) else 0
        default_pf = port_fuels.index(autoload["port_fuel_type"]) if (
            autoload and autoload.get("port_fuel_type") in port_fuels
        ) else 0
        with col_sf:
            fuel_type = st.selectbox(
                "항해/Manv 유종",
                sea_fuels,
                index=default_sf,
                help="메인엔진 (FO 계열만)",
                key="dash_sea_fuel",
            )
        with col_pf:
            port_fuel_type = st.selectbox(
                "정박/Buffer 유종",
                port_fuels,
                index=default_pf,
                help="보조엔진 (FO/GO 모두 가능)",
                key="dash_port_fuel",
            )

        # autoload 1회 적용 후 클리어 (재진입 시 사용자 변경값 보존)
        if autoload:
            del st.session_state["dashboard_autoload"]

        sn_mapping = None
        if in_service_list:
            has_sn, _ = detect_sn_mapping(service_code, mgr)
            if has_sn:
                st.divider()
                st.subheader("⚙️ S/N → E/W 매핑")
                st.caption(f"'{service_code}'는 S/N으로 표기. 매핑을 지정하세요.")
                s_dir = st.radio("S(남행) →", ["W", "E"], index=0, key="s_dir", horizontal=True)
                n_dir = st.radio("N(북행) →", ["E", "W"], index=0, key="n_dir", horizontal=True)
                sn_mapping = {"S": s_dir, "N": n_dir}

        st.divider()
        st.header("📊 시뮬레이션 변수")

        with st.expander("1️⃣ 운임 변동", expanded=True):
            fr_e = st.slider("E 운임", -30, 30, 0, 1, format="%d%%", key="fr_e") / 100
            fr_w = st.slider("W 운임", -30, 30, 0, 1, format="%d%%", key="fr_w") / 100

        with st.expander("2️⃣ 유가 변동", expanded=True):
            fuel_pct = st.slider("유가 변동률", -30, 50, 0, 1, format="%d%%") / 100

        with st.expander("3️⃣ 선적량 변동", expanded=True):
            vol_e = st.slider("E 선적량", -30, 30, 0, 1, format="%d%%", key="vol_e") / 100
            vol_w = st.slider("W 선적량", -30, 30, 0, 1, format="%d%%", key="vol_w") / 100

        with st.expander("4️⃣ 투입 선형 변경", expanded=False):
            change_vessel = st.checkbox("선형 변경 시뮬레이션")
            new_vessel_type = None
            if change_vessel:
                new_vessel_idx = st.selectbox(
                    "신규 선형", range(len(valid_types)),
                    format_func=lambda i: valid_types.iloc[i]["label"],
                    index=default_vessel_idx, key="new_vessel",
                )
                new_vessel_type = valid_types.iloc[new_vessel_idx]["type_name"]

    # 메인 처리
    baseline = src.get_baseline(
        service_code, selected_route["route_cb_no"],
        date(year, month, 1), date(year, month, 28),
    )

    integration_warnings = []
    alloc = None
    ctx_result = None
    if in_service_list:
        try:
            # ServiceContext 구성
            ctx = ServiceContext(
                service_code=service_code,
                operation_type=op_type,
                total_vessels_in_service=total_vessels,
                vessel_capacity_teu_14t=vessel_capacity_14t,
                own_vessels_deployed=own_vessels,
                own_bsa_teu=bsa_teu,
            )
            baseline, ctx_result = integrator.enrich_baseline_with_context(
                baseline, ctx, vessel_type,
                year, month, fuel_type, overwrite=True,
                sn_mapping=sn_mapping,
                bunker_port=bunker_port,
                port_fuel_type=port_fuel_type if port_fuel_type != fuel_type else None,
            )
            integration_warnings = ctx_result.warnings
            alloc = ctx_result.full_alloc  # 운항원가 분석 탭 호환
        except Exception as e:
            st.error(f"운항원가 통합 실패: {e}")

    scenario = Scenario(
        freight_change_e=fr_e, freight_change_w=fr_w,
        fuel_price_change=fuel_pct,
        volume_change_e=vol_e, volume_change_w=vol_w,
    )
    result = apply_scenario(baseline, scenario)

    vessel_change_result = None
    if change_vessel and new_vessel_type and in_service_list:
        try:
            new_baseline, new_alloc = integrator.simulate_vessel_change(
                baseline, service_code, new_vessel_type,
                year, month, fuel_type, sn_mapping=sn_mapping,
            )
            vessel_change_result = {
                "new_baseline": new_baseline,
                "new_vessel_type": new_vessel_type,
            }
        except Exception as e:
            st.error(f"선형 변경 시뮬레이션 실패: {e}")

    # KPI
    st.subheader(f"📋 {service_code}-{selected_route['route_cb_no']} | 🚢 {vessel_type} ({vessel_teu}TEU)")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("매출 합계", f"${result.simulated.total_revenue:,.0f}",
                  fmt_money(result.simulated.total_revenue - baseline.total_revenue, sign=True))
    with col2:
        st.metric("한계이익", f"${result.simulated.total_contribution_margin:,.0f}",
                  fmt_money(result.contribution_margin_change, sign=True))
    with col3:
        delta = result.voyage_profit_change
        st.metric("운항이익", f"${result.simulated.total_voyage_profit:,.0f}",
                  fmt_money(delta, sign=True),
                  delta_color="normal" if delta >= 0 else "inverse")
    with col4:
        e_lf = result.simulated.east.loading.load_factor
        w_lf = result.simulated.west.loading.load_factor
        st.metric("소석률 (E / W)", f"{e_lf:.1%} / {w_lf:.1%}")

    st.divider()

    tabs = st.tabs([
        "📊 차터베이스 P&L", "💰 운항원가 분석", "🌪️ 민감도 분석",
        "🚢 선형 비교", "⚠️ 데이터 경고",
    ])

    with tabs[0]:
        show_sim = any([fr_e, fr_w, fuel_pct, vol_e, vol_w])
        if show_sim:
            st.caption("시나리오 적용된 결과를 '시뮬' 컬럼에서 확인하세요.")
        df = render_pnl_table(baseline, result.simulated)
        st.dataframe(
            style_pnl_dataframe(df, show_simulation=show_sim),
            use_container_width=True, hide_index=True, height=700,
        )

    with tabs[1]:
        if alloc is None:
            st.warning("운항원가 통합이 안 됐습니다.")
        else:
            col_l, col_r = st.columns(2)
            with col_l:
                cost_data = pd.DataFrame({
                    "항목": ["연료비", "항비", "용선료"],
                    "금액": [alloc.total_fuel, alloc.total_port_charge, alloc.total_charter],
                })
                fig = px.pie(cost_data, values="금액", names="항목",
                             title="운항원가 구성", hole=0.4,
                             color_discrete_sequence=["#ef4444", "#f59e0b", "#3b82f6"])
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

            with col_r:
                ew_data = pd.DataFrame({
                    "항목": ["연료비"] * 2 + ["항비"] * 2 + ["용선료"] * 2,
                    "방향": ["E", "W"] * 3,
                    "금액": [alloc.east_fuel, alloc.west_fuel,
                            alloc.east_port_charge, alloc.west_port_charge,
                            alloc.east_charter, alloc.west_charter],
                })
                fig2 = px.bar(ew_data, x="항목", y="금액", color="방향",
                              title="E/W 방향별 분배", barmode="group",
                              color_discrete_map={"E": "#22c55e", "W": "#3b82f6"})
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, use_container_width=True)

            detail_df = pd.DataFrame([
                {"항목": "연료비", "East": alloc.east_fuel,
                 "West": alloc.west_fuel, "합계": alloc.total_fuel},
                {"항목": "항비", "East": alloc.east_port_charge,
                 "West": alloc.west_port_charge, "합계": alloc.total_port_charge},
                {"항목": "용선료", "East": alloc.east_charter,
                 "West": alloc.west_charter, "합계": alloc.total_charter},
            ])
            total_row = pd.DataFrame([{
                "항목": "총 운항원가",
                "East": detail_df["East"].sum(),
                "West": detail_df["West"].sum(),
                "합계": detail_df["합계"].sum(),
            }])
            full_detail = pd.concat([detail_df, total_row], ignore_index=True)
            st.dataframe(
                full_detail.style.format({"East": "${:,.0f}", "West": "${:,.0f}",
                                          "합계": "${:,.0f}"}),
                use_container_width=True, hide_index=True,
            )

            # BSA 기반 분석 (7단계 추가)
            if ctx_result is not None:
                st.divider()
                st.subheader("🎯 자사 BSA 기준 분석")
                ob = ctx_result.own_breakdown
                ctx = ctx_result.ctx

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("TEU당 단가", f"${ob.per_teu_unit:,.0f}",
                              help=f"= 1척 운항원가 / 1척 선복({ob.capacity_teu:,.0f}TEU)")
                with c2:
                    st.metric("자사 부담", f"${ob.own_total_cost:,.0f}",
                              help=f"= BSA {ob.bsa_teu:,.0f} × ${ob.per_teu_unit:,.0f}")
                with c3:
                    if ob.slot_balance_teu > 0:
                        st.metric("선복 임대 수익",
                                  f"${ob.slot_lending_revenue:,.0f}",
                                  delta=f"잉여 {ob.slot_balance_teu:+,.0f}TEU",
                                  delta_color="normal")
                    elif ob.slot_balance_teu < 0:
                        st.metric("선복 임차 비용",
                                  f"${ob.slot_charter_cost:,.0f}",
                                  delta=f"부족 {ob.slot_balance_teu:+,.0f}TEU",
                                  delta_color="inverse")
                    else:
                        st.metric("선복 수지", "균형")
                with c4:
                    st.metric("순 운항원가",
                              f"${ob.net_voyage_cost:,.0f}",
                              help="자사 부담 + 임차비 - 임대수익")

                # 검증 정보
                with st.expander("📐 BSA 계산 상세"):
                    st.markdown(f"""
                    - **서비스 구조**: {ctx.total_vessels_in_service}척 공동운항, 자사 {ctx.own_vessels_deployed}척 투입
                    - **1척 선복 (14T)**: {ctx.vessel_capacity_teu_14t:,.0f} TEU
                    - **자사 BSA**: {ctx.effective_bsa_teu:,.0f} TEU (지분 {ctx.own_share_ratio:.1%})
                    - **자사 제공 선복**: {ctx.own_vessel_capacity_provided_teu:,.0f} TEU
                    - **선복 수지**: {ctx.slot_balance_teu:+,.0f} TEU ({ctx.slot_position})

                    **검증**: 자사 부담 + 임대 수익 = ${ob.own_total_cost + ob.slot_lending_revenue:,.0f}
                    (1척 전체 운항원가와 일치해야 함)
                    """)

    with tabs[2]:
        st.subheader("민감도 분석: 각 변수 +10% 시 운항이익 변화")
        sens = sensitivity_analysis(baseline, delta=0.10)
        sens_df = pd.DataFrame({
            "변수": list(sens.keys()),
            "운항이익 변화": list(sens.values()),
        }).sort_values("운항이익 변화", key=abs, ascending=True)

        fig = go.Figure(go.Bar(
            x=sens_df["운항이익 변화"], y=sens_df["변수"], orientation="h",
            marker_color=["#ef4444" if v < 0 else "#22c55e" for v in sens_df["운항이익 변화"]],
            text=[f"{v:+,.0f}" for v in sens_df["운항이익 변화"]],
            textposition="outside",
        ))
        fig.update_layout(xaxis_title="운항이익 변화 (USD)",
                          height=400, margin=dict(l=0, r=40, t=20, b=40))
        st.plotly_chart(fig, use_container_width=True)

        bep = break_even_freight_rate(baseline)
        st.divider()
        st.subheader("BEP(손익분기점) 분석")
        col_e, col_w = st.columns(2)
        with col_e:
            if bep["east"] is not None:
                st.metric("E 방향 BEP 운임 변동", f"{bep['east']:+.1%}")
        with col_w:
            if bep["west"] is not None:
                st.metric("W 방향 BEP 운임 변동", f"{bep['west']:+.1%}")

    with tabs[3]:
        st.subheader("선형 변경 What-if")
        if not in_service_list:
            st.warning("이 서비스의 프로포마 데이터가 없어 비교 불가합니다.")
        else:
            compare_types = mgr.vessel_spec.find_types_by_teu(vessel_teu, 0.30)
            with_aux = compare_types.dropna(subset=["aux_at_sea", "aux_at_port"])
            missing_aux = len(compare_types) - len(with_aux)
            if missing_aux > 0:
                st.caption(f"⚠️ aux 데이터 없는 {missing_aux}개 선형은 자동 비교에서 제외됩니다. "
                           f"`vessel_spec_supplement.xlsx`로 보완 가능.")
            compare_types = with_aux
            if compare_types.empty:
                st.info("비교할 만한 선형이 없습니다. (aux 데이터 보유 선형 부족)")
            else:
                vc = VoyageCostCalculator(mgr)
                compare_data = []
                with st.spinner("선형별 운항원가 계산 중..."):
                    for _, row in compare_types.head(8).iterrows():
                        try:
                            cost = vc.calculate(
                                service_code, row["type_name"],
                                year, month, fuel_type,
                                bunker_port=bunker_port,
                                port_fuel_type=port_fuel_type if port_fuel_type != fuel_type else None,
                            )
                            compare_data.append({
                                "선형": row["type_name"],
                                "TEU": int(row["teu_nominal"]),
                                "연료비": cost.total_fuel_usd,
                                "항비": cost.total_port_charge_usd,
                                "용선료": cost.total_charter_usd,
                                "총 운항원가": cost.grand_total_usd,
                                "TEU당 원가": cost.grand_total_usd / row["teu_nominal"],
                            })
                        except Exception:
                            continue

                if compare_data:
                    cmp_df = pd.DataFrame(compare_data).sort_values("TEU당 원가")
                    st.dataframe(
                        cmp_df.style.format({
                            "연료비": "${:,.0f}", "항비": "${:,.0f}",
                            "용선료": "${:,.0f}", "총 운항원가": "${:,.0f}",
                            "TEU당 원가": "${:,.0f}",
                        }).highlight_min(subset=["TEU당 원가"], color="#bbf7d0"),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption("💡 녹색 = TEU당 원가가 가장 낮은 (가장 효율적인) 선형")

        if vessel_change_result:
            st.divider()
            new_bl = vessel_change_result["new_baseline"]
            st.subheader(f"선형 변경 결과: {vessel_type} → {vessel_change_result['new_vessel_type']}")
            change_data = pd.DataFrame([{
                "항목": "연료비 (E+W)",
                "현재": baseline.east.voyage_var_cost.fuel + baseline.west.voyage_var_cost.fuel,
                "변경 후": new_bl.east.voyage_var_cost.fuel + new_bl.west.voyage_var_cost.fuel,
            }, {
                "항목": "항비 (E+W)",
                "현재": baseline.east.voyage_var_cost.port_charge + baseline.west.voyage_var_cost.port_charge,
                "변경 후": new_bl.east.voyage_var_cost.port_charge + new_bl.west.voyage_var_cost.port_charge,
            }, {
                "항목": "용선료 (E+W)",
                "현재": baseline.east.voyage_fixed_cost.charter_hire + baseline.west.voyage_fixed_cost.charter_hire,
                "변경 후": new_bl.east.voyage_fixed_cost.charter_hire + new_bl.west.voyage_fixed_cost.charter_hire,
            }, {
                "항목": "운항이익",
                "현재": baseline.total_voyage_profit,
                "변경 후": new_bl.total_voyage_profit,
            }])
            change_data["변화"] = change_data["변경 후"] - change_data["현재"]
            st.dataframe(
                change_data.style.format({
                    "현재": "${:,.0f}", "변경 후": "${:,.0f}", "변화": "${:+,.0f}",
                }),
                use_container_width=True, hide_index=True,
            )

    with tabs[4]:
        st.subheader("데이터 가정 및 경고")
        st.caption("이 시스템이 사용한 가정값과 데이터 이슈입니다. 임원 보고 시 함께 명시하면 투명성이 확보됩니다.")

        st.markdown("**📋 시스템 가정값**")
        try:
            from config import FUEL_ASSUMPTIONS
            st.json(FUEL_ASSUMPTIONS)
        except ImportError:
            pass

        st.markdown("**⚠️ 활성 경고**")
        if integration_warnings:
            for w in integration_warnings:
                st.warning(w)
        else:
            st.success("현재 활성 경고 없음")

        st.markdown("**📄 기타 데이터 이슈**")
        st.info(
            "1. PORT_CHARGE CA16 컬럼 의미 불명확 (운영팀 확인 필요)  \n"
            "2. 5000TEU 초과 선형의 항비 데이터 부재 (CA15로 폴백)  \n"
            "3. 일부 선형 시트의 aux engine 데이터 누락  \n"
            "4. Maneuvering 비율 40% 가정 (실측 기준 미확정)  \n\n"
            "상세는 `data/DATA_ISSUES.md` 참조"
        )


if __name__ == "__main__":
    main()
