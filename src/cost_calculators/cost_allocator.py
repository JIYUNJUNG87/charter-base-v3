"""
운항원가 방향별(E/W) 분배기.

한 항차 전체로 계산된 운항원가를 차터베이스 양식에 맞게
East/West 방향으로 나누는 모듈.

분배 방식 (비용 유형별로 다름):
  - 항비: 발생 항구의 직전 leg의 BND(방향)에 직접 귀속 (정확)
  - 연료비: leg별 시간 × 방향에 귀속 (정확)
  - 용선료: 전체 항차 일수를 방향별 시간 비율로 분배 (시간성 비용)
"""

from dataclasses import dataclass
import pandas as pd

from ..data_loaders import MasterDataManager
from .voyage_cost_calculator import VoyageCostResult


@dataclass
class DirectionalCostAllocation:
    """방향별로 분배된 운항원가"""
    service_code: str
    vessel_type: str

    # East 방향
    east_fuel: float = 0.0
    east_port_charge: float = 0.0
    east_charter: float = 0.0
    east_voyage_hours: float = 0.0

    # West 방향
    west_fuel: float = 0.0
    west_port_charge: float = 0.0
    west_charter: float = 0.0
    west_voyage_hours: float = 0.0

    # 분배 불가능한 경우 (예: 방향 정보 없는 leg)
    unallocated_fuel: float = 0.0
    unallocated_port_charge: float = 0.0
    unallocated_charter: float = 0.0

    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    # ===== 운항변동비 (차터베이스 양식) =====
    @property
    def east_voyage_variable_cost(self) -> float:
        return self.east_fuel + self.east_port_charge

    @property
    def west_voyage_variable_cost(self) -> float:
        return self.west_fuel + self.west_port_charge

    # ===== 운항고정비 (차터베이스 양식) =====
    @property
    def east_voyage_fixed_cost(self) -> float:
        return self.east_charter

    @property
    def west_voyage_fixed_cost(self) -> float:
        return self.west_charter

    # ===== 검증용 합계 =====
    @property
    def total_fuel(self) -> float:
        return self.east_fuel + self.west_fuel + self.unallocated_fuel

    @property
    def total_port_charge(self) -> float:
        return self.east_port_charge + self.west_port_charge + self.unallocated_port_charge

    @property
    def total_charter(self) -> float:
        return self.east_charter + self.west_charter + self.unallocated_charter

    def to_dict(self) -> dict:
        return {
            "east": {
                "fuel": self.east_fuel,
                "port_charge": self.east_port_charge,
                "charter": self.east_charter,
                "voyage_variable_cost": self.east_voyage_variable_cost,
                "voyage_fixed_cost": self.east_voyage_fixed_cost,
                "voyage_hours": self.east_voyage_hours,
            },
            "west": {
                "fuel": self.west_fuel,
                "port_charge": self.west_port_charge,
                "charter": self.west_charter,
                "voyage_variable_cost": self.west_voyage_variable_cost,
                "voyage_fixed_cost": self.west_voyage_fixed_cost,
                "voyage_hours": self.west_voyage_hours,
            },
            "unallocated": {
                "fuel": self.unallocated_fuel,
                "port_charge": self.unallocated_port_charge,
                "charter": self.unallocated_charter,
            },
            "warnings": self.warnings,
        }


