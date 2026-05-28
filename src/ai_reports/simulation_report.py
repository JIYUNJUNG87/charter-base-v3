"""
시뮬레이션 요약 리포트 생성기.

입력:
  - 차터베이스 baseline (시뮬레이션 전)
  - 시뮬레이션 결과
  - 시나리오 정보

출력 (마크다운):
  ## 요약
  ## 주요 변화
  ## 리스크 및 대응방안
  ## 의사결정 권고
"""

from .base import BaseReportGenerator


REPORT_PROMPT_KO = """당신은 해운/항공 항로 수지 분석 전문가입니다.
아래 시뮬레이션 결과를 보고 임원진 보고용 분석 리포트를 한국어 마크다운으로 작성하세요.

작성 원칙:
- 데이터에 명시된 숫자만 사용 (추정/창작 금지)
- 임원 보고용 톤 (간결, 단정, 핵심 위주)
- 3~5단락 분량
- 한국 해운업계 표현 사용 (운항이익, 한계이익, 소석률 등)
- 절대로 데이터에 없는 추가 정보를 만들어내지 마세요

리포트 구성:
## 📋 요약 (3줄 이내)
- 변화의 본질과 결론

## 📊 주요 변화
- 어떤 변수가 어떻게 바뀌었고, 그 결과 P&L이 어떻게 영향받는지

## ⚠️ 리스크
- 이 시나리오가 현실화될 경우의 리스크

## 💡 의사결정 권고
- 구체적 액션 아이템 (2~3개)

==== 데이터 ====
항로: {service_code}
선형: {vessel_type}
시나리오:
{scenario_text}

베이스라인 P&L (USD):
- 매출: {base_revenue:,.0f}
- 한계이익: {base_contribution:,.0f}
- 운항이익: {base_voyage_profit:,.0f}
- 영업이익률: {base_margin:.1%}

시뮬레이션 결과:
- 매출: {sim_revenue:,.0f} ({rev_change:+,.0f}, {rev_pct:+.1%})
- 한계이익: {sim_contribution:,.0f} ({cont_change:+,.0f})
- 운항이익: {sim_voyage_profit:,.0f} ({voy_change:+,.0f})
- 영업이익률: {sim_margin:.1%}

방향별 운항이익:
- E (현재→시뮬): {base_east_profit:,.0f} → {sim_east_profit:,.0f}
- W (현재→시뮬): {base_west_profit:,.0f} → {sim_west_profit:,.0f}
"""


