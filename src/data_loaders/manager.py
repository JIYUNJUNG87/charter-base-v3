"""
통합 데이터 매니저.
모든 마스터 데이터 로더를 한 곳에서 관리.

사용 예:
    from src.data_loaders import MasterDataManager
    mgr = MasterDataManager()

    # 단가 조회
    price = mgr.bunker.get_latest_price("LSFO", "KOR")

    # 8000TEU 선박의 월 용선료 (CA20 매칭)
    cat, rate = mgr.hire.get_rate_by_teu(2026, 1, 8000)

    # ANX 서비스 요약
    summary = mgr.service.get_service_summary("ANX")
"""

import os
from pathlib import Path
from .bunker_loader import BunkerPriceLoader
from .hire_loader import HireRateLoader
from .port_charge_loader import PortChargeLoader
from .vessel_spec_loader import VesselSpecLoader
from .service_loader import ServiceScheduleLoader


# 기본 파일 경로 (data/master/ 디렉토리 기준)
DEFAULT_FILES = {
    "bunker": "BUNKER.xls",
    "hire": "HIRE.xls",
    "port_charge": "PORT_CHARGE.xls",
    "vessel_spec": "vessel_spec.xlsx",
    "service": "SERVICE_LIST.xls",
}


class MasterDataManager:
    """모든 마스터 데이터 로더의 통합 매니저"""

    def __init__(self, master_dir: str | Path | None = None):
        # 우선순위: 명시 인자 > 환경변수 > 기본 data/master > 폴백 data/master_demo
        if master_dir is None:
            env = os.getenv("CHARTERBASE_MASTER_DIR")
            if env:
                master_dir = env
            elif Path("data/master").exists():
                master_dir = "data/master"
            else:
                master_dir = "data/master_demo"

        self.master_dir = Path(master_dir)
        if not self.master_dir.exists():
            raise FileNotFoundError(f"마스터 디렉토리가 없습니다: {self.master_dir}")

        self.bunker = BunkerPriceLoader(self.master_dir / DEFAULT_FILES["bunker"])
        self.hire = HireRateLoader(self.master_dir / DEFAULT_FILES["hire"])
        self.port_charge = PortChargeLoader(self.master_dir / DEFAULT_FILES["port_charge"])
        self.vessel_spec = VesselSpecLoader(self.master_dir / DEFAULT_FILES["vessel_spec"])
        self.service = ServiceScheduleLoader(self.master_dir / DEFAULT_FILES["service"])

    def reload_all(self):
        """모든 로더의 캐시 초기화 (파일 갱신 시)"""
        self.bunker.reload()
        self.hire.reload()
        self.port_charge.reload()
        self.vessel_spec.reload()
        self.service.reload()

    def summary(self) -> dict:
        """모든 데이터의 요약 통계"""
        return {
            "bunker": {
                "records": len(self.bunker.load()),
                "date_range": self.bunker.get_date_range(),
                "fuel_types": self.bunker.get_available_fuel_types(),
                "ports": self.bunker.get_available_ports(),
            },
            "hire": {
                "categories": len(self.hire.get_categories()),
                "rates": len(self.hire.get_rates()),
            },
            "port_charge": {
                "records": len(self.port_charge.load()),
                "ports": len(self.port_charge.get_available_ports()),
            },
            "vessel_spec": {
                "types": len(self.vessel_spec.get_types()),
                "teu_classes": self.vessel_spec.get_teu_classes(),
            },
            "service": {
                "services": len(self.service.get_services()),
                "legs": len(self.service.get_legs()),
            },
        }