class CostAllocator:
    """
    한 항차의 운항원가를 East/West 방향별로 분배.

    BND 컬럼 해석:
        S (South), N (North), E (East), W (West) 또는 직접 E/W
        실제 데이터에서는 'S'(남쪽=서향, West)와 'N'(북쪽=동향, East)로 쓰임
        SERVICE LIST의 BND 컬럼 매핑을 따름
    """

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager

    @staticmethod
    def _normalize_direction(
        bnd: str,
        sn_mapping: dict = None,
    ) -> str:
        """
        BND 컬럼 값을 차터베이스 양식의 E/W로 정규화.

        대부분의 서비스는 BND를 'E', 'W'로 직접 표기 → 그대로 사용.
        일부 남북 노선(아시아 역내)은 'S', 'N'으로 표기 → 항로별 명시적 매핑 필요.

        Parameters
        ----------
        bnd : 프로포마의 BND 값
        sn_mapping : 해당 서비스의 S/N → E/W 매핑 룰 (없으면 S/N은 매핑하지 않음)
                     예: {"S": "W", "N": "E"}

        Returns
        -------
        "E", "W", 또는 None (매핑 불가)
        """
        if not bnd or pd.isna(bnd):
            return None
        s = str(bnd).strip().upper()

        # 1) E/W 직접 표기 (가장 흔한 케이스)
        if s in ("E", "EAST", "EB"):
            return "E"
        if s in ("W", "WEST", "WB"):
            return "W"

        # 2) S/N 표기 - 명시적 매핑이 있을 때만 사용
        if sn_mapping:
            mapped = sn_mapping.get(s)
            if mapped in ("E", "W"):
                return mapped

        return None

    def allocate(
        self,
        cost_result: VoyageCostResult,
        sn_mapping: dict = None,
    ) -> DirectionalCostAllocation:
        """
        운항원가 결과를 E/W로 분배.

        Parameters
        ----------
        cost_result : VoyageCostResult
        sn_mapping : S/N → E/W 매핑 (예: {"S": "W", "N": "E"})
                     None이면 S/N 표기 항로의 비용은 unallocated로 처리.
                     해당 서비스의 비즈니스 룰에 따라 회사가 결정.
        """
        legs = self.data.service.get_legs(cost_result.service_code)
        if legs.empty:
            raise ValueError(f"서비스 없음: {cost_result.service_code}")

        alloc = DirectionalCostAllocation(
            service_code=cost_result.service_code,
            vessel_type=cost_result.vessel_type,
        )

        # 1) leg별 방향 정규화 + 시간 합계
        legs = legs.copy()
        legs["direction"] = legs["bnd"].apply(
            lambda b: self._normalize_direction(b, sn_mapping)
        )

        # 사용된 BND 값 분석
        unique_bnds = legs["bnd"].dropna().unique().tolist()
        has_sn = any(b in ("S", "N") for b in unique_bnds)
        has_ew = any(b in ("E", "W") for b in unique_bnds)

        if has_sn and not sn_mapping:
            alloc.warnings.append(
                f"서비스 '{cost_result.service_code}'는 BND를 S/N으로 표기하는데 "
                f"sn_mapping이 제공되지 않았습니다. S/N leg의 비용이 unallocated로 처리됩니다. "
                f"sn_mapping 예: {{'S': 'W', 'N': 'E'}} 또는 {{'S': 'E', 'N': 'W'}}"
            )

        # leg별 시간 (시간) - sea + port + manv + buffer
        def leg_total_hours(row):
            cols = ["sea_time_min", "tml_min", "tb_manv_min",
                    "td_manv_min", "sea_buff_min"]
            total = 0
            for c in cols:
                v = row.get(c)
                if v is not None and not pd.isna(v):
                    total += float(v)
            return total / 60

        legs["total_hours"] = legs.apply(leg_total_hours, axis=1)

        # 2) 방향 미지정 leg 체크
        unknown_legs = legs[legs["direction"].isna()]
        if not unknown_legs.empty:
            unknown_seqs = unknown_legs["seq"].tolist()
            alloc.warnings.append(
                f"방향(BND) 정보가 없는 leg: {unknown_seqs} → unallocated로 분배"
            )

        # 3) 연료비 분배 (leg별로 직접 분배)
        fuel_df = cost_result.fuel.to_dataframe()
        # legs와 fuel_df는 seq 기준으로 매칭
        merged = legs.merge(
            fuel_df[["seq", "fuel_cost_usd"]],
            on="seq", how="left",
        )
        for _, row in merged.iterrows():
            cost = float(row.get("fuel_cost_usd") or 0)
            direction = row["direction"]
            if direction == "E":
                alloc.east_fuel += cost
            elif direction == "W":
                alloc.west_fuel += cost
            else:
                alloc.unallocated_fuel += cost

        # 4) 항비 분배 (각 leg의 도착항에서 발생하는 항비를 그 leg의 방향에 귀속)
        port_df = cost_result.port_charge.to_dataframe()
        port_merged = legs.merge(
            port_df[["seq", "charge_usd"]],
            on="seq", how="left",
        )
        for _, row in port_merged.iterrows():
            cost = float(row.get("charge_usd") or 0)
            direction = row["direction"]
            if direction == "E":
                alloc.east_port_charge += cost
            elif direction == "W":
                alloc.west_port_charge += cost
            else:
                alloc.unallocated_port_charge += cost

        # 5) 시간 합계 (방향별)
        alloc.east_voyage_hours = legs[legs["direction"] == "E"]["total_hours"].sum()
        alloc.west_voyage_hours = legs[legs["direction"] == "W"]["total_hours"].sum()
        unallocated_hours = legs[legs["direction"].isna()]["total_hours"].sum()

        # 6) 용선료 분배 (시간 비율)
        total_hours = (alloc.east_voyage_hours + alloc.west_voyage_hours
                       + unallocated_hours)
        total_charter = cost_result.total_charter_usd
        if total_hours > 0:
            alloc.east_charter = total_charter * (alloc.east_voyage_hours / total_hours)
            alloc.west_charter = total_charter * (alloc.west_voyage_hours / total_hours)
            alloc.unallocated_charter = total_charter * (unallocated_hours / total_hours)
        else:
            alloc.unallocated_charter = total_charter

        return alloc
