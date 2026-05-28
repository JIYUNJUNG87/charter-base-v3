"""
연료비 계산기.

설계 원칙:
- 4가지 연료 모드(at_sea / in_port / maneuvering / buffer)별로 분리해서 계산
- 각 leg마다 시간별 소모량 × 단가 산출
- Maneuvering 비율은 config.FUEL_ASSUMPTIONS에서 관리 (현재 40% 가정)
- 명확한 결과 객체로 반환 (어느 모드에서 얼마 썼는지 추적 가능)

산식:
  연료비 = Σ구간별 [
      sea_time   × (main_engine(speed) + aux_at_sea) +
      port_time  × aux_at_port +
      manv_time  × (main_engine(ref_speed) × MANV_RATIO + aux_at_sea) +
      buff_time  × aux_at_port  (또는 at_sea, 설정에 따라)
  ] × bunker_price(port, fuel_type, date)
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pandas as pd

from ..data_loaders import MasterDataManager


# ============================================================
# 결과 객체
# ============================================================
@dataclass
class FuelBreakdown:
    """한 leg의 연료 소비 분석"""
    leg_seq: int
    from_port: str
    to_port: str
    speed_knot: float
    distance_nm: float

    # 모드별 시간 (hours)
    sea_hours: float = 0.0
    port_hours: float = 0.0
    manv_hours: float = 0.0
    buffer_hours: float = 0.0

    # 모드별 소모량 (ton)
    sea_consumption: float = 0.0      # main + aux
    port_consumption: float = 0.0     # aux only
    manv_consumption: float = 0.0     # main(reduced) + aux
    buffer_consumption: float = 0.0

    # 단가 정보 - 항해/Maneuvering용 (메인엔진 사용)
    bunker_port: str = ""             # 단가 조회한 항구
    bunker_price: float = 0.0         # USD/ton (항해 유종)
    price_date: Optional[date] = None
    fuel_type: str = "LSFO"           # 항해 유종 (FO 계열)

    # 정박/Buffer용 별도 유종/단가 (보조엔진 사용)
    port_fuel_type: Optional[str] = None      # 정박 유종 (None이면 항해 유종과 동일)
    port_bunker_price: float = 0.0            # USD/ton (정박 유종)

    @property
    def total_consumption_ton(self) -> float:
        return (self.sea_consumption + self.port_consumption
                + self.manv_consumption + self.buffer_consumption)

    @property
    def total_fuel_cost_usd(self) -> float:
        """모드별 적용 단가가 다르면 각각 계산"""
        if self.port_fuel_type and self.port_fuel_type != self.fuel_type:
            # 항해 유종 (SEA + MANV)
            sea_side = (self.sea_consumption + self.manv_consumption) * self.bunker_price
            # 정박 유종 (PORT + BUFFER)
            port_side = (self.port_consumption + self.buffer_consumption) * self.port_bunker_price
            return sea_side + port_side
        # 단일 유종
        return self.total_consumption_ton * self.bunker_price

    def to_dict(self) -> dict:
        return {
            "seq": self.leg_seq,
            "from_port": self.from_port,
            "to_port": self.to_port,
            "speed_knot": self.speed_knot,
            "distance_nm": self.distance_nm,
            "sea_hours": self.sea_hours,
            "port_hours": self.port_hours,
            "manv_hours": self.manv_hours,
            "buffer_hours": self.buffer_hours,
            "sea_consumption_ton": self.sea_consumption,
            "port_consumption_ton": self.port_consumption,
            "manv_consumption_ton": self.manv_consumption,
            "buffer_consumption_ton": self.buffer_consumption,
            "total_consumption_ton": self.total_consumption_ton,
            "bunker_port": self.bunker_port,
            "bunker_price_usd_per_ton": self.bunker_price,
            "price_date": self.price_date,
            "fuel_type": self.fuel_type,
            "fuel_cost_usd": self.total_fuel_cost_usd,
        }


@dataclass
class ServiceFuelResult:
    """서비스 전체의 연료비 계산 결과"""
    service_code: str
    vessel_type: str
    fuel_type: str

    leg_breakdowns: list[FuelBreakdown] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)

    @property
    def total_fuel_cost_usd(self) -> float:
        return sum(b.total_fuel_cost_usd for b in self.leg_breakdowns)

    @property
    def total_consumption_ton(self) -> float:
        return sum(b.total_consumption_ton for b in self.leg_breakdowns)

    @property
    def total_sea_hours(self) -> float:
        return sum(b.sea_hours for b in self.leg_breakdowns)

    @property
    def total_port_hours(self) -> float:
        return sum(b.port_hours for b in self.leg_breakdowns)

    @property
    def total_manv_hours(self) -> float:
        return sum(b.manv_hours for b in self.leg_breakdowns)

    @property
    def total_buffer_hours(self) -> float:
        return sum(b.buffer_hours for b in self.leg_breakdowns)

    def to_dataframe(self) -> pd.DataFrame:
        """leg별 breakdown을 DataFrame으로"""
        return pd.DataFrame([b.to_dict() for b in self.leg_breakdowns])

    def summary(self) -> dict:
        """전체 요약"""
        total = self.total_consumption_ton
        if total == 0:
            return {"total_fuel_cost_usd": 0}
        return {
            "service_code": self.service_code,
            "vessel_type": self.vessel_type,
            "fuel_type": self.fuel_type,
            "total_fuel_cost_usd": self.total_fuel_cost_usd,
            "total_consumption_ton": total,
            "consumption_breakdown_pct": {
                "sea": sum(b.sea_consumption for b in self.leg_breakdowns) / total * 100,
                "port": sum(b.port_consumption for b in self.leg_breakdowns) / total * 100,
                "manv": sum(b.manv_consumption for b in self.leg_breakdowns) / total * 100,
                "buffer": sum(b.buffer_consumption for b in self.leg_breakdowns) / total * 100,
            },
            "time_breakdown_hours": {
                "sea": self.total_sea_hours,
                "port": self.total_port_hours,
                "manv": self.total_manv_hours,
                "buffer": self.total_buffer_hours,
                "total": (self.total_sea_hours + self.total_port_hours
                          + self.total_manv_hours + self.total_buffer_hours),
            },
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


# ============================================================
# 메인 계산기
# ============================================================
class FuelCostCalculator:
    """연료비 계산기"""

    def __init__(self, data_manager: MasterDataManager, assumptions: dict = None):
        self.data = data_manager
        # config 로딩
        try:
            from config import FUEL_ASSUMPTIONS, FUEL_PRICE_DEFAULTS
            self.assumptions = dict(FUEL_ASSUMPTIONS)
            self.price_defaults = dict(FUEL_PRICE_DEFAULTS)
        except ImportError:
            # 폴백 (테스트용)
            self.assumptions = {
                "manv_main_engine_ratio": 0.40,
                "manv_reference_speed": None,
                "buffer_mode": "in_port",
                "include_aux_at_sea": True,
            }
            self.price_defaults = {
                "default_fuel_type": "LSFO",
                "port_to_bunker_port": {},
                "fallback_bunker_port": "SIN",
            }
        # 사용자 overrides
        if assumptions:
            self.assumptions.update(assumptions)

    # ----------------------------------------
    # 단일 leg 계산
    # ----------------------------------------
    def calculate_leg(
        self,
        leg: pd.Series,
        vessel_type: str,
        fuel_type: str = None,
        price_date: date = None,
        fixed_bunker_port: str = None,
        fixed_bunker_price: float = None,
        fixed_bunker_price_date: date = None,
    ) -> FuelBreakdown:
        """
        한 구간(leg)의 연료비 계산.

        leg: ServiceScheduleLoader.get_legs()의 한 행
        vessel_type: VesselSpecLoader의 type_name (예: "Jiangsu 4250")
        fuel_type: LSFO/380CST/MGO 등 (기본: LSFO)
        price_date: 단가 조회 기준일 (기본: 최신)
        fixed_bunker_port: 지정 시 모든 leg에 동일 단가 적용 (실제 운영 방식)
        """
        if fuel_type is None:
            fuel_type = self.price_defaults["default_fuel_type"]

        speed = float(leg.get("speed_knot") or 0)

        bd = FuelBreakdown(
            leg_seq=int(leg.get("seq") or 0),
            from_port=str(leg.get("from_port", "")),
            to_port=str(leg.get("to_port", "")),
            speed_knot=speed,
            distance_nm=float(leg.get("distance_nm") or 0),
            fuel_type=fuel_type,
        )

        # 1. 시간 (분 단위 → 시간)
        bd.sea_hours = self._min_to_hours(leg.get("sea_time_min"))
        bd.port_hours = self._min_to_hours(leg.get("tml_min"))
        bd.manv_hours = (
            self._min_to_hours(leg.get("tb_manv_min"))
            + self._min_to_hours(leg.get("td_manv_min"))
        )
        bd.buffer_hours = self._min_to_hours(leg.get("sea_buff_min"))

        # 2. 선형 소모량 데이터
        main_at_speed = self.data.vessel_spec.get_consumption(vessel_type, speed)
        aux_at_sea = self.data.vessel_spec.get_aux_consumption(vessel_type, "at_sea")
        aux_at_port = self.data.vessel_spec.get_aux_consumption(vessel_type, "in_port")

        # 누락 데이터 fallback (None 또는 NaN이면 0으로 처리하되 경고)
        import math
        def _safe(v):
            if v is None:
                return 0.0
            try:
                if math.isnan(v):
                    return 0.0
            except (TypeError, ValueError):
                return 0.0
            return float(v)

        aux_at_sea = _safe(aux_at_sea)
        aux_at_port = _safe(aux_at_port)
        main_at_speed = _safe(main_at_speed)

        # 3. 모드별 소모량 (ton)
        # at_sea
        sea_daily = main_at_speed
        if self.assumptions["include_aux_at_sea"]:
            sea_daily += aux_at_sea
        bd.sea_consumption = sea_daily * (bd.sea_hours / 24)

        # in_port
        bd.port_consumption = aux_at_port * (bd.port_hours / 24)

        # maneuvering: main(ref_speed) × ratio + aux_at_sea
        ref_speed = self.assumptions.get("manv_reference_speed")
        if ref_speed is None:
            # 해당 선형의 최고 등재 속도 사용
            ref_speed = self._get_design_speed(vessel_type)
        manv_main_at_design = _safe(
            self.data.vessel_spec.get_consumption(vessel_type, ref_speed)
        )
        manv_ratio = self.assumptions["manv_main_engine_ratio"]
        manv_daily = manv_main_at_design * manv_ratio + aux_at_sea
        bd.manv_consumption = manv_daily * (bd.manv_hours / 24)

        # buffer
        if self.assumptions["buffer_mode"] == "at_sea":
            buf_daily = main_at_speed + (aux_at_sea if self.assumptions["include_aux_at_sea"] else 0)
        else:
            buf_daily = aux_at_port
        bd.buffer_consumption = buf_daily * (bd.buffer_hours / 24)

        # 4. 단가 - fixed가 있으면 우선, 없으면 3단계 폴백
        if fixed_bunker_port and fixed_bunker_price is not None:
            # 사용자 지정 벙커링 항구 단가 적용 (모든 leg 동일)
            bd.bunker_port = fixed_bunker_port
            bd.bunker_price = fixed_bunker_price
            bd.price_date = fixed_bunker_price_date
        else:
            # 구버전 로직 (도착항별 단가)
            bd.bunker_port = self._map_to_bunker_port(bd.to_port)
            price = None

            # Step 1: 지정된 날짜의 단가
            if price_date:
                price = self.data.bunker.get_price(price_date, fuel_type, bd.bunker_port)
                if price is not None:
                    bd.price_date = price_date

            # Step 2: 그 항구의 최신 단가 (날짜만 폴백)
            if price is None:
                latest = self.data.bunker.get_latest_price(fuel_type, bd.bunker_port)
                if latest:
                    bd.price_date, price = latest

            # Step 3: 다른 항구로 폴백 (마지막 수단)
            if price is None:
                fb = self.price_defaults["fallback_bunker_port"]
                latest = self.data.bunker.get_latest_price(fuel_type, fb)
                if latest:
                    bd.bunker_port = fb + " (fallback)"
                    bd.price_date, price = latest

            bd.bunker_price = price or 0.0

        return bd

    # ----------------------------------------
    # 서비스 전체 계산
    # ----------------------------------------
    def calculate_service(
        self,
        service_code: str,
        vessel_type: str,
        fuel_type: str = None,
        price_date: date = None,
        bunker_port: str = None,
        port_fuel_type: str = None,
    ) -> ServiceFuelResult:
        """
        한 서비스의 모든 leg에 대한 연료비 계산.

        Parameters
        ----------
        fuel_type : 항해/Maneuvering용 유종 (메인엔진, 보통 LSFO/380CST)
        bunker_port : 벙커링 공급 항구 (모든 leg에 동일 단가 적용)
        port_fuel_type : 정박/Buffer용 유종 (None이면 fuel_type과 동일).
                       실무에서는 보조엔진이 GO 계열을 쓰는 경우가 많음 (LSMGO/MGO).
        """
        legs = self.data.service.get_legs(service_code)
        if legs.empty:
            raise ValueError(f"서비스를 찾을 수 없습니다: {service_code}")

        if fuel_type is None:
            fuel_type = self.price_defaults["default_fuel_type"]

        result = ServiceFuelResult(
            service_code=service_code,
            vessel_type=vessel_type,
            fuel_type=fuel_type,
        )

        # 가정값 기록
        result.assumptions = {
            "manv_main_engine_ratio": self.assumptions["manv_main_engine_ratio"],
            "buffer_mode": self.assumptions["buffer_mode"],
            "include_aux_at_sea": self.assumptions["include_aux_at_sea"],
        }

        # 선형 데이터 확인 + 경고
        info = self.data.vessel_spec.get_type_info(vessel_type)
        if info is None:
            raise ValueError(f"선형 정보를 찾을 수 없습니다: {vessel_type}")

        if info.get("aux_at_sea") is None or info.get("aux_at_port") is None:
            result.warnings.append(
                f"선형 '{vessel_type}'의 보조엔진 소모량(aux) 데이터가 없어 0으로 계산됨"
            )

        # Maneuvering 비율 가정 명시
        result.warnings.append(
            f"Maneuvering 메인엔진 소모량을 설계 선속 소모량의 "
            f"{self.assumptions['manv_main_engine_ratio']:.0%}로 가정 (운항팀 기준 미확정)"
        )

        # 벙커링 항구 단가 미리 조회 (서비스 단위 고정 단가)
        bunker_price_fixed = None
        bunker_price_date_fixed = None
        if bunker_port:
            if price_date:
                bunker_price_fixed = self.data.bunker.get_price(
                    price_date, fuel_type, bunker_port,
                )
                if bunker_price_fixed is not None:
                    bunker_price_date_fixed = price_date
            if bunker_price_fixed is None:
                latest = self.data.bunker.get_latest_price(fuel_type, bunker_port)
                if latest:
                    bunker_price_date_fixed, bunker_price_fixed = latest

            if bunker_price_fixed is None:
                result.warnings.append(
                    f"⚠️ 지정된 벙커링 항구 '{bunker_port}' / '{fuel_type}' 단가 데이터 없음. "
                    f"도착항별 fallback 적용."
                )

        # 정박 유종 단가도 별도 조회 (지정된 경우)
        port_fuel_price_fixed = None
        port_fuel_price_date_fixed = None
        if port_fuel_type and port_fuel_type != fuel_type and bunker_port:
            if price_date:
                port_fuel_price_fixed = self.data.bunker.get_price(
                    price_date, port_fuel_type, bunker_port,
                )
                if port_fuel_price_fixed is not None:
                    port_fuel_price_date_fixed = price_date
            if port_fuel_price_fixed is None:
                latest = self.data.bunker.get_latest_price(port_fuel_type, bunker_port)
                if latest:
                    port_fuel_price_date_fixed, port_fuel_price_fixed = latest

        # 각 leg 계산
        unmapped_ports = set()
        for _, leg in legs.iterrows():
            bd = self.calculate_leg(
                leg, vessel_type, fuel_type, price_date,
                fixed_bunker_port=bunker_port if bunker_price_fixed else None,
                fixed_bunker_price=bunker_price_fixed,
                fixed_bunker_price_date=bunker_price_date_fixed,
            )
            # 정박 유종 별도 적용
            if port_fuel_price_fixed:
                bd.port_fuel_type = port_fuel_type
                bd.port_bunker_price = port_fuel_price_fixed
            elif port_fuel_type and port_fuel_type != fuel_type:
                # 같은 가격이라도 유종은 표기
                bd.port_fuel_type = port_fuel_type
                bd.port_bunker_price = bd.bunker_price  # fallback

            result.leg_breakdowns.append(bd)
            if "fallback" in bd.bunker_port:
                unmapped_ports.add(bd.to_port)

        if unmapped_ports:
            result.warnings.append(
                f"단가 매핑이 없어 fallback 항구 사용한 항구: {sorted(unmapped_ports)}"
            )

        if bunker_port and bunker_price_fixed:
            msg = (f"✅ 벙커링 항구 '{bunker_port}' 단가 ${bunker_price_fixed:.1f}/톤 "
                   f"({bunker_price_date_fixed}) 전체 leg에 동일 적용")
            if port_fuel_price_fixed:
                msg += (f" / 정박 유종 '{port_fuel_type}' "
                        f"${port_fuel_price_fixed:.1f}/톤 별도 적용")
            result.warnings.append(msg)

        return result

    # ----------------------------------------
    # 헬퍼
    # ----------------------------------------
    @staticmethod
    def _min_to_hours(val) -> float:
        if val is None or pd.isna(val):
            return 0.0
        try:
            return max(0.0, float(val) / 60)
        except (ValueError, TypeError):
            return 0.0

    def _get_design_speed(self, vessel_type: str) -> float:
        """선형의 최고 등재 선속을 design speed로 사용"""
        df = self.data.vessel_spec.get_speed_consumption()
        sub = df[df["type_name"] == vessel_type]
        if sub.empty:
            return 18.0  # 기본값
        return float(sub["speed"].max())

    def _map_to_bunker_port(self, port_code: str) -> str:
        """ANX의 항구코드 → BUNKER 파일의 단가 항구"""
        mapping = self.price_defaults.get("port_to_bunker_port", {})
        if port_code in mapping:
            return mapping[port_code]
        # 국가 코드(앞 2자리)로 매칭 시도
        country = port_code[:2] if len(port_code) >= 2 else ""
        country_default = {
            "KR": "KOR", "CN": "SHA", "HK": "HKG", "SG": "SIN",
            "VN": "SIN", "TH": "SIN", "ID": "SIN", "MY": "SIN", "PH": "SIN",
            "JP": "KOR",  # 일본은 한국 단가가 가장 가까움
            "AE": "FJR", "IN": "FJR", "PK": "FJR",
            "RU": "RUS",
        }
        return country_default.get(country, self.price_defaults["fallback_bunker_port"])
