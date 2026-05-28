"""
항구 페어 거리 매트릭스.

기존 SERVICE_LIST의 444개 구간 데이터에서 항구 페어별 평균 거리를 추출.
신규 항로 작성 시 거리 자동 채우기 용도.

핵심 기능:
- 두 항구 사이 거리 조회 (양방향 모두 시도)
- 같은 페어인데 거리가 일관되지 않으면 경고
- 1NM 같은 명백한 오류 데이터 필터링
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager


# 명백한 오류로 간주할 최소 거리 (이보다 작으면 무시)
MIN_REASONABLE_DISTANCE_NM = 5

# 같은 페어의 거리 편차가 이 이상이면 경고 표시
DISTANCE_VARIANCE_WARNING_NM = 50


@dataclass
class DistanceLookupResult:
    """거리 조회 결과"""
    from_port: str
    to_port: str
    distance_nm: Optional[float] = None
    source_count: int = 0           # 몇 개의 서비스에서 사용된 거리인지
    is_reversed: bool = False       # 역방향(to→from) 데이터를 사용한 경우
    has_variance: bool = False      # 같은 페어인데 거리 편차 큼
    variance_range: Optional[tuple] = None  # (min, max)

    @property
    def found(self) -> bool:
        return self.distance_nm is not None


class DistanceMatrix:
    """항구 페어 거리 매트릭스"""

    def __init__(self, data_manager: MasterDataManager):
        self.data = data_manager
        self._matrix = None
        self._build()

    def _build(self):
        """기존 서비스 데이터에서 거리 매트릭스 구축"""
        legs = self.data.service.get_legs()
        df = legs[["from_port", "to_port", "distance_nm"]].dropna()
        # 비합리적인 값 제거 (1NM 같은 오류)
        df = df[df["distance_nm"] >= MIN_REASONABLE_DISTANCE_NM]

        # 페어별 통계
        stats = df.groupby(["from_port", "to_port"])["distance_nm"].agg(
            ["mean", "min", "max", "count"]
        ).reset_index()
        stats["variance"] = stats["max"] - stats["min"]
        self._matrix = stats

    def get_distance(self, from_port: str, to_port: str) -> DistanceLookupResult:
        """
        두 항구 사이 거리 조회.
        - 1순위: 정방향 (from→to) 데이터
        - 2순위: 역방향 (to→from) 데이터 (왕복 거리는 동일하다고 가정)
        - 둘 다 없으면 found=False
        """
        # 1) 정방향 조회
        mask = (self._matrix["from_port"] == from_port) & \
               (self._matrix["to_port"] == to_port)
        forward = self._matrix[mask]

        if not forward.empty:
            row = forward.iloc[0]
            return DistanceLookupResult(
                from_port=from_port, to_port=to_port,
                distance_nm=round(float(row["mean"])),
                source_count=int(row["count"]),
                has_variance=row["variance"] >= DISTANCE_VARIANCE_WARNING_NM,
                variance_range=(float(row["min"]), float(row["max"]))
                                if row["variance"] > 0 else None,
            )

        # 2) 역방향 조회
        mask_rev = (self._matrix["from_port"] == to_port) & \
                   (self._matrix["to_port"] == from_port)
        backward = self._matrix[mask_rev]

        if not backward.empty:
            row = backward.iloc[0]
            return DistanceLookupResult(
                from_port=from_port, to_port=to_port,
                distance_nm=round(float(row["mean"])),
                source_count=int(row["count"]),
                is_reversed=True,
                has_variance=row["variance"] >= DISTANCE_VARIANCE_WARNING_NM,
                variance_range=(float(row["min"]), float(row["max"]))
                                if row["variance"] > 0 else None,
            )

        return DistanceLookupResult(from_port=from_port, to_port=to_port)

    def get_distances_for_route(
        self, port_sequence: list[str]
    ) -> list[DistanceLookupResult]:
        """기항지 순서를 받아서 각 구간별 거리 리스트 반환"""
        results = []
        for i in range(len(port_sequence) - 1):
            fp, tp = port_sequence[i], port_sequence[i + 1]
            results.append(self.get_distance(fp, tp))
        return results

    def get_known_ports(self) -> list[str]:
        """매트릭스에 있는 모든 항구 코드"""
        from_ports = set(self._matrix["from_port"].unique())
        to_ports = set(self._matrix["to_port"].unique())
        return sorted(from_ports | to_ports)

    def get_neighbors(self, port: str, top_n: int = 20) -> list[tuple[str, float]]:
        """특정 항구에서 갈 수 있는 다른 항구들 (거리순)"""
        mask = self._matrix["from_port"] == port
        neighbors = self._matrix[mask].sort_values("mean").head(top_n)
        return [(row["to_port"], round(float(row["mean"]), 0))
                for _, row in neighbors.iterrows()]
