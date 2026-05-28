"""
HIRE (HRCI 용선료 지수) 로더.

원본 HIRE.xls 구조:
- 1열: YEAR, 2열: CATEGORY (CA1~CA20), 3열: NAME (선형 명세)
- 4열~: 월별 일일 용선료 (USD/day), Grand Total 포함

표준 출력 형식:
1) categories_df: 카테고리 마스터
    category   teu     name                          design
    CA1        1030    1,030teu Ice(2.5%)            Ice / 2.5%
    CA6        1700    1,700teu Gless Topaz (5.0%)   Gless Topaz / 5.0%

2) hire_rates_df: long format 용선료
    year   month   category   daily_rate
    2026   Jan     CA1        18000
    2026   Feb     CA1        20000

조회 메서드:
- get_rate(year, month, category)
- get_rate_by_teu(year, month, teu_size)  ← TEU 크기로 자동 매칭
- get_categories()
"""

import re
from datetime import date
from pathlib import Path
import pandas as pd
from .base import BaseDataLoader


class HireRateLoader(BaseDataLoader):
    """HRCI 용선료 로더"""

    def _parse(self) -> dict:
        raw = pd.read_excel(
            self.file_path
        )

        # 첫 행이 헤더 역할 (YEAR, CATEGORY, NAME, MONTH...)
        # raw.columns[3] 이후가 월 컬럼

        # 1) 헤더 행을 정리
        header_row = raw.iloc[0]
        # 컬럼명 직접 매핑
        # 원본: ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'MONTH', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6']
        # 1행: ['YEAR', 'CATEGORY', 'NAME', 'Jan-26', None, 'Feb-26', 'Grand Total']

        month_cols = {}  # col_idx → "Jan-26" 같은 라벨
        for i, val in enumerate(header_row):
            if pd.isna(val):
                continue
            s = str(val).strip()
            # 월 형식 (Jan-26, Feb-26 등)
            if re.match(r"^[A-Za-z]{3}-\d{2}$", s):
                month_cols[i] = s
            # Grand Total
            elif s.lower() == "grand total":
                month_cols[i] = "Total"

        # 데이터 행 (행 1부터 시작, 마지막 'YEAR Total' 행 제외)
        categories = []
        rates = []

        year_val = None
        for idx in range(1, len(raw)):
            row = raw.iloc[idx]
            # YEAR 열
            year_cell = row.iloc[0]
            cat_cell = row.iloc[1]
            name_cell = row.iloc[2]

            if pd.notna(year_cell):
                try:
                    year_val = int(year_cell)
                except (ValueError, TypeError):
                    # "2026 Total" 같은 합계 행이면 종료
                    break

            if pd.isna(cat_cell):
                continue

            category = str(cat_cell).strip()
            name = str(name_cell).strip() if pd.notna(name_cell) else ""

            # TEU 사이즈 파싱 (예: "1,030teu Ice(2.5%)" → 1030)
            teu_size = self._extract_teu(name)
            design = self._extract_design(name)

            categories.append({
                "category": category,
                "teu": teu_size,
                "name": name,
                "design": design,
            })

            # 월별 단가
            for col_idx, month_label in month_cols.items():
                val = row.iloc[col_idx]
                if pd.isna(val):
                    continue
                try:
                    rate = float(val)
                except (ValueError, TypeError):
                    continue

                if month_label == "Total":
                    continue  # 평균값은 별도 처리 가능, 우선 제외

                # 월 라벨 파싱 (Jan-26)
                month_date = self._parse_month_label(month_label, year_val)
                rates.append({
                    "year": year_val,
                    "month": month_date,
                    "month_label": month_label,
                    "category": category,
                    "daily_rate": rate,
                })

        categories_df = pd.DataFrame(categories).drop_duplicates(subset=["category"])
        rates_df = pd.DataFrame(rates)

        return {
            "categories": categories_df,
            "rates": rates_df,
        }

    @staticmethod
    def _extract_teu(name: str) -> int | None:
        """'1,030teu Ice(2.5%)' → 1030"""
        m = re.search(r"(\d[\d,]*)\s*teu", name, re.IGNORECASE)
        if not m:
            # '8500 GL' 처럼 teu 없는 경우
            m = re.search(r"^\s*(\d[\d,]*)\b", name)
        if not m:
            return None
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _extract_design(name: str) -> str:
        """선형 명세에서 디자인 추출 (TEU 다음 부분)"""
        # '1,030teu Ice(2.5%)' → 'Ice(2.5%)'
        m = re.search(r"teu\s+(.*)", name, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return name

    @staticmethod
    def _parse_month_label(label: str, year: int) -> date | None:
        """Jan-26 → 2026-01-01"""
        try:
            return pd.to_datetime(label, format="%b-%y").date()
        except (ValueError, TypeError):
            return None

    # ===== 조회 API =====
    def get_categories(self) -> pd.DataFrame:
        return self.load()["categories"]

    def get_rates(self) -> pd.DataFrame:
        return self.load()["rates"]

    def get_rate(self, year: int, month: int, category: str) -> float | None:
        """특정 연/월/카테고리의 일일 용선료"""
        df = self.get_rates()
        # 월 라벨 만들기
        target = date(year, month, 1)
        mask = (df["month"] == target) & (df["category"] == category)
        result = df[mask]
        if result.empty:
            return None
        return float(result.iloc[0]["daily_rate"])

    def get_rate_by_teu(
        self, year: int, month: int, teu_size: int
    ) -> tuple[str, float] | None:
        """
        TEU 크기로 가장 근사한 카테고리를 찾아 용선료 반환.
        반환: (매칭된 카테고리, 일일 용선료)
        """
        cats = self.get_categories()
        cats_with_teu = cats.dropna(subset=["teu"]).copy()
        if cats_with_teu.empty:
            return None
        # TEU 차이 절대값이 가장 작은 카테고리
        cats_with_teu["diff"] = (cats_with_teu["teu"] - teu_size).abs()
        best = cats_with_teu.sort_values("diff").iloc[0]
        category = best["category"]
        rate = self.get_rate(year, month, category)
        if rate is None:
            return None
        return (category, rate)

    def get_category_for_teu(self, teu_size: int) -> str | None:
        """TEU 크기로 가장 근사한 카테고리 코드만 반환"""
        cats = self.get_categories().dropna(subset=["teu"]).copy()
        if cats.empty:
            return None
        cats["diff"] = (cats["teu"] - teu_size).abs()
        return cats.sort_values("diff").iloc[0]["category"]
