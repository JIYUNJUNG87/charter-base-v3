"""
선형 추천 분석 리포트.

입력:
  - 항로 (서비스 코드)
  - 후보 선형 리스트
  - 각 선형별 운항원가 결과

출력:
  - 추천 선형 (TEU당 원가 기준 + 추가 고려사항)
  - 선형별 비교표
  - 의사결정 근거
"""

from .base import BaseReportGenerator


VESSEL_RECOMMENDATION_PROMPT_KO = """당신은 해운 항로 선형 선정 전문가입니다.
아래 데이터를 보고 임원진에게 보고할 선형 추천 분석을 한국어 마크다운으로 작성하세요.

작성 원칙:
- 데이터에 있는 숫자만 사용
- 추천 선형을 명확히 제시
- TEU당 원가만이 아닌 절대금액·항로 특성도 고려
- 3~5단락

==== 데이터 ====
항로: {service_code}
항차 일수: {voyage_days:.1f}일
총 거리: {total_distance_nm:,.0f} NM

선형별 비교 ({n_vessels}개):
{vessel_comparison}

가장 효율적인 선형 (TEU당 원가 최저): {best_vessel}

리포트 구성:
## 🎯 추천
## 📊 비교 분석
## 💡 의사결정 근거
## ⚠️ 추가 고려사항
"""


