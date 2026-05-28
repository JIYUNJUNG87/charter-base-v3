"""
가상 데이터 소스.
업로드해주신 차터베이스 화면의 SIS2 항로 데이터를 실제 값 그대로 입력.
이걸로 시뮬레이션 결과가 화면과 일치하는지 검증 가능.
"""

from datetime import date
from .base import CharterBaseDataSource
from ..engine.models import (
    RouteBaseline, DirectionalPnL, VesselType, LoadingInfo, RateInfo,
    Revenue, CargoVariableCost, VoyageVariableCost, VoyageFixedCost,
    PortPairData,
)


# 선형 마스터 데이터 (실제로는 ERP의 선박 마스터에서 가져옴)
VESSEL_TYPES = {
    "4000TEU": VesselType(
        vessel_class="4000TEU",
        capacity_teu=4000,
        daily_fuel_consumption=85,
        daily_charter_rate=18000,
        service_speed=21,
    ),
    "8000TEU": VesselType(
        vessel_class="8000TEU",
        capacity_teu=8000,
        daily_fuel_consumption=140,
        daily_charter_rate=32000,
        service_speed=22,
    ),
    "14000TEU": VesselType(
        vessel_class="14000TEU",
        capacity_teu=14000,
        daily_fuel_consumption=180,
        daily_charter_rate=45000,
        service_speed=23,
    ),
    "18000TEU": VesselType(
        vessel_class="18000TEU",
        capacity_teu=18000,
        daily_fuel_consumption=210,
        daily_charter_rate=58000,
        service_speed=23,
    ),
}


class MockDataSource(CharterBaseDataSource):
    """차터베이스 화면을 모사한 가상 데이터"""

    def get_route_list(self) -> list[dict]:
        # 차터베이스 화면 좌측 리스트 그대로
        return [
            {"service_code": "PVS2", "route_cb_no": "089", "route_name": "PVS2-089"},
            {"service_code": "TPX",  "route_cb_no": "015", "route_name": "TPX-015"},
            {"service_code": "TPX",  "route_cb_no": "016", "route_name": "TPX-016"},
            {"service_code": "TPX",  "route_cb_no": "017", "route_name": "TPX-017"},
            {"service_code": "SIS2", "route_cb_no": "080", "route_name": "SIS2-080"},
            {"service_code": "PXS",  "route_cb_no": "011", "route_name": "PXS-011"},
        ]

    def get_baseline(
        self,
        service_code: str,
        route_cb_no: str,
        period_start: date,
        period_end: date,
    ) -> RouteBaseline:
        if service_code == "SIS2" and route_cb_no == "080":
            return self._sis2_080(period_start, period_end)
        # 다른 항로는 SIS2 기반으로 변형해서 반환 (PoC용)
        return self._generic_route(
            service_code, route_cb_no, period_start, period_end
        )

    # ========================================================
    # SIS2-080 실제 데이터 (차터베이스 화면 그대로)
    # 단위: 천 USD (화면과 동일)
    # ========================================================
    def _sis2_080(self, period_start, period_end) -> RouteBaseline:
        # ===== East 방향 =====
        east = DirectionalPnL(
            direction="E",
            loading=LoadingInfo(
                own_capacity=1000,
                loaded_teu=326,
                coc_teu=326,
                soc_teu=0,
                empty_container=60,
            ),
            rate=RateInfo(
                avg_rate=243,
                coc_avg_rate=243,
                soc_avg_rate=0,
            ),
            revenue=Revenue(
                freight=79237,
                charter_revenue=0,
                slot_revenue=0,
            ),
            cargo_var_cost=CargoVariableCost(
                handling=39357,
                feeder=0,
                agency_commission=1981,
                equipment_transport=5899,
                equipment_cost=9701,
            ),
            voyage_var_cost=VoyageVariableCost(
                port_charge=0,
                fuel=0,
            ),
            voyage_fixed_cost=VoyageFixedCost(
                charter_hire=0,
                slot_charter=257310,
            ),
        )

        # ===== West 방향 =====
        west = DirectionalPnL(
            direction="W",
            loading=LoadingInfo(
                own_capacity=1000,
                loaded_teu=380,
                coc_teu=378,
                soc_teu=2,
                empty_container=0,
            ),
            rate=RateInfo(
                avg_rate=1153,
                coc_avg_rate=1155,
                soc_avg_rate=832,
            ),
            revenue=Revenue(
                freight=438307,
                charter_revenue=0,
                slot_revenue=0,
            ),
            cargo_var_cost=CargoVariableCost(
                handling=49225,
                feeder=0,
                agency_commission=10958,
                equipment_transport=0,
                equipment_cost=15777,
            ),
            voyage_var_cost=VoyageVariableCost(
                port_charge=0,
                fuel=0,
            ),
            voyage_fixed_cost=VoyageFixedCost(
                charter_hire=0,
                slot_charter=231677,
            ),
        )

        # ===== 포트 페어 데이터 (차터베이스 우측 패널 그대로) =====
        port_pairs = [
            PortPairData("W", "KRPUS", "INNSA", 62, 0, 0),
            PortPairData("W", "KRPUS", "INMUN", 28, 0, 0),
            PortPairData("W", "KRPUS", "PKKHI", 16, 0, 0),
            PortPairData("W", "KRKAN", "INNSA", 52, 0, 0),
            PortPairData("W", "KRKAN", "INMUN", 10, 0, 0),
            PortPairData("W", "KRKAN", "PKKHI", 12, 0, 0),
            PortPairData("W", "CNSHA", "INNSA", 85, 0, 0),
            PortPairData("W", "CNSHA", "INMUN", 6, 0, 0),
            PortPairData("W", "CNSHA", "PKKHI", 9, 0, 0),
            PortPairData("W", "CNNGB", "INNSA", 32, 0, 0),
            PortPairData("W", "CNNGB", "INMUN", 6, 0, 0),
            PortPairData("W", "CNNGB", "PKKHI", 12, 0, 0),
            PortPairData("W", "CNSHK", "INNSA", 37, 0, 0),
            PortPairData("W", "CNSHK", "INMUN", 9, 0, 0),
            PortPairData("W", "CNSHK", "PKKHI", 4, 0, 0),
            PortPairData("E", "INNSA", "KRPUS", 96, 0, 0),
            PortPairData("E", "INMUN", "KRPUS", 80, 0, 0),
            PortPairData("E", "PKKHI", "KRPUS", 35, 0, 0),
            PortPairData("E", "MYPKL", "KRPUS", 50, 0, 0),
        ]

        return RouteBaseline(
            service_code="SIS2",
            route_cb_no="080",
            route_name="SIS2-080 (한국-인도/파키스탄)",
            period_start=period_start,
            period_end=period_end,
            vessel=VESSEL_TYPES["8000TEU"],  # 가정
            east=east,
            west=west,
            port_pairs=port_pairs,
        )

    def _generic_route(self, service_code, route_cb_no, period_start, period_end):
        """기타 항로용 임시 데이터 (PoC 시연용)"""
        sis2 = self._sis2_080(period_start, period_end)
        sis2.service_code = service_code
        sis2.route_cb_no = route_cb_no
        sis2.route_name = f"{service_code}-{route_cb_no}"
        return sis2
