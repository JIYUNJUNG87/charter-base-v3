"""
다중 시나리오 비교 페이지.

SMX 업사이징 양식과 유사한 구조:
- 상단: 시나리오 정의 (가로 3개 카드)
- 중단: 통합 비교 표 (항목별 가로 비교 + 차이값)
- 하단: 시각화 (TEU당 원가, 시간 분포)
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from src.data_loaders import MasterDataManager
from src.engine.scenario_compare import ScenarioSpec, ScenarioComparator
from src.engine.service_context import DAYS_PER_VESSEL


st.set_page_config(page_title="시나리오 비교", page_icon="🔀", layout="wide")


from src.ui.shared import get_data_manager, get_comparator


def main():
    st.title("🔀 시나리오 비교")
    st.caption("여러 항로/선형/BSA 시나리오를 동시에 계산하고 비교 (SMX 업사이징 검토 같은 분석에 사용)")

    mgr = get_data_manager()
    comp = get_comparator()

    # 사용 가능 항로/선형
    services = mgr.service.get_services()["service_code"].tolist()
    types_df = mgr.vessel_spec.get_types().dropna(subset=["teu_nominal"]).copy()

    def _vessel_label(r):
        warn = "" if (pd.notna(r["aux_at_sea"]) and pd.notna(r["aux_at_port"])) else "⚠️ "
        teu14 = f"{int(r['teu_at_14t'])}T" if pd.notna(r["teu_at_14t"]) else "?"
        return f"{warn}{r['type_name']} (디자인 {int(r['teu_nominal'])} / 14T {teu14})"

    types_df["label"] = types_df.apply(_vessel_label, axis=1)
    type_names = types_df["type_name"].tolist()
    type_labels = types_df["label"].tolist()

    # ============================================================
    # 시나리오 정의
    # ============================================================
    st.subheader("1️⃣ 시나리오 정의")
    st.caption("최대 4개 시나리오를 정의하고 한꺼번에 비교합니다.")

    # 시나리오 수
    n_scenarios = st.slider("시나리오 수", 2, 4, 3)

    # 각 시나리오 카드 (가로 배치)
    cols = st.columns(n_scenarios)
    specs = []

    default_names = ["베이스 (현재)", "변경안 1", "변경안 2", "변경안 3"]

    for i in range(n_scenarios):
        with cols[i]:
            st.markdown(f"**시나리오 {i+1}**")
            name = st.text_input("이름", default_names[i], key=f"name_{i}")

            # 서비스 코드
            default_svc_idx = services.index("SMX") if "SMX" in services else 0
            svc_idx = st.selectbox(
                "항로",
                range(len(services)),
                format_func=lambda j: services[j],
                index=default_svc_idx,
                key=f"svc_{i}",
            )
            service_code = services[svc_idx]

            # 선형
            default_vessel_idx = next(
                (j for j, n in enumerate(type_names) if n == "Jiangsu 4250"),
                0,
            )
            v_idx = st.selectbox(
                "선형",
                range(len(type_names)),
                format_func=lambda j: type_labels[j],
                index=default_vessel_idx,
                key=f"vessel_{i}",
            )
            vessel_type = type_names[v_idx]

            # 척수 / BSA
            c1, c2 = st.columns(2)
            with c1:
                total_v = st.number_input(
                    "총 척수", 1, 20, 6, key=f"total_{i}",
                )
            with c2:
                own_v = st.number_input(
                    "자사 척수", 0, total_v, 1, key=f"own_{i}",
                )

            # 자동 BSA 미리보기
            vrow = types_df[types_df["type_name"] == vessel_type].iloc[0]
            cap_14t = float(vrow["teu_at_14t"]) if pd.notna(vrow["teu_at_14t"]) else float(vrow["teu_nominal"])
            auto_bsa = cap_14t * (own_v / total_v) if total_v > 0 else 0

            use_manual = st.checkbox(
                f"BSA 수기 (자동 {auto_bsa:.0f})",
                key=f"manual_bsa_{i}",
            )
            if use_manual:
                bsa_val = st.number_input(
                    "BSA (TEU)",
                    min_value=0.0,
                    value=float(round(auto_bsa)),
                    step=10.0,
                    key=f"bsa_val_{i}",
                )
            else:
                bsa_val = None

            # 운영 형태 표시
            if own_v == 0:
                st.caption("🔵 순수 임차")
            elif own_v == total_v:
                st.caption("🟢 자사 단독")
            else:
                st.caption(f"🟡 공동운항 (BSA {bsa_val or auto_bsa:.0f}TEU)")

            specs.append(ScenarioSpec(
                name=name,
                service_code=service_code,
                vessel_type=vessel_type,
                total_vessels=int(total_v),
                own_vessels=int(own_v),
                bsa_override=bsa_val,
            ))

    # 공통 시점
    st.divider()
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        year = st.number_input("기준 연도", 2024, 2027, 2026)
    with c2:
        month = st.number_input("기준 월", 1, 12, 1)
    with c3:
        bunker_port = st.selectbox(
            "벙커링 항구",
            ["KOR", "HKG", "SIN", "SHA", "FJR", "RUS"],
        )
    with c4:
        fuel_type = st.selectbox(
            "항해 유종", ["LSFO", "380CST"],
            help="메인엔진",
        )
    with c5:
        port_fuel_type = st.selectbox(
            "정박 유종", ["LSFO", "380CST", "LSMGO", "MGO"],
            help="보조엔진",
        )

    for s in specs:
        s.year = int(year)
        s.month = int(month)
        s.fuel_type = fuel_type
        s.bunker_port = bunker_port
        s.port_fuel_type = port_fuel_type if port_fuel_type != fuel_type else None

    # ============================================================
    # 비교 실행
    # ============================================================
    if st.button("🚀 시나리오 비교 실행", type="primary"):
        with st.spinner(f"{len(specs)}개 시나리오 계산 중..."):
            try:
                results = comp.evaluate_many(specs)
                st.session_state.last_results = results
            except Exception as e:
                st.error(f"계산 실패: {e}")
                import traceback
                with st.expander("상세"):
                    st.code(traceback.format_exc())
                return

    # ============================================================
    # 결과 표시
    # ============================================================
    if "last_results" not in st.session_state:
        st.info("위에서 시나리오를 정의하고 '시나리오 비교 실행' 버튼을 누르세요.")
        return

    results = st.session_state.last_results
    if not results:
        st.warning("계산된 결과 없음")
        return

    st.divider()
    st.subheader("2️⃣ 비교 결과")

    # 상단: 핵심 지표 카드 (시나리오별 가로)
    st.markdown("### 핵심 지표")
    metric_cols = st.columns(len(results))
    for i, r in enumerate(results):
        with metric_cols[i]:
            st.markdown(f"**{r.spec.name}**")
            st.caption(r.spec.short_summary())
            st.metric("TEU당 단가", f"${r.per_teu_unit:,.0f}")
            st.metric("1척 총원가", f"${r.total_voyage_cost:,.0f}")
            st.metric("자사 부담", f"${r.own_total_cost:,.0f}")
            st.metric("순 운항원가", f"${r.net_voyage_cost:,.0f}",
                      help="자사 부담 - 임대 수익")

    # 중단: 통합 비교 표
    st.divider()
    st.markdown("### 통합 비교 표")

    # 베이스(첫 번째) 대비 차이 표시 옵션
    show_diff = st.checkbox("베이스(첫 번째 시나리오) 대비 차이값 표시", value=True)

    df = _build_comparison_dataframe(results, show_diff=show_diff)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 하단: 시각화
    st.divider()
    st.markdown("### 시각화")

    vc1, vc2 = st.columns(2)

    with vc1:
        st.markdown("**TEU당 단가 비교**")
        fig_teu = go.Figure(data=[
            go.Bar(
                x=[r.spec.name for r in results],
                y=[r.per_teu_unit for r in results],
                marker_color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"][:len(results)],
                text=[f"${r.per_teu_unit:,.0f}" for r in results],
                textposition="outside",
            )
        ])
        fig_teu.update_layout(
            yaxis_title="USD / TEU", height=320,
            margin=dict(l=20, r=20, t=20, b=20),
        )
        st.plotly_chart(fig_teu, use_container_width=True)

    with vc2:
        st.markdown("**운항원가 구성 (1척 기준)**")
        cost_df = pd.DataFrame([
            {"시나리오": r.spec.name, "항목": "연료비", "금액": r.fuel_cost}
            for r in results
        ] + [
            {"시나리오": r.spec.name, "항목": "항비", "금액": r.port_charge}
            for r in results
        ] + [
            {"시나리오": r.spec.name, "항목": "용선료", "금액": r.charter_hire}
            for r in results
        ])
        fig_stack = px.bar(
            cost_df, x="시나리오", y="금액", color="항목",
            color_discrete_map={"연료비": "#ef4444", "항비": "#f59e0b", "용선료": "#3b82f6"},
        )
        fig_stack.update_layout(
            yaxis_title="USD", height=320,
            margin=dict(l=20, r=20, t=20, b=20),
        )
        st.plotly_chart(fig_stack, use_container_width=True)

    # 시간 분포
    st.markdown("**시간 분포 (1항차 기준)**")
    time_df = pd.DataFrame([
        {"시나리오": r.spec.name, "구분": "SEA", "시간": r.sea_hours}
        for r in results
    ] + [
        {"시나리오": r.spec.name, "구분": "TERMINAL", "시간": r.terminal_hours}
        for r in results
    ] + [
        {"시나리오": r.spec.name, "구분": "MANV", "시간": r.manv_hours}
        for r in results
    ] + [
        {"시나리오": r.spec.name, "구분": "BUFFER", "시간": r.buffer_hours}
        for r in results
    ])
    fig_time = px.bar(
        time_df, x="시나리오", y="시간", color="구분",
        orientation="v", barmode="stack",
        color_discrete_map={
            "SEA": "#3b82f6", "TERMINAL": "#10b981",
            "MANV": "#f59e0b", "BUFFER": "#a78bfa",
        },
    )
    fig_time.update_layout(
        yaxis_title="시간 (h)", height=300,
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_time, use_container_width=True)

    # 경고
    all_warnings = []
    for r in results:
        for w in r.warnings:
            all_warnings.append(f"[{r.spec.name}] {w}")
    if all_warnings:
        with st.expander(f"⚠️ Warnings ({len(all_warnings)}건)"):
            for w in all_warnings:
                st.caption(w)


def _build_comparison_dataframe(results, show_diff: bool) -> pd.DataFrame:
    """시나리오별 가로 비교 DataFrame"""
    base = results[0]

    def fmt(v, is_money=True, sign=False):
        if v is None:
            return "-"
        if isinstance(v, (int, float)):
            if sign:
                return f"{v:+,.0f}" if not is_money else f"${v:+,.0f}"
            return f"{v:,.0f}" if not is_money else f"${v:,.0f}"
        return str(v)

    def pct(curr, base_val):
        if base_val == 0:
            return ""
        diff_pct = (curr - base_val) / abs(base_val) * 100
        return f" ({diff_pct:+.1f}%)"

    rows = []

    def add_row(label, attr, is_money=True, money_unit=""):
        row = {"항목": label}
        for i, r in enumerate(results):
            v = getattr(r, attr)
            cell = fmt(v, is_money=is_money)
            if show_diff and i > 0 and isinstance(v, (int, float)):
                diff = v - getattr(base, attr)
                cell += f"\n(Δ {fmt(diff, is_money=is_money, sign=True)}{pct(v, getattr(base, attr))})"
            row[r.spec.name] = cell
        rows.append(row)

    # 운항 정보
    rows.append({"항목": "━━━ 운항 정보 ━━━", **{r.spec.name: "" for r in results}})
    add_row("항차 일수", "voyage_days", is_money=False)
    add_row("총 거리 (NM)", "total_distance_nm", is_money=False)
    add_row("구간 수", "leg_count", is_money=False)

    # 선복
    rows.append({"항목": "━━━ 선복 / BSA ━━━", **{r.spec.name: "" for r in results}})
    add_row("1척 선복 (14T)", "capacity_teu", is_money=False)
    add_row("자사 BSA", "bsa_teu", is_money=False)
    add_row("선복 수지", "slot_balance_teu", is_money=False)

    # 1척 운항원가
    rows.append({"항목": "━━━ 1척 운항원가 ━━━", **{r.spec.name: "" for r in results}})
    add_row("연료비", "fuel_cost")
    add_row("항비", "port_charge")
    add_row("용선료", "charter_hire")
    add_row("1척 총원가", "total_voyage_cost")

    # BSA 기반
    rows.append({"항목": "━━━ BSA 기반 분석 ━━━", **{r.spec.name: "" for r in results}})
    add_row("TEU당 단가", "per_teu_unit")
    add_row("자사 부담", "own_total_cost")
    add_row("임대 수익", "slot_lending_revenue")
    add_row("임차 비용", "slot_charter_cost")
    add_row("순 운항원가", "net_voyage_cost")

    # 시간 분포
    rows.append({"항목": "━━━ 시간 분포 (h) ━━━", **{r.spec.name: "" for r in results}})
    add_row("SEA", "sea_hours", is_money=False)
    add_row("TERMINAL", "terminal_hours", is_money=False)
    add_row("MANV", "manv_hours", is_money=False)
    add_row("BUFFER", "buffer_hours", is_money=False)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
