"""
ERP REST API 데이터 소스 (스켈레톤).
전산팀이 API 스펙을 확정하면 구현.
"""

from datetime import date
from .base import CharterBaseDataSource
from ..engine.models import RouteBaseline


class ERPApiDataSource(CharterBaseDataSource):
    def __init__(self, base_url, auth_token="", timeout=30):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout

    def get_route_list(self):
        # [TODO] GET /charter-base/routes
        raise NotImplementedError("API 스펙 확정 후 구현")

    def get_baseline(self, service_code, route_cb_no, period_start, period_end):
        # [TODO] GET /charter-base/{service_code}/{route_cb_no}/pnl
        raise NotImplementedError("API 스펙 확정 후 구현")
