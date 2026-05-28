"""
선형 및 BSA 기반 동적 정박시간 계산기.

핵심 원칙:
- 정박시간(TML)은 하역 작업량에 비례
- 하역 작업량 = BSA × 평균 회전율 (in/out 합산 move)
- 정확한 산식: 작업량 ÷ (크레인 수 × 시간당 생산성)
- 데이터 부족 시 간이 산식 사용: 표준 TML × (BSA/기준BSA)

회사 정책 (단순 모델, 정확한 모델은 추후 확장):
- 기준 BSA = 1000TEU (이 기준에서 기존 평균 정박시간)
- 선형이 클수록 BSA가 크면 정박시간 비례 증가
- 단, 50% 감쇠율 적용 (실제로는 크레인 추가 등으로 100% 비례 안 함)
"""

from dataclasses import dataclass
from typing import Optional

from ..data_loaders import MasterDataManager
from .standard_assumptions import StandardValueExtractor


# 정박시간 스케일링 기준
REFERENCE_BSA_TEU = 1000        # 이 BSA에서 표준 TML 적용
SCALING_DAMPING = 0.5            # 50% 감쇠 (BSA 2배 → TML 1.5배)


@dataclass
class DwellTimeEstimate:
    """선형/BSA 기반 정박시간 추정 결과"""
    port: str
    base_minutes: int            # 기존 통계 평균 (BSA 무관)
    adjusted_minutes: int        # BSA 반영 후
    bsa_teu: float
    capacity_teu: float
    scaling_factor: float        # 적용된 배율
    sample_count: int            # 통계 샘플 수
    method: str                  # "scaled" / "default" / "manual"


class DwellTimeCalculator:
    """선형 및 BSA 기반 정박시간 계산기"""

    def __init__(self, data_manager: MasterDataManager,
                 reference_bsa: float = REFERENCE_BSA_TEU,
                 damping: float = SCALING_DAMPING):
        self.data = data_manager
        self.std_extractor = StandardValueExtractor(data_manager)
        self.reference_bsa = reference_bsa
        self.damping = damping

    def calculate_for_port(
        self,
        port: str,
        bsa_teu: float,
        capacity_teu: float,
        manual_override_min: Optional[int] = None,
    ) -> DwellTimeEstimate:
        """
        한 항구의 정박시간 추정.

        Parameters
        ----------
        port : 항구 코드 (예: "KRPUS")
        bsa_teu : 자사 BSA
        capacity_teu : 1척 선복 (14T 기준)
        manual_override_min : 수기 지정값 (있으면 그것 사용)
        """
        # 1) 기존 통계에서 기본 TML 추출
        base_min, sample_n = self.std_extractor.get_port_dwell_time(port)

        # 2) 수기 지정이면 그대로
        if manual_override_min is not None:
            return DwellTimeEstimate(
                port=port,
                base_minutes=base_min,
                adjusted_minutes=manual_override_min,
                bsa_teu=bsa_teu,
                capacity_teu=capacity_teu,
                scaling_factor=manual_override_min / base_min if base_min else 0,
                sample_count=sample_n,
                method="manual",
            )

        # 3) 스케일링 적용
        # scaling_factor = 1 + (bsa/ref - 1) × damping
        # 예: BSA 1000, ref 1000 → 1.0배
        # 예: BSA 2000, ref 1000, damping 0.5 → 1 + (2-1)*0.5 = 1.5배
        # 예: BSA 500, ref 1000, damping 0.5 → 1 + (0.5-1)*0.5 = 0.75배
        if self.reference_bsa > 0:
            ratio = bsa_teu / self.reference_bsa
            scaling = 1.0 + (ratio - 1.0) * self.damping
            scaling = max(0.5, min(scaling, 3.0))  # 0.5x ~ 3.0x 제한
        else:
            scaling = 1.0

        adjusted = int(round(base_min * scaling / 5) * 5)  # 5분 단위 반올림

        return DwellTimeEstimate(
            port=port,
            base_minutes=base_min,
            adjusted_minutes=adjusted,
            bsa_teu=bsa_teu,
            capacity_teu=capacity_teu,
            scaling_factor=scaling,
            sample_count=sample_n,
            method="scaled" if sample_n > 0 else "default",
        )

    def calculate_for_route(
        self,
        ports: list[str],
        bsa_teu: float,
        capacity_teu: float,
        manual_overrides: Optional[dict] = None,
    ) -> dict[str, DwellTimeEstimate]:
        """노선 전체의 항구별 정박시간 일괄 계산"""
        manual_overrides = manual_overrides or {}
        result = {}
        for port in ports:
            override = manual_overrides.get(port)
            result[port] = self.calculate_for_port(
                port, bsa_teu, capacity_teu, manual_override_min=override,
            )
        return result
