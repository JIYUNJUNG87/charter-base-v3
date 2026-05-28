"""
Oracle 직접 연결 데이터 소스 (스켈레톤).

전산팀에서 읽기 전용 DB 계정을 발급해주면 _parse_to_baseline()을 구현하면 됩니다.
"""

from datetime import date
from .base import CharterBaseDataSource
from ..engine.models import RouteBaseline


# 실제 ERP 테이블 명 확인 후 수정
SQL_ROUTE_LIST = """
SELECT service_code, route_cb_no, route_name
FROM charter_base_master
WHERE active_yn = 'Y'
ORDER BY service_code, route_cb_no
"""


class OracleDataSource(CharterBaseDataSource):
    """차터베이스 Oracle DB 직접 연결"""

    def __init__(self, user: str, password: str, dsn: str):
        self.user = user
        self.password = password
        self.dsn = dsn
        self._conn = None

    def _connect(self):
        if self._conn is None:
            try:
                import oracledb
            except ImportError:
                raise ImportError("`pip install oracledb` 필요")
            self._conn = oracledb.connect(
                user=self.user, password=self.password, dsn=self.dsn
            )
        return self._conn

    def get_route_list(self) -> list[dict]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(SQL_ROUTE_LIST)
            return [
                {"service_code": r[0], "route_cb_no": r[1], "route_name": r[2]}
                for r in cur.fetchall()
            ]

    def get_baseline(self, service_code, route_cb_no, period_start, period_end):
        # [TODO] 차터베이스 테이블 구조 확인 후 구현
        raise NotImplementedError("DB 계정 발급 후 SQL 작성 필요")
