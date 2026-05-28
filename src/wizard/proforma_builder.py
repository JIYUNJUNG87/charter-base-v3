"""
프로포마 빌더.

신규 항로의 프로포마 스케줄을 자동 생성.

3가지 방식:
1. from_scratch: 기항지 순서만 받아서 완전 자동 생성
2. from_template: 기존 서비스를 복제해서 일부 수정
3. manual: 사용자가 각 구간 직접 입력 (UI에서 처리)

추가 기능 (5단계):
- target_voyage_days 지정 시 버퍼 자동 조정으로 7일 배수 정확히 맞춤
- 선형 + BSA 기반 동적 정박시간 적용 (4단계)

생성된 프로포마는 기존 ServiceScheduleLoader가 반환하는 것과
동일한 형식의 DataFrame이라, 운항원가 계산기에 바로 넣을 수 있음.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager
from .distance_matrix import DistanceMatrix, DistanceLookupResult
from .standard_assumptions import (
    StandardValueExtractor, StandardAssumptions, DEFAULT_STANDARDS,
)
from .dwell_time_calculator import DwellTimeCalculator


@dataclass
class ProformaLeg:
    """프로포마 한 구간"""
    seq: int
    from_port: str
    to_port: str
    bnd: str = "E"                  # 방향 (E/W)
    distance_nm: float = 0.0
    speed_knot: float = 15.0
    tb_manv_min: int = 60
    td_manv_min: int = 60
    tml_min: int = 720             # 도착항 정박시간
    sea_buff_min: int = 120
    distance_source: str = ""      # "matrix", "manual", "missing"
    distance_warning: str = ""     # 거리 데이터 이슈가 있을 때

    @property
    def sea_time_min(self) -> int:
        """항해시간 = 거리 / 선속 (분 단위)"""
        if self.speed_knot <= 0:
            return 0
        return int(round(self.distance_nm / self.speed_knot * 60))

    @property
    def total_time_min(self) -> int:
        """구간 총 시간"""
        return (self.sea_time_min + self.tml_min + self.tb_manv_min
                + self.td_manv_min + self.sea_buff_min)

    def to_dict(self) -> dict:
        """ServiceScheduleLoader 형식과 호환되는 dict"""
        return {
            "seq": self.seq,
            "from_port": self.from_port,
            "to_port": self.to_port,
            "wharf": "",
            "bnd": self.bnd,
            "eta": "",
            "tb_manv": self._fmt_time(self.tb_manv_min),
            "etb": "",
            "etb_day": "",
            "td_manv": self._fmt_time(self.td_manv_min),
            "tml": self._fmt_time(self.tml_min),
            "etd": "",
            "etd_day": "",
            "distance_nm": self.distance_nm,
            "speed_knot": self.speed_knot,
            "sea_time": self._fmt_time(self.sea_time_min),
            "diff": "000:00",
            "sea_buff": self._fmt_time(self.sea_buff_min),
            "total_time": self._fmt_time(self.total_time_min),
            # 분 단위 컬럼 (계산기 호환)
            "tb_manv_min": self.tb_manv_min,
            "td_manv_min": self.td_manv_min,
            "tml_min": self.tml_min,
            "sea_time_min": self.sea_time_min,
            "sea_buff_min": self.sea_buff_min,
            "total_time_min": self.total_time_min,
        }

    @staticmethod
    def _fmt_time(minutes: int) -> str:
        """분 → 'HHH:MM' 형식"""
        if minutes < 0:
            return f"-{abs(minutes) // 60:03d}:{abs(minutes) % 60:02d}"
        return f"{minutes // 60:03d}:{minutes % 60:02d}"


@dataclass
class Proforma:
    """완성된 프로포마"""
    service_code: str
    service_name: str
    legs: list[ProformaLeg] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    standards_used: Optional[StandardAssumptions] = None

    @property
    def total_distance_nm(self) -> float:
        return sum(leg.distance_nm for leg in self.legs)

    @property
    def total_time_hours(self) -> float:
        return sum(leg.total_time_min for leg in self.legs) / 60

    @property
    def port_sequence(self) -> list[str]:
        if not self.legs:
            return []
        return [self.legs[0].from_port] + [leg.to_port for leg in self.legs]

    def to_legs_dataframe(self) -> pd.DataFrame:
        """ServiceScheduleLoader.get_legs() 와 호환되는 DataFrame"""
        rows = [leg.to_dict() for leg in self.legs]
        df = pd.DataFrame(rows)
        df["service_code"] = self.service_code
        return df

    def summary(self) -> dict:
        return {
            "service_code": self.service_code,
            "service_name": self.service_name,
            "leg_count": len(self.legs),
            "total_distance_nm": self.total_distance_nm,
            "total_time_hours": self.total_time_hours,
            "total_time_days": self.total_time_hours / 24,
            "port_sequence": self.port_sequence,
            "warnings": self.warnings,
        }


class ProformaBuilder:
    """프로포마 빌더"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager
        self.distance_matrix = DistanceMatrix(data_manager)
        self.std_extractor = StandardValueExtractor(data_manager)
        self.dwell_calculator = DwellTimeCalculator(data_manager)

    # ================================================================
    # 방식 1: 처음부터 만들기 (From Scratch)
    # ================================================================
    def build_from_scratch(
        self,
        service_code: str,
        service_name: str,
        port_sequence: list[str],
        direction_pattern: str = "auto",  # "auto", "ew", "sn", "manual"
        leg_directions: Optional[list[str]] = None,  # direction_pattern="manual"일 때 사용
        speed_knot: float = None,
        manual_distances: dict = None,
        manual_dwell_times: dict = None,
        # 5단계 추가
        bsa_teu: Optional[float] = None,
        capacity_teu_14t: Optional[float] = None,
        target_voyage_days: Optional[float] = None,
    ) -> Proforma:
        """
        기항지 순서만 받아서 자동으로 프로포마 생성.

        Parameters
        ----------
        port_sequence : 기항지 순서 (예: ["KRPUS", "CNSHA", "VNSGN", "KRPUS"])
        direction_pattern : 방향 자동 할당 방식
            - "auto" / "ew": 수출/수입 룰 (KR→외국=W, 외국→KR=E)
            - "sn": 전반=S, 후반=N
            - "manual": leg_directions로 직접 지정 (각 leg의 바운드)
        leg_directions : direction_pattern="manual"일 때 각 leg의 바운드 (S/N/E/W).
            len(leg_directions) == len(port_sequence) - 1 이어야 함.
        speed_knot : 표준 선속 (None이면 데이터에서 추출한 추천값 사용)
        manual_distances : {(from, to): distance} 형태의 수동 거리 입력
        manual_dwell_times : {port: minutes} 형태의 수동 정박시간 입력
        bsa_teu : 자사 BSA (정박시간 스케일링용)
        capacity_teu_14t : 1척 선복 (BSA 기반 계산용)
        target_voyage_days : 목표 항차 일수 (7일 배수). 지정 시 버퍼 자동 조정.
        """
        if len(port_sequence) < 2:
            raise ValueError("최소 2개 이상의 기항지가 필요합니다")

        # manual 모드 검증
        if direction_pattern == "manual":
            expected_n = len(port_sequence) - 1
            if not leg_directions or len(leg_directions) != expected_n:
                raise ValueError(
                    f"direction_pattern='manual'일 때 leg_directions는 "
                    f"{expected_n}개여야 합니다 (받은 값: {len(leg_directions) if leg_directions else 0}개)"
                )

        std = self.std_extractor.suggest_assumptions()
        if speed_knot is not None:
            std.speed_knot = speed_knot

        proforma = Proforma(
            service_code=service_code,
            service_name=service_name,
            standards_used=std,
        )

        manual_distances = manual_distances or {}
        manual_dwell_times = manual_dwell_times or {}

        n_legs = len(port_sequence) - 1
        midpoint = n_legs // 2

        # 각 leg 생성
        for i in range(n_legs):
            fp = port_sequence[i]
            tp = port_sequence[i + 1]
            seq = i + 1

            distance, dist_source, dist_warning = self._resolve_distance(
                fp, tp, manual_distances,
            )

            # 정박시간: BSA 기반 또는 기존 표준값
            if bsa_teu and capacity_teu_14t:
                est = self.dwell_calculator.calculate_for_port(
                    tp, bsa_teu, capacity_teu_14t,
                    manual_override_min=manual_dwell_times.get(tp),
                )
                dwell_min = est.adjusted_minutes
            else:
                dwell_min = self._resolve_dwell_time(tp, manual_dwell_times)

            bnd = self._assign_direction(
                i, n_legs, midpoint, direction_pattern,
                port_sequence=port_sequence,
                leg_directions=leg_directions,
            )

            leg = ProformaLeg(
                seq=seq, from_port=fp, to_port=tp, bnd=bnd,
                distance_nm=distance, speed_knot=std.speed_knot,
                tb_manv_min=std.tb_manv_minutes,
                td_manv_min=std.td_manv_minutes,
                tml_min=dwell_min,
                sea_buff_min=std.sea_buff_minutes,
                distance_source=dist_source,
                distance_warning=dist_warning,
            )
            proforma.legs.append(leg)

            if distance == 0:
                proforma.warnings.append(
                    f"구간 {seq} ({fp}→{tp}): 거리 데이터 없음 (수동 입력 필요)"
                )

        # 5단계: 목표 항차일수에 맞춰 버퍼 자동 조정
        if target_voyage_days is not None:
            adjustment_info = self._adjust_buffer_to_target(
                proforma, target_voyage_days,
            )
            if adjustment_info:
                proforma.warnings.append(adjustment_info)

        return proforma

    def _adjust_buffer_to_target(
        self, proforma: Proforma, target_days: float,
    ) -> Optional[str]:
        """
        총 항차일수를 목표값에 맞추도록 버퍼를 균등 조정.
        Returns: 조정 정보 메시지 (또는 None)
        """
        target_min = int(target_days * 24 * 60)
        current_min = sum(leg.total_time_min for leg in proforma.legs)
        diff_min = target_min - current_min

        if diff_min == 0:
            return None

        n_legs = len(proforma.legs)
        if n_legs == 0:
            return "조정 불가: 구간 없음"

        # 음수면 단축 필요 (선속 올리거나 버퍼 제거)
        if diff_min < 0:
            # 현재 총 버퍼
            current_buf = sum(leg.sea_buff_min for leg in proforma.legs)
            if current_buf + diff_min < 0:
                return (
                    f"⚠️ 목표 {target_days:.0f}일 달성 불가: "
                    f"현재 {current_min/60:.1f}h, 목표 {target_min/60:.1f}h, "
                    f"버퍼 모두 제거해도 {abs(diff_min + current_buf)/60:.1f}h 부족. "
                    f"선속 상향 검토 필요."
                )
            # 버퍼 비례 감소
            ratio = (current_buf + diff_min) / current_buf if current_buf > 0 else 0
            for leg in proforma.legs:
                leg.sea_buff_min = int(round(leg.sea_buff_min * ratio / 5) * 5)
        else:
            # 양수면 버퍼 증가 (균등 분배)
            extra_per_leg = diff_min // n_legs
            remainder = diff_min - (extra_per_leg * n_legs)
            for i, leg in enumerate(proforma.legs):
                add = extra_per_leg + (5 if i < remainder // 5 else 0)
                leg.sea_buff_min += add

        # 재계산 후 실제 차이
        final_min = sum(leg.total_time_min for leg in proforma.legs)
        final_days = final_min / (24 * 60)
        return (
            f"목표 {target_days:.0f}일 맞춤 자동 조정: "
            f"버퍼 {diff_min:+,}분 변경 → 최종 {final_days:.2f}일"
        )

    # ================================================================
    # 방식 2: 기존 서비스 복제 (From Template)
    # ================================================================
    def build_from_template(
        self,
        new_service_code: str,
        new_service_name: str,
        template_service_code: str,
        port_overrides: dict = None,  # {원래 항구: 새 항구}
    ) -> Proforma:
        """
        기존 서비스를 베이스로 신규 프로포마 생성.
        port_overrides로 일부 항구만 교체 가능.
        """
        template_legs = self.data.service.get_legs(template_service_code)
        if template_legs.empty:
            raise ValueError(f"템플릿 서비스 없음: {template_service_code}")

        port_overrides = port_overrides or {}
        proforma = Proforma(
            service_code=new_service_code,
            service_name=new_service_name,
            standards_used=self.std_extractor.suggest_assumptions(),
        )
        proforma.warnings.append(
            f"템플릿 '{template_service_code}' 기반으로 생성됨"
        )

        # 항구 교체 정보
        if port_overrides:
            override_summary = ", ".join(
                f"{k}→{v}" for k, v in port_overrides.items()
            )
            proforma.warnings.append(f"교체된 항구: {override_summary}")

        for _, row in template_legs.iterrows():
            fp = port_overrides.get(row["from_port"], row["from_port"])
            tp = port_overrides.get(row["to_port"], row["to_port"])

            # 항구가 교체되면 거리 재계산 필요
            if (fp != row["from_port"]) or (tp != row["to_port"]):
                dist_result = self.distance_matrix.get_distance(fp, tp)
                distance = dist_result.distance_nm if dist_result.found else 0
                distance_source = "matrix" if dist_result.found else "missing"
            else:
                distance = float(row.get("distance_nm") or 0)
                distance_source = "template"

            leg = ProformaLeg(
                seq=int(row["seq"]),
                from_port=fp,
                to_port=tp,
                bnd=str(row.get("bnd") or "E"),
                distance_nm=distance,
                speed_knot=float(row.get("speed_knot") or 15),
                tb_manv_min=int(row.get("tb_manv_min") or 60),
                td_manv_min=int(row.get("td_manv_min") or 60),
                tml_min=int(row.get("tml_min") or 720),
                sea_buff_min=int(row.get("sea_buff_min") or 120),
                distance_source=distance_source,
            )
            proforma.legs.append(leg)

            if distance == 0 and distance_source == "missing":
                proforma.warnings.append(
                    f"구간 {leg.seq} ({fp}→{tp}): 거리 데이터 없음"
                )

        return proforma

    # ================================================================
    # 헬퍼
    # ================================================================
    def _resolve_distance(
        self, fp: str, tp: str, manual: dict
    ) -> tuple[float, str, str]:
        """거리 결정 (수동 → 매트릭스 → 없음)"""
        if (fp, tp) in manual:
            return float(manual[(fp, tp)]), "manual", ""

        result = self.distance_matrix.get_distance(fp, tp)
        if result.found:
            warning = ""
            if result.has_variance:
                warning = (f"거리 편차 큼 ({result.variance_range[0]:.0f}~"
                           f"{result.variance_range[1]:.0f}NM, "
                           f"{result.source_count}개 평균)")
            elif result.is_reversed:
                warning = "역방향 데이터 사용"
            return result.distance_nm, "matrix", warning

        return 0.0, "missing", "거리 데이터 없음 - 수동 입력 필요"

    def _resolve_dwell_time(self, port: str, manual: dict) -> int:
        """정박시간 결정"""
        if port in manual:
            return int(manual[port])
        minutes, _ = self.std_extractor.get_port_dwell_time(port)
        return minutes

    def _assign_direction(
        self,
        leg_index: int, total_legs: int, midpoint: int, pattern: str,
        port_sequence: list = None,
        leg_directions: list = None,
    ) -> str:
        """
        방향 할당.

        규칙:
        - "manual": leg_directions[leg_index] 그대로 사용
        - "sn": 전반=S, 후반=N
        - "auto" / "ew": 수출/수입 룰 (KR→외국=W, 외국→KR=E)
        """
        # manual 모드: 사용자 지정 직접 사용
        if pattern == "manual" and leg_directions:
            return leg_directions[leg_index]

        if pattern == "sn":
            return "S" if leg_index < midpoint else "N"

        # E/W 또는 auto: 수출/수입 룰 적용
        if port_sequence is None or len(port_sequence) < 2:
            return "W" if leg_index < midpoint else "E"

        return self._assign_export_import_direction(leg_index, port_sequence)

    @staticmethod
    def _is_kr_port(port: str) -> bool:
        """한국 항구인지 (KR로 시작)"""
        return bool(port) and port.upper().startswith("KR")

    def _assign_export_import_direction(
        self, leg_index: int, port_sequence: list,
    ) -> str:
        """
        수출/수입 기반 방향 할당.
        KR→외국 = W, 외국→KR = E
        KR→KR / 외국→외국은 인접 구간 방향 따라감
        """
        fp = port_sequence[leg_index]
        tp = port_sequence[leg_index + 1]
        fp_kr = self._is_kr_port(fp)
        tp_kr = self._is_kr_port(tp)

        # 명확한 케이스
        if fp_kr and not tp_kr:
            return "W"  # KR → 외국 = 수출
        if not fp_kr and tp_kr:
            return "E"  # 외국 → KR = 수입

        # 모호한 케이스 (KR↔KR 또는 외국↔외국)
        # → 인접 leg를 탐색해서 방향 따라감
        n_legs = len(port_sequence) - 1

        # 다음 구간들을 차례로 보고 명확한 방향이 나오면 그걸 따름
        for j in range(leg_index + 1, n_legs):
            nfp = port_sequence[j]
            ntp = port_sequence[j + 1]
            if self._is_kr_port(nfp) and not self._is_kr_port(ntp):
                return "W"
            if not self._is_kr_port(nfp) and self._is_kr_port(ntp):
                return "E"

        # 이전 구간들을 거꾸로 탐색
        for j in range(leg_index - 1, -1, -1):
            pfp = port_sequence[j]
            ptp = port_sequence[j + 1]
            if self._is_kr_port(pfp) and not self._is_kr_port(ptp):
                return "W"
            if not self._is_kr_port(pfp) and self._is_kr_port(ptp):
                return "E"

        # 그래도 결정 안 되면 (예: KR→KR만 있는 노선) 기본 W
        return "W"
