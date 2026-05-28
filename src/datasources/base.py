"""
데이터 소스 추상 인터페이스.

지금: MockDataSource (차터베이스 화면 데이터 모사)
나중: OracleDataSource, ERPApiDataSource (실제 ERP 연결)
"""

from abc import ABC, abstractmethod
from datetime import date
from ..engine.models import RouteBaseline


class CharterBaseDataSource(ABC):
    """차터베이스 데이터 소스 추상 클래스"""

    @abstractmethod
    def get_route_list(self) -> list[dict]:
        """
        항로 목록 반환.
        예: [{"service_code": "SIS2", "route_cb_no": "080", "route_name": "..."}, ...]
        """
        pass

    @abstractmethod
    def get_baseline(
        self,
        service_code: str,
        route_cb_no: str,
        period_start: date,
        period_end: date,
    ) -> RouteBaseline:
        """특정 항로/기간의 베이스라인 데이터 반환"""
        pass


class DataSourceFactory:
    """설정에 따라 데이터 소스 생성"""

    @staticmethod
    def create(source_type: str) -> CharterBaseDataSource:
        if source_type == "mock":
            from .mock_source import MockDataSource
            return MockDataSource()
        elif source_type == "oracle":
            from .oracle_source import OracleDataSource
            from config import ORACLE_CONFIG
            return OracleDataSource(**ORACLE_CONFIG)
        elif source_type == "api":
            from .api_source import ERPApiDataSource
            from config import API_CONFIG
            return ERPApiDataSource(**API_CONFIG)
        else:
            raise ValueError(f"Unknown data source: {source_type}")
