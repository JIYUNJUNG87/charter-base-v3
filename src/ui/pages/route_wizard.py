"""
신규 항로 마법사 UI (v2 - BSA/공동운항 반영).

새 흐름:
  1. 서비스 기본 정보 + 선형 선택 (먼저!)
  2. 서비스 구조 (총 척수, 자사 척수, BSA)
  3. 기항지 입력
  4. 표준 가정값 + 목표 항차일수 (7일 단위)
  5. 프로포마 생성 + 운항원가 즉시 산출

핵심 변화:
- 선형을 먼저 선택해야 BSA 자동 산정 + 정박시간 스케일링 가능
- 7일 배수 (1척=7일, 2척=14일...) 자동 조정
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

from src.data_loaders import MasterDataManager
from src.wizard import ProformaBuilder, DistanceMatrix, StandardValueExtractor
from src.cost_calculators import VoyageCostCalculator, VoyageCostIntegrator
from src.engine.service_context import ServiceContext, DAYS_PER_VESSEL


st.set_page_config(page_title="신규 항로 마법사", page_icon="🆕", layout="wide")


from src.ui.shared import (
    get_data_manager, get_builder, get_distance_matrix,
)


def _suggest_aux_sea(teu_nominal: float) -> float:
    """디자인 TEU 기준 항해중 aux 추천값 (톤/일)"""
    if teu_nominal < 1500:
        return 3.5
    elif teu_nominal < 3000:
        return 5.5
    elif teu_nominal < 5000:
        return 7.5
    elif teu_nominal < 7000:
        return 10.0
    else:
        return 13.0


def _suggest_aux_port(teu_nominal: float) -> float:
    """디자인 TEU 기준 정박중 aux 추천값 (톤/일)"""
    if teu_nominal < 1500:
        return 3.0
    elif teu_nominal < 3000:
        return 4.5
    elif teu_nominal < 5000:
        return 6.5
    elif teu_nominal < 7000:
        return 8.5
    else:
        return 11.0


def main():
    st.title("🆕 신규 항로 마법사")
    st.caption("선형 → 서비스 구조(BSA) → 기항지 → 자동 프로포마 → 운항원가 산출")

    mgr = get_data_manager()
    builder = get_builder()
    dm = get_distance_matrix()
    sve = StandardValueExtractor(mgr)

    method = st.radio(
        "작성 방식",
        ["📋 처음부터 만들기", "📑 기존 서비스 복제"],
        horizontal=True,
    )

    if method == "📋 처음부터 만들기":
        _from_scratch_ui(mgr, builder, dm, sve)
    else:
        _from_template_ui(mgr, builder)


def _from_scratch_ui(mgr, builder, dm, sve):
    """처음부터 만들기 (선형 먼저 흐름)"""

    # 초기화 버튼 (오른쪽 위)
    col_reset_l, col_reset_r = st.columns([5, 1])
    with col_reset_r:
        if st.button("🔄 초기화", help="모든 입력값을 기본값으로 되돌립니다"):
            # session_state에서 마법사 관련 키 모두 제거
            wizard_keys = [k for k in st.session_state.keys() if any(
                k.startswith(prefix) for prefix in [
                    "wiz_", "port_", "bnd_", "cost_",
                ]
            )]
            for k in wizard_keys:
                del st.session_state[k]
            st.session_state.port_count = 4
            st.session_state.pop("last_proforma", None)
            st.session_state.pop("last_ctx_info", None)
            st.rerun()

    # ============================================================
    # 1️⃣ 서비스 기본 정보 + 선형 선택
    # ============================================================
    st.subheader("1️⃣ 서비스 기본 정보 + 투입 선형")
    col1, col2 = st.columns([1, 1])
    with col1:
        service_code = st.text_input("서비스 코드", "NEW1", key="wiz_svc_code")
        service_name = st.text_input("서비스명", "New Service", key="wiz_svc_name")

    # 선형 선택 (먼저!)
    types_df = mgr.vessel_spec.get_types()
    valid_types = types_df.dropna(subset=["teu_nominal"]).copy()
    # aux 데이터 없으면 라벨에 ⚠️ 표시
    def _make_label(r):
        warn = "" if (pd.notna(r["aux_at_sea"]) and pd.notna(r["aux_at_port"])) else "⚠️ "
        teu14 = f"{int(r['teu_at_14t'])}T" if pd.notna(r["teu_at_14t"]) else "?"
        return f"{warn}{r['type_name']} (디자인 {int(r['teu_nominal'])} / 14T {teu14})"
    valid_types["label"] = valid_types.apply(_make_label, axis=1)

    with col2:
        default_idx = next(
            (i for i, n in enumerate(valid_types["type_name"]) if n == "Jiangsu 4250"),
            0,
        )
        v_idx = st.selectbox(
            "선형",
            range(len(valid_types)),
            format_func=lambda i: valid_types.iloc[i]["label"],
            index=default_idx,
            key="wiz_vessel_idx",
        )

    vessel_row = valid_types.iloc[v_idx]
    vessel_type = vessel_row["type_name"]
    capacity_14t = float(vessel_row["teu_at_14t"]) if pd.notna(vessel_row["teu_at_14t"]) else float(vessel_row["teu_nominal"])

    # 누락된 데이터 확인 + 수기 입력 UI
    aux_sea_missing = pd.isna(vessel_row.get("aux_at_sea"))
    aux_port_missing = pd.isna(vessel_row.get("aux_at_port"))
    teu14_missing = pd.isna(vessel_row.get("teu_at_14t"))

    if aux_sea_missing or aux_port_missing or teu14_missing:
        with st.expander("⚠️ 일부 데이터가 누락되어 수기 입력이 필요합니다", expanded=True):
            st.caption(
                "이 선형은 보조엔진 또는 14T 선복 데이터가 비어있습니다. "
                "아래 값을 입력하면 시뮬레이션에 반영됩니다. "
                "영구 반영하려면 `vessel_spec_supplement.xlsx`에 채워서 master 폴더에 두세요."
            )
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                if teu14_missing:
                    capacity_14t = st.number_input(
                        "14T TEU (필수)",
                        min_value=0.0,
                        value=float(vessel_row["teu_nominal"]) * 0.7,  # 디자인의 70% 추정
                        step=10.0,
                        help="14톤 기준 선복. 보통 디자인 TEU의 65~75%",
                        key="manual_14t",
                    )
                else:
                    st.metric("14T TEU", f"{int(capacity_14t):,}")
            with mc2:
                if aux_sea_missing:
                    aux_sea_manual = st.number_input(
                        "Aux 항해중 (톤/일)",
                        min_value=0.0,
                        value=_suggest_aux_sea(vessel_row["teu_nominal"]),
                        step=0.5,
                        help="항해 중 보조엔진 일일 소모량",
                        key="manual_aux_sea",
                    )
                else:
                    aux_sea_manual = None
                    st.metric("Aux 항해중", f"{vessel_row['aux_at_sea']:.1f} 톤/일")
            with mc3:
                if aux_port_missing:
                    aux_port_manual = st.number_input(
                        "Aux 정박중 (톤/일)",
                        min_value=0.0,
                        value=_suggest_aux_port(vessel_row["teu_nominal"]),
                        step=0.5,
                        help="정박 중 보조엔진 일일 소모량",
                        key="manual_aux_port",
                    )
                else:
                    aux_port_manual = None
                    st.metric("Aux 정박중", f"{vessel_row['aux_at_port']:.1f} 톤/일")
        # 세션에 저장 (운항원가 계산 시 사용)
        st.session_state["aux_overrides"] = {
            "type_name": vessel_type,
            "aux_at_sea": aux_sea_manual,
            "aux_at_port": aux_port_manual,
        }
    else:
        st.session_state.pop("aux_overrides", None)

    # 무게 기준
    weight_basis = st.radio(
        "선복 기준",
        [14.0, 13.5, 12.0],
        format_func=lambda v: f"{v}TON HOMO (표준)" if v == 14.0 else f"{v}TON HOMO",
        horizontal=True,
        help="대부분 14T 기준. 일부 항로는 12T/13.5T",
        key="wiz_weight_basis",
    )

    # ============================================================
    # 2️⃣ 서비스 구조 (총 척수, 자사 척수, BSA)
    # ============================================================
    st.divider()
    st.subheader("2️⃣ 서비스 구조 (공동운항)")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_vessels = st.number_input("서비스 총 척수", 1, 20, 6,
                                        help="공동운항 멤버 합산",
                                        key="wiz_total_vessels")
    with col2:
        own_vessels = st.number_input("자사 투입 척수", 0, total_vessels, 1,
                                      help="0이면 순수 임차",
                                      key="wiz_own_vessels")
    with col3:
        auto_bsa = capacity_14t * (own_vessels / total_vessels) if total_vessels > 0 else 0
        st.metric("자동 BSA", f"{auto_bsa:,.0f} TEU",
                  help=f"= {capacity_14t:,.0f} × ({own_vessels}/{total_vessels})")
    with col4:
        use_manual_bsa = st.checkbox("BSA 수기 조정", key="wiz_manual_bsa")

    bsa_teu = None
    if use_manual_bsa:
        bsa_teu = st.number_input(
            "수기 BSA (TEU)",
            min_value=0.0,
            value=float(round(auto_bsa)),
            step=10.0,
            key="wiz_bsa_value",
        )
    else:
        bsa_teu = auto_bsa

    # 운영 형태 자동 판단
    if own_vessels == 0:
        op_type = "charter_only"
        st.info("🔵 운영 형태: **순수 임차** (Slot Charter) - 자사 배 없음, BSA만 임차")
    elif own_vessels == total_vessels:
        op_type = "owned"
        st.info("🟢 운영 형태: **자사 단독 운항**")
    else:
        op_type = "shared"
        st.info(f"🟡 운영 형태: **공동운항** - 자사 {own_vessels}척 / 총 {total_vessels}척")

    # 이론 항차일수
    expected_days = total_vessels * DAYS_PER_VESSEL
    st.caption(f"💡 이론 항차일수: **{expected_days}일** (= {total_vessels}척 × 7일)")

    # ============================================================
    # 3️⃣ 기항지 입력
    # ============================================================
    st.divider()
    st.subheader("3️⃣ 기항지 순서")
    st.caption("순서대로 항구 코드를 입력하세요.")

    known_ports = dm.get_known_ports()

    if "port_count" not in st.session_state:
        st.session_state.port_count = 4

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("➕ 기항지 추가"):
            st.session_state.port_count += 1
    with c2:
        if st.button("➖ 마지막 제거") and st.session_state.port_count > 2:
            st.session_state.port_count -= 1
    with c3:
        st.caption(f"현재 입력 칸: {st.session_state.port_count}개")

    port_sequence = []
    port_cols = st.columns(min(st.session_state.port_count, 6))
    for i in range(st.session_state.port_count):
        col = port_cols[i % 6]
        with col:
            default = "KRPUS" if i == 0 else ""
            port = st.text_input(
                f"기항지 {i+1}",
                value=default,
                key=f"port_{i}",
            ).strip().upper()
            if port:
                port_sequence.append(port)
                if port not in known_ports:
                    st.caption(f"⚠️ 미등록")

    # 출발지 자동 복귀 옵션
    auto_return = st.checkbox(
        "🔄 출발지로 자동 복귀 (왕복 완성)",
        value=True,
        help="체크하면 마지막에 첫 항구를 자동으로 추가해서 왕복 항로 완성. "
             "예: KRPUS → KRUSN → CNSHA 입력 시 자동으로 CNSHA → KRPUS 구간 추가됨.",
        key="wiz_auto_return",
    )
    if auto_return and len(port_sequence) >= 2:
        if port_sequence[-1] != port_sequence[0]:
            # 첫 항구를 마지막에 자동 추가
            port_sequence = port_sequence + [port_sequence[0]]
            st.caption(
                f"✨ 출발지 자동 복귀 적용: 마지막에 **{port_sequence[0]}** 자동 추가됨 "
                f"(총 {len(port_sequence)}개 기항지, {len(port_sequence) - 1}구간)"
            )
        else:
            st.caption(f"✅ 이미 왕복 완성됨 ({len(port_sequence)}개 기항지)")

    # ============================================================
    # 4️⃣ 표준 가정값 + 목표 항차일수
    # ============================================================
    st.divider()
    st.subheader("4️⃣ 표준 가정값")

    std = sve.suggest_assumptions()
    c1, c2 = st.columns(2)
    with c1:
        speed = st.number_input(
            "표준 선속 (knot)",
            min_value=8.0, max_value=25.0,
            value=float(std.speed_knot), step=0.5,
            help="버퍼 자동 조정 시 선속 유지하며 버퍼만 변경",
            key="wiz_speed",
        )
    with c2:
        target_days = st.number_input(
            f"목표 항차일수 (7의 배수)",
            min_value=7, max_value=84,
            value=expected_days,
            step=7,
            help=f"권장: {expected_days}일 ({total_vessels}척 × 7일)",
            key="wiz_target_days",
        )
        if target_days != expected_days:
            st.caption(f"⚠️ 척수와 불일치 (권장: {expected_days}일)")

    # ============================================================
    # 5️⃣ 구간별 바운드 입력 (트리거 기반 수출/수입)
    # ============================================================
    st.divider()
    st.subheader("5️⃣ 구간별 바운드 (수출/수입)")
    st.caption(
        "각 구간의 바운드를 선택하세요. **트리거 항구 이전 = 수출, 이후 = 수입**.\n"
        "표기는 노선 지리에 따라 다름: 미주=E/W, 동남아=S/N, 인도/중동=W/E"
    )

    # 기본값 추정 (수출/수입 룰)
    def _default_bnd(fp, tp, idx, ports):
        fp_kr = fp.startswith("KR")
        tp_kr = tp.startswith("KR")
        if fp_kr and not tp_kr:
            return "W"  # KR→외국 = 수출 기본 W
        if not fp_kr and tp_kr:
            return "E"  # 외국→KR = 수입 기본 E
        # 모호한 케이스 - 인접 구간 따라감
        for j in range(idx + 1, len(ports) - 1):
            nfp, ntp = ports[j], ports[j + 1]
            if nfp.startswith("KR") and not ntp.startswith("KR"):
                return "W"
            if not nfp.startswith("KR") and ntp.startswith("KR"):
                return "E"
        for j in range(idx - 1, -1, -1):
            pfp, ptp = ports[j], ports[j + 1]
            if pfp.startswith("KR") and not ptp.startswith("KR"):
                return "W"
            if not pfp.startswith("KR") and ptp.startswith("KR"):
                return "E"
        return "W"

    leg_bnds = []
    if len(port_sequence) >= 2:
        bnd_options = ["S", "N", "E", "W"]
        n_legs_preview = len(port_sequence) - 1

        # 1~6개씩 그리드로 (모바일/좁은 화면 대응)
        legs_per_row = 4
        for row_start in range(0, n_legs_preview, legs_per_row):
            row_cols = st.columns(legs_per_row)
            for j in range(legs_per_row):
                idx = row_start + j
                if idx >= n_legs_preview:
                    break
                fp = port_sequence[idx]
                tp = port_sequence[idx + 1]
                default = _default_bnd(fp, tp, idx, port_sequence)
                with row_cols[j]:
                    bnd = st.selectbox(
                        f"seq {idx+1}: {fp}→{tp}",
                        bnd_options,
                        index=bnd_options.index(default),
                        key=f"bnd_{idx}",
                    )
                    leg_bnds.append(bnd)

        # 트리거 항구 자동 추정 (시각적 안내용)
        if leg_bnds:
            # 첫 번째로 방향이 바뀌는 지점 찾기
            trigger_idx = None
            export_set = {"W", "S"}  # 수출 방향 (W=서쪽수출, S=남쪽수출)
            for i in range(1, len(leg_bnds)):
                if leg_bnds[i-1] in export_set and leg_bnds[i] not in export_set:
                    trigger_idx = i - 1  # 수출 마지막 leg
                    break
                if leg_bnds[i-1] not in export_set and leg_bnds[i] in export_set:
                    trigger_idx = i - 1
                    break

            if trigger_idx is not None and trigger_idx < n_legs_preview:
                trigger_port = port_sequence[trigger_idx + 1]
                st.caption(
                    f"🎯 추정 트리거 항구: **{trigger_port}** "
                    f"(seq {trigger_idx+1}에서 방향 전환)"
                )

    # 생성 버튼
    can_generate = len(port_sequence) >= 2 and len(leg_bnds) == len(port_sequence) - 1
    if st.button("🚀 프로포마 생성", type="primary", disabled=not can_generate):
        try:
            with st.spinner("프로포마 생성 중..."):
                proforma = builder.build_from_scratch(
                    service_code=service_code,
                    service_name=service_name,
                    port_sequence=port_sequence,
                    direction_pattern="manual",
                    leg_directions=leg_bnds,
                    speed_knot=speed,
                    bsa_teu=bsa_teu,
                    capacity_teu_14t=capacity_14t,
                    target_voyage_days=target_days,
                )
                st.session_state.last_proforma = proforma
                st.session_state.last_ctx_info = {
                    "service_code": service_code,
                    "total_vessels": total_vessels,
                    "own_vessels": own_vessels,
                    "vessel_type": vessel_type,
                    "capacity_14t": capacity_14t,
                    "bsa_teu": bsa_teu,
                    "weight_basis": weight_basis,
                    "op_type": op_type,
                }
        except Exception as e:
            st.error(f"생성 실패: {e}")

    # 결과 표시
    if "last_proforma" in st.session_state:
        _display_result(mgr, st.session_state.last_proforma,
                       st.session_state.last_ctx_info)


def _from_template_ui(mgr, builder):
    """기존 서비스 복제 (기존 흐름 유지하되 BSA 추가)"""
    st.subheader("1️⃣ 기본 정보")
    c1, c2 = st.columns(2)
    with c1:
        new_code = st.text_input("새 서비스 코드", "NEW_FROM_TEMPLATE")
    with c2:
        new_name = st.text_input("새 서비스명", "Modified Service")

    st.subheader("2️⃣ 템플릿 선택")
    services = mgr.service.get_services()
    template_labels = [
        f"{r['service_code']} - {r['service_name']}"
        for _, r in services.iterrows()
    ]
    template_idx = st.selectbox(
        "복제할 서비스",
        range(len(services)),
        format_func=lambda i: template_labels[i],
    )
    template_code = services.iloc[template_idx]["service_code"]

    template_legs = mgr.service.get_legs(template_code)
    st.caption(f"📋 원본: {len(template_legs)}구간, {template_legs['distance_nm'].sum():,.0f}NM")
    with st.expander("원본 프로포마 보기"):
        st.dataframe(
            template_legs[["seq", "from_port", "to_port", "bnd", "distance_nm", "speed_knot"]],
            hide_index=True, use_container_width=True,
        )

    st.subheader("3️⃣ 항구 교체 (선택)")
    n_overrides = st.number_input("교체할 항구 수", 0, 5, 0)
    port_overrides = {}
    if n_overrides > 0:
        cols = st.columns(2)
        for i in range(n_overrides):
            with cols[0]:
                orig = st.text_input(f"원래 {i+1}", key=f"orig_{i}").strip().upper()
            with cols[1]:
                new_p = st.text_input(f"새 {i+1}", key=f"new_{i}").strip().upper()
            if orig and new_p:
                port_overrides[orig] = new_p

    if st.button("🚀 프로포마 생성", type="primary"):
        try:
            proforma = builder.build_from_template(
                new_service_code=new_code,
                new_service_name=new_name,
                template_service_code=template_code,
                port_overrides=port_overrides,
            )
            st.session_state.last_proforma = proforma
            st.session_state.last_ctx_info = None
        except Exception as e:
            st.error(f"생성 실패: {e}")

    if "last_proforma" in st.session_state:
        _display_result(mgr, st.session_state.last_proforma,
                       st.session_state.get("last_ctx_info"))


def _display_result(mgr, proforma, ctx_info):
    """프로포마 결과 + 운항원가 표시"""
    st.divider()
    st.header("📊 생성 결과")

    summary = proforma.summary()

    if ctx_info:
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("구간", summary["leg_count"])
        with c2:
            st.metric("총 거리", f"{summary['total_distance_nm']:,.0f}NM")
        with c3:
            st.metric("총 일수", f"{summary['total_time_days']:.1f}일")
        with c4:
            st.metric("BSA", f"{ctx_info['bsa_teu']:,.0f}TEU")
        with c5:
            st.metric("운영 형태", ctx_info["op_type"])
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("구간", summary["leg_count"])
        with c2:
            st.metric("총 거리", f"{summary['total_distance_nm']:,.0f}NM")
        with c3:
            st.metric("총 시간", f"{summary['total_time_hours']:.0f}h")
        with c4:
            st.metric("총 일수", f"{summary['total_time_days']:.1f}일")

    st.markdown(f"**기항지:** {' → '.join(summary['port_sequence'])}")

    if summary["warnings"]:
        with st.expander(f"⚠️ Warnings ({len(summary['warnings'])}건)", expanded=True):
            for w in summary["warnings"]:
                st.warning(w)

    # 구간별 표
    legs_df = pd.DataFrame([{
        "seq": leg.seq, "from": leg.from_port, "to": leg.to_port, "bnd": leg.bnd,
        "거리(NM)": leg.distance_nm, "선속": leg.speed_knot,
        "항해(h)": round(leg.sea_time_min / 60, 1),
        "정박(h)": round(leg.tml_min / 60, 1),
        "Manv(h)": round((leg.tb_manv_min + leg.td_manv_min) / 60, 1),
        "Buffer(h)": round(leg.sea_buff_min / 60, 1),
        "출처": leg.distance_source,
    } for leg in proforma.legs])
    st.dataframe(legs_df, hide_index=True, use_container_width=True)

    # 정박시간 계산 근거 (BSA 기반일 때만)
    if ctx_info and ctx_info.get("bsa_teu") and ctx_info.get("capacity_14t"):
        from src.wizard.dwell_time_calculator import (
            DwellTimeCalculator, REFERENCE_BSA_TEU, SCALING_DAMPING,
        )
        bsa = ctx_info["bsa_teu"]
        cap = ctx_info["capacity_14t"]

        with st.expander("📐 정박시간 계산 근거"):
            st.caption(
                f"**스케일링 공식**: `정박시간 = 기본값(통계 평균) × 배율`\n\n"
                f"**배율 공식**: `1 + (BSA/{REFERENCE_BSA_TEU} - 1) × {SCALING_DAMPING}` "
                f"(기준 BSA {REFERENCE_BSA_TEU}TEU 대비 자사 BSA 비율의 절반만 반영)\n\n"
                f"**현재 BSA**: {bsa:,.0f}TEU → "
                f"**배율**: × {1.0 + (bsa/REFERENCE_BSA_TEU - 1) * SCALING_DAMPING:.2f}"
            )

            dwc = DwellTimeCalculator(mgr)
            rows = []
            for leg in proforma.legs:
                est = dwc.calculate_for_port(leg.to_port, bsa, cap)
                rows.append({
                    "seq": leg.seq,
                    "도착항": leg.to_port,
                    "기본값(h)": round(est.base_minutes / 60, 1),
                    "샘플 수": est.sample_count,
                    "배율": f"× {est.scaling_factor:.2f}",
                    "결과(h)": round(est.adjusted_minutes / 60, 1),
                    "방식": est.method,
                })
            dwell_df = pd.DataFrame(rows)
            st.dataframe(dwell_df, hide_index=True, use_container_width=True)
            st.caption(
                "💡 **기본값** = 회사 데이터에서 그 항구의 평균 정박시간 / "
                "**샘플 수** = 평균 산출에 사용된 항차 수 / "
                "**배율** = BSA 크기에 따른 자동 조정 (0.5~3.0배 제한)"
            )

    # 즉시 운항원가 (BSA 적용)
    st.divider()
    st.header("💰 즉시 운항원가 산출")

    missing = [leg for leg in proforma.legs if leg.distance_nm == 0]
    if missing:
        st.error(f"❌ {len(missing)}개 구간 거리 누락. 운항원가 계산 불가.")
        return

    if not ctx_info:
        st.info("BSA 정보가 없어 1척 기준 운항원가만 산출합니다.")

    c1, c2, c3 = st.columns(3)
    with c1:
        year = st.number_input("연도", 2024, 2027, 2026, key="cost_y")
    with c2:
        month = st.number_input("월", 1, 12, 1, key="cost_m")
    with c3:
        bunker_port = st.selectbox(
            "벙커링 항구",
            ["KOR", "HKG", "SIN", "SHA", "FJR", "RUS"],
            format_func=lambda p: {
                "KOR": "한국 (KOR)", "HKG": "홍콩 (HKG)",
                "SIN": "싱가포르 (SIN)", "SHA": "상하이 (SHA)",
                "FJR": "후자이라 (FJR)", "RUS": "러시아 (RUS)",
            }.get(p, p),
            help="실제 벙커링 항구. 모든 leg에 동일 단가 적용",
            key="cost_bunker_port",
        )

    fc1, fc2 = st.columns(2)
    with fc1:
        sea_fuel = st.selectbox(
            "항해/Maneuvering 유종 (메인엔진)",
            ["LSFO", "380CST"],
            help="메인엔진은 FO 계열만 사용 가능",
            key="cost_sea_fuel",
        )
    with fc2:
        port_fuel = st.selectbox(
            "정박/Buffer 유종 (보조엔진)",
            ["LSFO", "380CST", "LSMGO", "MGO"],
            index=0,
            help="보조엔진은 FO/GO 모두 사용 가능. 항구 규제 따라 GO 쓰는 경우 많음",
            key="cost_port_fuel",
        )

    if st.button("💡 운항원가 계산", type="primary"):
        try:
            new_legs_df = proforma.to_legs_dataframe()
            cache = mgr.service.load()
            new_services = pd.concat([
                cache["services"],
                pd.DataFrame([{
                    "service_code": proforma.service_code,
                    "service_name": proforma.service_name
                }])
            ], ignore_index=True).drop_duplicates(subset=["service_code"], keep="last")
            new_legs = pd.concat([
                cache["legs"][cache["legs"]["service_code"] != proforma.service_code],
                new_legs_df
            ], ignore_index=True)
            mgr.service._cache = {"services": new_services, "legs": new_legs}

            calc = VoyageCostCalculator(mgr)
            cost = calc.calculate(
                proforma.service_code,
                ctx_info["vessel_type"] if ctx_info else "Jiangsu 4250",
                year, month,
                fuel_type=sea_fuel,
                bunker_port=bunker_port,
                port_fuel_type=port_fuel if port_fuel != sea_fuel else None,
            )

            # 적용 단가 안내
            if cost.fuel.leg_breakdowns:
                bd = cost.fuel.leg_breakdowns[0]
                sea_info = f"항해 {sea_fuel} ${bd.bunker_price:.1f}/톤"
                if bd.port_fuel_type and bd.port_fuel_type != sea_fuel:
                    port_info = f" + 정박 {bd.port_fuel_type} ${bd.port_bunker_price:.1f}/톤"
                else:
                    port_info = ""
                st.success(f"✅ 계산 완료 ({bunker_port} 공급, {sea_info}{port_info})")
            else:
                st.success("✅ 계산 완료")

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("연료비 (1척)", f"${cost.total_fuel_usd:,.0f}")
            with c2:
                st.metric("항비 (1척)", f"${cost.total_port_charge_usd:,.0f}")
            with c3:
                st.metric("용선료 (1척)", f"${cost.total_charter_usd:,.0f}")
            with c4:
                st.metric("총 (1척)", f"${cost.grand_total_usd:,.0f}")

            if ctx_info:
                ctx = ServiceContext(
                    service_code=proforma.service_code,
                    operation_type=ctx_info["op_type"],
                    total_vessels_in_service=ctx_info["total_vessels"],
                    vessel_capacity_teu_14t=ctx_info["capacity_14t"],
                    own_vessels_deployed=ctx_info["own_vessels"],
                    own_bsa_teu=ctx_info["bsa_teu"],
                    weight_basis_ton=ctx_info["weight_basis"],
                )
                own = cost.apply_service_context(ctx)

                st.subheader("🎯 자사 BSA 기준 분석")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("TEU당 단가", f"${own.per_teu_unit:,.0f}")
                with c2:
                    st.metric("자사 부담", f"${own.own_total_cost:,.0f}",
                              help="= BSA × 단가")
                with c3:
                    st.metric("임대 수익", f"${own.slot_lending_revenue:,.0f}",
                              help=f"잉여 {own.slot_balance_teu:+,.0f}TEU")
                with c4:
                    st.metric("순 운항원가", f"${own.net_voyage_cost:,.0f}",
                              help="자사부담 - 임대수익")

                # 대시보드 연계 버튼
                st.divider()
                st.markdown("### 🔗 다른 페이지에서 분석")
                st.caption(
                    "마법사에서 정한 값을 그대로 가져가서 시뮬레이션 변수(운임/유가/물량 등)만 조정할 수 있습니다."
                )

                col_d1, col_d2 = st.columns([1, 3])
                with col_d1:
                    if st.button("🚢 차터베이스 대시보드에서 분석", type="primary"):
                        # 대시보드용 자동 셋업 정보 저장
                        st.session_state.dashboard_autoload = {
                            "service_code": proforma.service_code,
                            "service_name": proforma.service_name,
                            "vessel_type": ctx_info["vessel_type"],
                            "total_vessels": ctx_info["total_vessels"],
                            "own_vessels": ctx_info["own_vessels"],
                            "bsa_teu": ctx_info["bsa_teu"],
                            "capacity_14t": ctx_info["capacity_14t"],
                            "weight_basis": ctx_info["weight_basis"],
                            "year": year,
                            "month": month,
                            "fuel_type": sea_fuel,
                            "port_fuel_type": port_fuel,
                            "bunker_port": bunker_port,
                            # 프로포마도 같이 (대시보드 캐시 주입용)
                            "proforma_legs_df": proforma.to_legs_dataframe(),
                        }
                        st.switch_page("dashboard.py")
                with col_d2:
                    st.caption(
                        f"✨ 대시보드로 자동 전달될 값:\n"
                        f"서비스 **{proforma.service_code}** / "
                        f"선형 **{ctx_info['vessel_type']}** / "
                        f"척수 **{ctx_info['own_vessels']}/{ctx_info['total_vessels']}** / "
                        f"BSA **{ctx_info['bsa_teu']:,.0f}TEU** / "
                        f"벙커링 **{bunker_port}** / 항해 **{sea_fuel}** + 정박 **{port_fuel}** / "
                        f"시점 **{year}-{month:02d}**"
                    )
        except Exception as e:
            st.error(f"계산 실패: {e}")
            import traceback
            with st.expander("상세 에러"):
                st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
