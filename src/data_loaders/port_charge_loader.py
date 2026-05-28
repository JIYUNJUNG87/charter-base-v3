"""
PORT_CHARGE (항구별 선형별 항비) 로더.

원본 PORT_CHARGE.xls 구조:
- PORT (코드), PORT NAME, CA1~CA16 (선형 카테고리), FROM DATE, TO DATE
- 각 셀: 해당 항구 × 선형의 LUMPSUM 항비 (USD)

표준 출력 형식 (long format):
    port     port_name              category   port_charge   from_date    to_date
    BDCGP    BDCGP                  CA1        9000          2018-01-01   2999-12-31
    INPIP    INPIP                  CA1        10000         2018-01-01   2999-12-31

조회 메서드:
- get_charge(port, category, target_date)
- get_charge_by_teu(port, teu_size, target_date)  ← TEU로 자동 매칭
- get_available_ports()
"""

from datetime import date, datetime
from pathlib import Path
import pandas as pd
from .base import BaseDataLoader


class PortChargeLoader(BaseDataLoader):
    """항구별 선형별 항비 로더"""

    def _parse(self) -> pd.DataFrame:
        raw = pd.read_excel(
            self.file_path
        )

        # 카테고리 컬럼 추출 (CA로 시작)
        cat_cols = [c for c in raw.columns if str(c).startswith("CA")]

        records = []
        for _, row in raw.iterrows():
            port_code = row["PORT"]
            port_name = row.get("PORT NAME", port_code)
            from_dt = self._parse_date(row.get("FROM DATE"))
            to_dt = self._parse_date(row.get("TO DATE"))

            if pd.isna(port_code):
                continue

            for cat in cat_cols:
                val = row[cat]
                if pd.isna(val):
                    continue
                try:
                    charge = float(val)
                except (ValueError, TypeError):
                    continue
                records.append({
                    "port": str(port_code).strip(),
                    "port_name": str(port_name).strip(),
                    "category": cat,
                    "port_charge": charge,
                    "from_date": from_dt,
                    "to_date": to_dt,
                })

        return pd.DataFrame(records)

    @staticmethod
    def _parse_date(val) -> date | None:
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.date()
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        try:
            return pd.to_datetime(val).date()
        except (ValueError, TypeError):
            return None

    # ===== 조회 API =====
    def get_charge(
        self,
        port: str,
        category: str,
        target_date: date | None = None,
    ) -> float | None:
        """특정 항구/선형 카테고리/날짜의 항비"""
        df = self.load()
        mask = (df["port"] == port) & (df["category"] == category)
        if target_date is not None:
            mask = mask & (df["from_date"] <= target_date) & (df["to_date"] >= target_date)
        result = df[mask]
        if result.empty:
            return None
        return float(result.iloc[0]["port_charge"])

    def get_charge_by_teu(
        self,
        port: str,
        teu_size: int,
        target_date: date | None = None,
        category_mapping_fn=None,
    ) -> tuple[str, float] | None:
        """
        TEU 크기로 매칭되는 항비.
        category_mapping_fn: TEU → 카테고리 변환 함수 (없으면 내장 룰 사용)
        """
        if category_mapping_fn is not None:
            category = category_mapping_fn(teu_size)
        else:
            category = self._default_teu_to_category(teu_size)

        if category is None:
            return None

        charge = self.get_charge(port, category, target_date)
        if charge is None:
            # 카테고리가 해당 항구에 없으면 가장 가까운 카테고리로 폴백
            df = self.load()
            available = df[df["port"] == port]["category"].unique()
            if len(available) == 0:
                return None
            # CA 숫자 추출해서 가장 가까운 것
            target_num = int(category.replace("CA", ""))
            best_cat = min(
                available,
                key=lambda c: abs(int(c.replace("CA", "")) - target_num),
            )
            charge = self.get_charge(port, best_cat, target_date)
            if charge is None:
                return None
            return (best_cat, charge)

        return (category, charge)

    @staticmethod
    def _default_teu_to_category(teu_size: int) -> str | None:
        """
        TEU → CA 카테고리 기본 매핑 (HIRE 파일 기준).
        HIRE 파일의 NAME에서 추출한 대표 TEU 기준으로 구간 분할.
        """
        if teu_size <= 0:
            return None
        # HIRE 파일의 대표 TEU 기준 구간
        thresholds = [
            (1040, "CA1"),
            (1075, "CA2"),
            (1100, "CA3"),
            (1200, "CA4"),
            (1500, "CA5"),
            (1720, "CA6"),
            (1770, "CA7"),
            (1900, "CA8"),
            (2350, "CA9"),
            (2600, "CA10"),
            (2750, "CA11"),
            (3150, "CA12"),
            (3900, "CA13"),
            (4650, "CA14"),
            (5025, "CA15"),
            (5275, "CA16"),
        ]
        for upper, cat in thresholds:
            if teu_size <= upper:
                return cat
        return "CA16"  # PORT_CHARGE는 CA16까지만 있음

    def get_available_ports(self) -> list[dict]:
        df = self.load()
        unique = df[["port", "port_name"]].drop_duplicates()
        return unique.to_dict("records")

    def get_categories_for_port(self, port: str) -> list[str]:
        df = self.load()
        return sorted(df[df["port"] == port]["category"].unique().tolist())
