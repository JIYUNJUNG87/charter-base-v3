"""
BUNKER 단가 로더.

원본 BUNKER.xls 구조:
- 1행: 유종 그룹 헤더 (380CST, 180CST, LSFO, MGO, LSMGO, MOPS)
- 2행: 항구 코드 (SIN, KOR, HKG, RUS, FJR, SHA) × 유종 수
- 3행~: 일별 단가 데이터

표준 출력 형식 (long format DataFrame):
    date         fuel_type   port    price
    2026-01-02   380CST      KOR     383.0
    2026-01-02   LSFO        SIN     423.0
    ...

조회 메서드 제공:
- get_price(date, fuel_type, port)
- get_latest_price(fuel_type, port)
- get_average_price(start, end, fuel_type, port)
"""

from datetime import date, datetime
from pathlib import Path
import pandas as pd
from .base import BaseDataLoader


# 원본 파일에서 사용하는 유종 그룹 (1행 헤더)
FUEL_TYPES = ["380CST", "180CST", "LSFO", "MGO", "LSMGO", "MOPS"]

# 각 유종별 항구 컬럼 수 (대부분 6개: SIN/KOR/HKG/RUS/FJR/SHA)
# MOPS는 일부만 있을 수 있어서 실제 헤더로 확인
PORTS = ["SIN", "KOR", "HKG", "RUS", "FJR", "SHA"]


class BunkerPriceLoader(BaseDataLoader):
    """PLATTS 벙커 단가 로더"""

    def _parse(self) -> pd.DataFrame:
        # 헤더 2줄로 읽기 (유종, 항구)
        raw = pd.read_excel(
            self.file_path,
            header=[0, 1]
        )

        records = []
        # 첫 컬럼 = DATE
        date_col = raw.columns[0]

        for col in raw.columns[1:]:
            fuel_type, port = col
            # MultiIndex의 Unnamed 처리
            if "Unnamed" in str(fuel_type) or "Unnamed" in str(port):
                continue
            # 유종이 유효한지 확인
            if fuel_type not in FUEL_TYPES:
                continue
            # 항구 코드 정규화
            port_clean = str(port).strip()
            if port_clean not in PORTS:
                continue

            for _, row in raw.iterrows():
                date_val = row[date_col]
                price = row[col]
                # 날짜 파싱
                parsed_date = self._parse_date(date_val)
                if parsed_date is None:
                    continue
                # 가격이 숫자이고 NaN 아닌 경우만
                if pd.isna(price):
                    continue
                try:
                    price_float = float(price)
                except (ValueError, TypeError):
                    continue

                records.append({
                    "date": parsed_date,
                    "fuel_type": fuel_type,
                    "port": port_clean,
                    "price": price_float,
                })

        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values(["date", "fuel_type", "port"]).reset_index(drop=True)
        return df

    @staticmethod
    def _parse_date(val) -> date | None:
        """DATE 컬럼이 20260101 형식 또는 datetime일 수 있음"""
        if pd.isna(val):
            return None
        try:
            if isinstance(val, (int, float)):
                s = str(int(val))
                if len(s) == 8:
                    return datetime.strptime(s, "%Y%m%d").date()
            if isinstance(val, str):
                s = val.strip()
                if len(s) == 8 and s.isdigit():
                    return datetime.strptime(s, "%Y%m%d").date()
            if isinstance(val, pd.Timestamp):
                return val.date()
            if isinstance(val, datetime):
                return val.date()
        except (ValueError, TypeError):
            return None
        return None

    # ===== 조회 API =====
    def get_price(
        self, target_date: date, fuel_type: str, port: str
    ) -> float | None:
        """특정 날짜의 단가 조회. 없으면 None."""
        df = self.load()
        mask = (
            (df["date"] == target_date)
            & (df["fuel_type"] == fuel_type)
            & (df["port"] == port)
        )
        result = df[mask]
        if result.empty:
            return None
        return float(result.iloc[0]["price"])

    def get_latest_price(self, fuel_type: str, port: str) -> tuple[date, float] | None:
        """가장 최근 단가 조회. (날짜, 가격) 또는 None."""
        df = self.load()
        mask = (df["fuel_type"] == fuel_type) & (df["port"] == port)
        result = df[mask].sort_values("date", ascending=False)
        if result.empty:
            return None
        row = result.iloc[0]
        return (row["date"], float(row["price"]))

    def get_average_price(
        self,
        start_date: date,
        end_date: date,
        fuel_type: str,
        port: str,
    ) -> float | None:
        """기간 평균 단가."""
        df = self.load()
        mask = (
            (df["date"] >= start_date)
            & (df["date"] <= end_date)
            & (df["fuel_type"] == fuel_type)
            & (df["port"] == port)
        )
        result = df[mask]
        if result.empty:
            return None
        return float(result["price"].mean())

    def get_available_fuel_types(self) -> list[str]:
        df = self.load()
        return sorted(df["fuel_type"].unique().tolist())

    def get_available_ports(self) -> list[str]:
        df = self.load()
        return sorted(df["port"].unique().tolist())

    def get_date_range(self) -> tuple[date, date] | None:
        df = self.load()
        if df.empty:
            return None
        return (df["date"].min(), df["date"].max())
