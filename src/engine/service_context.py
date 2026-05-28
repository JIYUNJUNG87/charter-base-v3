"""
서비스 운영 컨텍스트 모델.

컨테이너 정기 서비스의 실제 운영 형태를 표현:
- 공동운항(Slot Sharing/Alliance) 구조
- BSA(Berth Slot Allocation) - 자사가 사용하는 선복 한도
- 자사 투입 선박 척수 vs 사용 BSA 차이로 인한 선복 임대/임차

3가지 운영 형태:
  1. owned        : 자사 단독 운항 (거의 없음)
  2. shared       : 공동운항 + 자사 선박 일부 투입 (가장 일반적)
  3. charter_only : 자사 선박 없이 BSA만 임차 (Slot Charter)
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


OperationType = Literal["owned", "shared", "charter_only"]


# 정기 서비스 운영 표준: 7일에 1척
DAYS_PER_VESSEL = 7

# 컨테이너 무게 기준 표준값
DEFAULT_WEIGHT_BASIS_TON = 14.0
WEIGHT_BASIS_OPTIONS = [12.0, 13.5, 14.0]  # 항로별로 다를 수 있음


@dataclass
class ServiceContext:
    """
    한 서비스의 운영 컨텍스트.

    예시 (ANX 서비스, 자사 4척 투입, BSA 666TEU):
        ServiceContext(
            service_code="ANX",
            operation_type="shared",
            total_vessels_in_service=6,    # 공동운항 총 6척
            vessel_capacity_teu_14t=4000,  # 4250 디자인 ≈ 4000 (14T)
            own_vessels_deployed=4,        # 자사 4척
            own_bsa_teu=666,               # BSA 666TEU
            weight_basis_ton=14.0,
        )
    """
    service_code: str
    operation_type: OperationType = "shared"

    # 서비스 전체 정보
    total_vessels_in_service: int = 1       # 공동운항 총 선박 수
    vessel_capacity_teu_14t: float = 0.0    # 투입 선형의 14TON 기준 선복

    # 자사 투입
    own_vessels_deployed: int = 1            # 자사가 투입한 척수

    # 자사 BSA (수기 조정 가능)
    # None이면 자동 계산: own_vessels × capacity / total_vessels
    own_bsa_teu: Optional[float] = None

    # 컨테이너 무게 기준
    weight_basis_ton: float = DEFAULT_WEIGHT_BASIS_TON

    # 운항 일수 (서비스 한 항차)
    voyage_days: float = 0.0

    # ===== 자동 계산 프로퍼티 =====
    @property
    def total_service_capacity_teu(self) -> float:
        """서비스 전체 선복 = 총 척수 × 1척 선복"""
        return self.total_vessels_in_service * self.vessel_capacity_teu_14t

    @property
    def own_vessel_capacity_provided_teu(self) -> float:
        """자사가 제공하는 선복 = 자사 척수 × 1척 선복"""
        return self.own_vessels_deployed * self.vessel_capacity_teu_14t

    @property
    def auto_bsa_teu(self) -> float:
        """
        자동 산정 BSA.
        공식: 1척_선복 × (자사_척수 / 총_척수)

        예: 6척 공동운항에 4000TEU 1척 투입
            → BSA = 4000 × (1/6) = 666TEU (자사 1척 제공)
            → BSA = 4000 × (4/6) = 2667TEU (자사 4척 제공)

        이는 모든 선박을 공동 사용하는 지분 공유(slot-sharing) 모델 기준.
        각 선사가 본인 배만 사용하는 단순 모델은 BSA 수기 조정 필요.
        """
        if self.total_vessels_in_service == 0:
            return 0.0
        return self.vessel_capacity_teu_14t * (
            self.own_vessels_deployed / self.total_vessels_in_service
        )

    @property
    def effective_bsa_teu(self) -> float:
        """실제 사용할 BSA. 수기 설정이 있으면 그것, 없으면 자동값."""
        if self.own_bsa_teu is not None:
            return self.own_bsa_teu
        return self.auto_bsa_teu

    @property
    def own_share_ratio(self) -> float:
        """자사 BSA 지분율 = 자사 BSA / 서비스 전체 선복"""
        total = self.total_service_capacity_teu
        if total == 0:
            return 0.0
        return self.effective_bsa_teu / total

    @property
    def slot_balance_teu(self) -> float:
        """
        선복 수지 = 자사 제공 선복 - 자사 BSA
        양수: 잉여 → 선복 임대 수익
        음수: 부족 → 선복 임차 비용
        """
        if self.operation_type == "charter_only":
            # 자사 배 없이 BSA만 임차 → 전체가 임차
            return -self.effective_bsa_teu
        return self.own_vessel_capacity_provided_teu - self.effective_bsa_teu

    @property
    def slot_position(self) -> str:
        """선복 포지션 라벨"""
        bal = self.slot_balance_teu
        if bal > 0:
            return "lender"      # 임대 (수익)
        elif bal < 0:
            return "renter"      # 임차 (비용)
        return "balanced"        # 균형

    # ===== 정기 서비스 검증 =====
    @property
    def expected_voyage_days(self) -> float:
        """이론적 항차 일수 = 총 척수 × 7일"""
        return self.total_vessels_in_service * DAYS_PER_VESSEL

    def validate_voyage_days(self, actual_voyage_days: float, tolerance_hours: float = 12) -> dict:
        """
        실제 항차 일수와 7일 배수 기준이 맞는지 검증.
        Returns: {"valid": bool, "expected": float, "actual": float, "diff_hours": float}
        """
        expected_hours = self.expected_voyage_days * 24
        actual_hours = actual_voyage_days * 24
        diff_hours = actual_hours - expected_hours
        return {
            "valid": abs(diff_hours) <= tolerance_hours,
            "expected_days": self.expected_voyage_days,
            "actual_days": actual_voyage_days,
            "diff_hours": diff_hours,
            "needs_adjustment_hours": -diff_hours,  # 양수: 늘려야, 음수: 줄여야
        }

    # ===== 자사 단가 계산 =====
    def own_per_teu_cost(self, fuel_cost: float, port_charge: float,
                         charter_hire: float) -> dict:
        """
        TEU당 운항원가 단가 계산.

        핵심 원칙 (회사 정책):
        - 단가는 **1척 운항원가 / 1척 전체 선복(14T)** 으로 계산
        - BSA는 그 단가 × 자사 사용량/잉여량 계산에만 사용

        예시 (1척 운항원가 $2,544,478, 1척 선복 4000TEU, 자사 BSA 666):
            TEU당 단가 = 2,544,478 / 4000 = $636/TEU
            자사 운항원가 = 666 × $636 = $423,576
            잉여 선복 (3334) → 임대 수익 = 3334 × $636 = $2,120,902

        Parameters
        ----------
        fuel_cost, port_charge, charter_hire : 1척 1항차 기준
        """
        total_per_vessel = fuel_cost + port_charge + charter_hire

        # 단가는 1척 전체 선복 기준
        capacity = self.vessel_capacity_teu_14t
        if capacity == 0:
            return {
                "per_teu_unit": 0,
                "per_vessel_total": total_per_vessel,
                "own_total_cost": 0,
            }

        per_teu = total_per_vessel / capacity

        # 자사 부담 운항원가 = BSA × 단가
        # (척수가 아닌 BSA 기준이라는 점 주의 - 회사 정책)
        own_cost = self.effective_bsa_teu * per_teu

        return {
            "per_vessel_total": total_per_vessel,
            "per_teu_unit": per_teu,             # 1척 운항원가 / 1척 선복
            "own_total_cost": own_cost,          # BSA × 단가
            # 항목별 단가 (참고용)
            "fuel_per_teu": fuel_cost / capacity,
            "port_per_teu": port_charge / capacity,
            "charter_per_teu": charter_hire / capacity,
        }

    def slot_lending_revenue(self, fuel_cost: float, port_charge: float,
                              charter_hire: float, lending_rate: Optional[float] = None) -> float:
        """
        잉여 선복 임대 수익.
        단가 미지정 시 자체 per_teu_unit (1척 운항원가/1척 선복) 사용.
        """
        if self.slot_balance_teu <= 0:
            return 0.0
        rate = lending_rate
        if rate is None:
            rate = self.own_per_teu_cost(fuel_cost, port_charge, charter_hire)["per_teu_unit"]
        return self.slot_balance_teu * rate

    def slot_charter_cost(self, fuel_cost: float, port_charge: float,
                          charter_hire: float, charter_rate: Optional[float] = None) -> float:
        """
        부족 선복 임차 비용.
        단가 미지정 시 자체 per_teu_unit 사용.
        """
        if self.slot_balance_teu >= 0:
            return 0.0
        shortage = abs(self.slot_balance_teu)
        rate = charter_rate
        if rate is None:
            rate = self.own_per_teu_cost(fuel_cost, port_charge, charter_hire)["per_teu_unit"]
        return shortage * rate

    # ===== 직렬화 / 요약 =====
    def to_dict(self) -> dict:
        return {
            "service_code": self.service_code,
            "operation_type": self.operation_type,
            "total_vessels_in_service": self.total_vessels_in_service,
            "vessel_capacity_teu_14t": self.vessel_capacity_teu_14t,
            "own_vessels_deployed": self.own_vessels_deployed,
            "own_bsa_teu": self.own_bsa_teu,
            "effective_bsa_teu": self.effective_bsa_teu,
            "auto_bsa_teu": self.auto_bsa_teu,
            "weight_basis_ton": self.weight_basis_ton,
            "voyage_days": self.voyage_days,
            "total_service_capacity_teu": self.total_service_capacity_teu,
            "own_vessel_capacity_provided_teu": self.own_vessel_capacity_provided_teu,
            "own_share_ratio": self.own_share_ratio,
            "slot_balance_teu": self.slot_balance_teu,
            "slot_position": self.slot_position,
            "expected_voyage_days": self.expected_voyage_days,
        }

    def summary(self) -> str:
        """사람이 읽기 좋은 요약 텍스트"""
        lines = [
            f"=== {self.service_code} 운영 컨텍스트 ===",
            f"운영 형태: {self.operation_type}",
            f"서비스 총 선박: {self.total_vessels_in_service}척 × "
            f"{self.vessel_capacity_teu_14t:,.0f}TEU(14T) = "
            f"{self.total_service_capacity_teu:,.0f}TEU",
            f"자사 투입: {self.own_vessels_deployed}척 "
            f"({self.own_vessel_capacity_provided_teu:,.0f}TEU 제공)",
            f"자사 BSA: {self.effective_bsa_teu:,.0f}TEU "
            f"(지분 {self.own_share_ratio:.1%})",
            f"선복 수지: {self.slot_balance_teu:+,.0f}TEU ({self.slot_position})",
            f"이론 항차일수: {self.expected_voyage_days}일 "
            f"(= {self.total_vessels_in_service}척 × {DAYS_PER_VESSEL}일)",
        ]
        if self.own_bsa_teu is not None:
            lines.append(f"  ※ BSA 수기 조정 적용 (자동값: {self.auto_bsa_teu:,.0f}TEU)")
        return "\n".join(lines)


# ============================================================
# 헬퍼: 선형 스펙에서 ServiceContext 기본값 생성
# ============================================================
def create_service_context_from_vessel(
    service_code: str,
    vessel_spec_info: dict,
    total_vessels: int,
    own_vessels: int,
    bsa_override: Optional[float] = None,
    operation_type: OperationType = "shared",
    weight_basis_ton: float = DEFAULT_WEIGHT_BASIS_TON,
) -> ServiceContext:
    """
    VesselSpecLoader.get_type_info() 결과를 받아서 ServiceContext 생성.
    선복은 14TON 기준 우선 사용, 없으면 디자인 TEU 사용.
    """
    teu_14t = vessel_spec_info.get("teu_at_14t")
    if teu_14t is None or teu_14t == 0:
        # 14TON 기준 데이터 없으면 디자인 TEU 사용 + 경고는 호출자가 처리
        teu_14t = vessel_spec_info.get("teu_nominal", 0)

    return ServiceContext(
        service_code=service_code,
        operation_type=operation_type,
        total_vessels_in_service=total_vessels,
        vessel_capacity_teu_14t=float(teu_14t),
        own_vessels_deployed=own_vessels,
        own_bsa_teu=bsa_override,
        weight_basis_ton=weight_basis_ton,
    )