class SimulationReportGenerator(BaseReportGenerator):
    """시뮬레이션 결과 리포트"""

    def generate_from_result(self, baseline, simulated, scenario,
                             service_code: str, vessel_type: str):
        """시뮬레이션 객체에서 직접 데이터 추출"""
        data = self._extract_data(baseline, simulated, scenario,
                                   service_code, vessel_type)
        return self.generate(data)

    def _extract_data(self, baseline, simulated, scenario,
                      service_code: str, vessel_type: str) -> dict:
        return {
            "service_code": service_code,
            "vessel_type": vessel_type,
            "scenario": {
                "freight_change_e": scenario.freight_change_e,
                "freight_change_w": scenario.freight_change_w,
                "fuel_price_change": scenario.fuel_price_change,
                "volume_change_e": scenario.volume_change_e,
                "volume_change_w": scenario.volume_change_w,
            },
            "baseline": {
                "total_revenue": baseline.total_revenue,
                "total_contribution_margin": baseline.total_contribution_margin,
                "total_voyage_profit": baseline.total_voyage_profit,
                "east_voyage_profit": baseline.east.voyage_profit,
                "west_voyage_profit": baseline.west.voyage_profit,
                "margin": (baseline.total_voyage_profit / baseline.total_revenue
                           if baseline.total_revenue else 0),
            },
            "simulated": {
                "total_revenue": simulated.total_revenue,
                "total_contribution_margin": simulated.total_contribution_margin,
                "total_voyage_profit": simulated.total_voyage_profit,
                "east_voyage_profit": simulated.east.voyage_profit,
                "west_voyage_profit": simulated.west.voyage_profit,
                "margin": (simulated.total_voyage_profit / simulated.total_revenue
                           if simulated.total_revenue else 0),
            },
        }

    def _scenario_to_text(self, scenario: dict) -> str:
        """시나리오 dict를 사람이 읽을 수 있는 텍스트로"""
        lines = []
        if scenario.get("freight_change_e", 0) or scenario.get("freight_change_w", 0):
            fe = scenario.get("freight_change_e", 0)
            fw = scenario.get("freight_change_w", 0)
            if fe == fw and fe != 0:
                lines.append(f"- 운임 변동: {fe:+.0%} (양방향)")
            else:
                if fe:
                    lines.append(f"- E 운임 변동: {fe:+.0%}")
                if fw:
                    lines.append(f"- W 운임 변동: {fw:+.0%}")
        if scenario.get("fuel_price_change", 0):
            lines.append(f"- 유가 변동: {scenario['fuel_price_change']:+.0%}")
        if scenario.get("volume_change_e", 0) or scenario.get("volume_change_w", 0):
            ve = scenario.get("volume_change_e", 0)
            vw = scenario.get("volume_change_w", 0)
            if ve == vw and ve != 0:
                lines.append(f"- 선적량 변동: {ve:+.0%} (양방향)")
            else:
                if ve:
                    lines.append(f"- E 선적량 변동: {ve:+.0%}")
                if vw:
                    lines.append(f"- W 선적량 변동: {vw:+.0%}")

        return "\n".join(lines) if lines else "- 변동 없음 (현재 상태)"

    def _build_prompt(self, data: dict) -> str:
        """Claude API 프롬프트"""
        b = data["baseline"]
        s = data["simulated"]
        return REPORT_PROMPT_KO.format(
            service_code=data["service_code"],
            vessel_type=data["vessel_type"],
            scenario_text=self._scenario_to_text(data["scenario"]),
            base_revenue=b["total_revenue"],
            base_contribution=b["total_contribution_margin"],
            base_voyage_profit=b["total_voyage_profit"],
            base_margin=b["margin"],
            sim_revenue=s["total_revenue"],
            sim_contribution=s["total_contribution_margin"],
            sim_voyage_profit=s["total_voyage_profit"],
            sim_margin=s["margin"],
            rev_change=s["total_revenue"] - b["total_revenue"],
            rev_pct=((s["total_revenue"] - b["total_revenue"]) / b["total_revenue"]
                     if b["total_revenue"] else 0),
            cont_change=s["total_contribution_margin"] - b["total_contribution_margin"],
            voy_change=s["total_voyage_profit"] - b["total_voyage_profit"],
            base_east_profit=b["east_voyage_profit"],
            base_west_profit=b["west_voyage_profit"],
            sim_east_profit=s["east_voyage_profit"],
            sim_west_profit=s["west_voyage_profit"],
        )

    def _build_template(self, data: dict) -> str:
        """템플릿 기반 리포트 (API 없을 때)"""
        b = data["baseline"]
        s = data["simulated"]

        rev_change = s["total_revenue"] - b["total_revenue"]
        voy_change = s["total_voyage_profit"] - b["total_voyage_profit"]
        cont_change = s["total_contribution_margin"] - b["total_contribution_margin"]
        rev_pct = (rev_change / b["total_revenue"]) if b["total_revenue"] else 0
        voy_pct = (voy_change / abs(b["total_voyage_profit"])
                   if b["total_voyage_profit"] else 0)

        # 시나리오 해석
        scenario_text = self._scenario_to_text(data["scenario"])
        direction = "개선" if voy_change > 0 else "악화"
        magnitude = abs(voy_change)
        if magnitude < 100_000:
            mag_label = "소폭"
        elif magnitude < 1_000_000:
            mag_label = "유의미한 수준으로"
        else:
            mag_label = "크게"

        # 한계이익률 (변동비 통제 영역)
        base_cm_ratio = (b["total_contribution_margin"] / b["total_revenue"]
                         if b["total_revenue"] else 0)
        sim_cm_ratio = (s["total_contribution_margin"] / s["total_revenue"]
                        if s["total_revenue"] else 0)

        # 주요 변동 변수
        s_data = data["scenario"]
        active_vars = []
        if s_data.get("freight_change_e", 0) or s_data.get("freight_change_w", 0):
            active_vars.append("운임")
        if s_data.get("fuel_price_change", 0):
            active_vars.append("유가")
        if s_data.get("volume_change_e", 0) or s_data.get("volume_change_w", 0):
            active_vars.append("선적량")
        active_vars_text = " · ".join(active_vars) if active_vars else "변동 없음"

        report = f"""## 📋 요약

**{data['service_code']}** 항로에 **{data['vessel_type']}** 선형 투입 기준, {active_vars_text} 시나리오 적용 결과 운항이익이 **${voy_change:+,.0f}** ({voy_pct:+.1%}) {mag_label} {direction}됩니다.

영업이익률은 **{b['margin']:.1%}** 에서 **{s['margin']:.1%}**로 변동하며, 한계이익률도 {base_cm_ratio:.1%} → {sim_cm_ratio:.1%}로 변화합니다.

## 📊 주요 변화

### 시나리오
{scenario_text}

### P&L 영향
| 항목 | 베이스라인 | 시뮬레이션 | 변화 |
|---|---:|---:|---:|
| 매출 | ${b['total_revenue']:,.0f} | ${s['total_revenue']:,.0f} | ${rev_change:+,.0f} ({rev_pct:+.1%}) |
| 한계이익 | ${b['total_contribution_margin']:,.0f} | ${s['total_contribution_margin']:,.0f} | ${cont_change:+,.0f} |
| 운항이익 | ${b['total_voyage_profit']:,.0f} | ${s['total_voyage_profit']:,.0f} | ${voy_change:+,.0f} |

### 방향별
- **E 방향**: ${b['east_voyage_profit']:,.0f} → ${s['east_voyage_profit']:,.0f} (${s['east_voyage_profit'] - b['east_voyage_profit']:+,.0f})
- **W 방향**: ${b['west_voyage_profit']:,.0f} → ${s['west_voyage_profit']:,.0f} (${s['west_voyage_profit'] - b['west_voyage_profit']:+,.0f})

## ⚠️ 리스크 및 검토 사항

{self._build_risk_section(data)}

## 💡 의사결정 권고

{self._build_recommendation_section(data, voy_change)}

---
*본 리포트는 시스템이 자동 생성한 템플릿 기반 분석입니다. Claude API 연동 시 보다 풍부한 해석이 제공됩니다.*
"""
        return report

    def _build_risk_section(self, data: dict) -> str:
        """리스크 섹션 (시나리오별 자동 분석)"""
        s = data["scenario"]
        risks = []

        # 유가 리스크
        if s.get("fuel_price_change", 0) >= 0.10:
            risks.append(
                f"- **유가 상승 리스크**: 유가 {s['fuel_price_change']:+.0%} 시나리오는 "
                f"BAF(유류할증료) 회수가 충분하지 않으면 직접적 손익 악화로 이어짐"
            )
        elif s.get("fuel_price_change", 0) <= -0.10:
            risks.append(
                f"- **유가 하락 시 BAF 인하 압력**: 화주의 BAF 인하 요구 가능성 존재"
            )

        # 운임 리스크
        if s.get("freight_change_e", 0) <= -0.10 or s.get("freight_change_w", 0) <= -0.10:
            risks.append(
                "- **운임 하락 리스크**: 경쟁사 가격 정책 또는 시장 침체 가능성 점검 필요"
            )

        # 선적량 리스크
        if s.get("volume_change_e", 0) <= -0.10 or s.get("volume_change_w", 0) <= -0.10:
            risks.append(
                "- **선적량 감소 리스크**: 소석률 저하 시 운항원가 분담 부담 증가"
            )

        # 운항이익이 음수인 경우
        if data["simulated"]["total_voyage_profit"] < 0:
            risks.append(
                f"- **적자 항로 경고**: 시뮬레이션 결과 운항이익이 적자 "
                f"(${data['simulated']['total_voyage_profit']:,.0f})로 유지·구조조정 검토 필요"
            )

        if not risks:
            risks.append("- 현재 시나리오는 안정적 범위에서 작동")

        return "\n".join(risks)

    def _build_recommendation_section(self, data: dict, voy_change: float) -> str:
        """권고 섹션"""
        recs = []
        s = data["scenario"]

        if voy_change < -500_000:
            recs.append(
                "**선형 변경 검토**: 동일 항로에 다른 선형 투입 시 운항원가 시뮬레이션 수행"
            )
            recs.append(
                "**운임 인상 협의**: 화주와의 운임 협상 또는 BAF 재산정 필요"
            )

        elif voy_change > 500_000:
            recs.append("**수익성 개선 기회 활용**: 마케팅·영업 강화로 효과 극대화")
            recs.append("**추가 항차 검토**: 수요 대비 공급 확대 가능성 분석")

        if s.get("fuel_price_change", 0) >= 0.15:
            recs.append("**벙커 헷지 검토**: 단기 유가 변동성 대응을 위한 헷지 전략 검토")

        if data["simulated"]["east_voyage_profit"] < 0 and data["simulated"]["west_voyage_profit"] > 0:
            recs.append("**E방향 수익성 개선**: 단방향 적자 해소를 위한 영업 강화")
        elif data["simulated"]["west_voyage_profit"] < 0 and data["simulated"]["east_voyage_profit"] > 0:
            recs.append("**W방향 수익성 개선**: 단방향 적자 해소를 위한 영업 강화")

        if not recs:
            recs.append("현 운영 기조 유지 + 정기 모니터링")

        # 자동 번호 매기기 (1부터 시작)
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs))