class VesselRecommendationGenerator(BaseReportGenerator):
    """선형 추천 리포트 생성기"""

    def generate_from_comparison(self, service_code: str, voyage_days: float,
                                  total_distance_nm: float,
                                  vessel_results: list[dict]):
        """
        vessel_results: [
            {"type_name": str, "teu": int, "fuel": float, "port_charge": float,
             "charter": float, "total": float, "warnings": list},
            ...
        ]
        """
        data = {
            "service_code": service_code,
            "voyage_days": voyage_days,
            "total_distance_nm": total_distance_nm,
            "vessels": vessel_results,
        }
        return self.generate(data)

    def _build_vessel_comparison_text(self, vessels: list[dict]) -> str:
        """선형 비교를 텍스트 표로"""
        lines = []
        for v in vessels:
            per_teu = v["total"] / v["teu"] if v["teu"] else 0
            line = (f"  - {v['type_name']} ({v['teu']}TEU): "
                    f"총원가 ${v['total']:,.0f}, TEU당 ${per_teu:,.0f}, "
                    f"연료 ${v['fuel']:,.0f}, 항비 ${v['port_charge']:,.0f}, "
                    f"용선료 ${v['charter']:,.0f}")
            warnings = v.get("warnings", [])
            if warnings:
                line += f" [⚠️ {len(warnings)}건 경고]"
            lines.append(line)
        return "\n".join(lines)

    def _find_best_vessel(self, vessels: list[dict]) -> dict:
        """TEU당 원가가 가장 낮은 선형"""
        return min(vessels, key=lambda v: v["total"] / v["teu"] if v["teu"] else 1e18)

    def _build_prompt(self, data: dict) -> str:
        best = self._find_best_vessel(data["vessels"])
        return VESSEL_RECOMMENDATION_PROMPT_KO.format(
            service_code=data["service_code"],
            voyage_days=data["voyage_days"],
            total_distance_nm=data["total_distance_nm"],
            n_vessels=len(data["vessels"]),
            vessel_comparison=self._build_vessel_comparison_text(data["vessels"]),
            best_vessel=f"{best['type_name']} ({best['teu']}TEU)",
        )

    def _build_template(self, data: dict) -> str:
        """템플릿 기반 추천"""
        vessels = data["vessels"]
        if not vessels:
            return "선형 데이터가 없습니다."

        # 정렬
        sorted_vessels = sorted(vessels, key=lambda v: v["total"] / v["teu"] if v["teu"] else 1e18)
        best = sorted_vessels[0]
        worst = sorted_vessels[-1]

        best_per_teu = best["total"] / best["teu"]
        worst_per_teu = worst["total"] / worst["teu"]
        savings_pct = (worst_per_teu - best_per_teu) / worst_per_teu

        # 비교표 마크다운
        table_rows = []
        for i, v in enumerate(sorted_vessels):
            per_teu = v["total"] / v["teu"]
            marker = " 🏆" if i == 0 else ""
            table_rows.append(
                f"| {v['type_name']}{marker} | {v['teu']:,} | "
                f"${v['fuel']:,.0f} | ${v['port_charge']:,.0f} | "
                f"${v['charter']:,.0f} | ${v['total']:,.0f} | "
                f"**${per_teu:,.0f}** |"
            )

        # 절대금액 1위 (가장 싼 총원가)
        cheapest_total = min(sorted_vessels, key=lambda v: v["total"])
        # 가장 큰 선형
        largest = max(sorted_vessels, key=lambda v: v["teu"])

        # 비용 구성 분석 (best 기준)
        total = best["total"]
        fuel_pct = best["fuel"] / total * 100
        port_pct = best["port_charge"] / total * 100
        charter_pct = best["charter"] / total * 100

        report = f"""## 🎯 추천 선형

**{best['type_name']} ({best['teu']:,}TEU)** 를 추천합니다.

- **TEU당 운항원가**: ${best_per_teu:,.0f}
- **항차 총 운항원가**: ${best['total']:,.0f}
- 가장 비효율적인 선택 대비 **TEU당 {savings_pct:.1%} 절감**

## 📊 비교 분석

### 비교 ({len(vessels)}개 선형, {data['voyage_days']:.1f}일 항차 기준)

| 선형 | TEU | 연료비 | 항비 | 용선료 | 총원가 | TEU당 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table_rows)}

🏆 = 추천 선형 (TEU당 원가 기준)

### 핵심 지표 비교

- **TEU당 원가 1위**: {best['type_name']} (${best_per_teu:,.0f})
- **절대금액 최저**: {cheapest_total['type_name']} (${cheapest_total['total']:,.0f})
- **최대 선복량**: {largest['type_name']} ({largest['teu']:,}TEU)

## 💡 의사결정 근거

추천 선형의 운항원가 구성:
- **용선료** {charter_pct:.1f}% (${best['charter']:,.0f}) — 가장 큰 비중
- **연료비** {fuel_pct:.1f}% (${best['fuel']:,.0f})
- **항비** {port_pct:.1f}% (${best['port_charge']:,.0f})

용선료가 운항원가의 절반 이상을 차지하므로, **HRCI 지수가 안정적인 시기에 장기 용선 검토**가 가능하면 추가 절감 여지가 있습니다.

## ⚠️ 추가 고려사항

{self._build_considerations(vessels, best)}

---
*본 리포트는 시스템이 자동 생성한 템플릿 기반 분석입니다. Claude API 연동 시 보다 풍부한 해석이 제공됩니다.*
"""
        return report

    def _build_considerations(self, vessels: list[dict], best: dict) -> str:
        """추가 고려사항"""
        items = []

        # 경고 있는 선형 체크
        warned = [v for v in vessels if v.get("warnings")]
        if warned:
            items.append(
                f"- **데이터 경고 보유 선형**: {len(warned)}개 선형이 데이터 폴백을 사용 중. "
                f"PORT_CHARGE 데이터 추가 확보 시 정확도 개선 가능."
            )

        # 큰 선형 (5000TEU 초과)이 포함되어 있는지
        big_vessels = [v for v in vessels if v["teu"] > 5000]
        if big_vessels:
            items.append(
                f"- **대형 선형 검토 시 주의**: 5,000TEU 초과 선형은 PORT_CHARGE 데이터 부재로 "
                f"CA15 폴백 적용. 실제 항비는 더 클 가능성 있음."
            )

        # 적재율 영향
        items.append(
            "- **소석률 가정 확인 필요**: 본 분석은 항로 운항원가만 산출. "
            "실제 수익성은 소석률·운임 수준에 따라 달라짐."
        )

        # 항로별 선박 입항 제약
        items.append(
            "- **항만 입항 제약 점검**: 기항 항구의 LOA/Beam/Draft 제약과 선형 호환성 확인 필요."
        )

        return "\n".join(items)
