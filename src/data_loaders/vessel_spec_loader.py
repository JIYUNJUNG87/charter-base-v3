"""
선형 스펙 로더.

원본 '선종별_타입_스펙__엑셀_파일_.xlsx' 구조:
- 시트별로 TEU 구간 (1,100TEU, 1,700TEU, ..., 9K PLUS)
- 각 시트에 여러 조선소/타입이 컬럼별로 (예: Jiangsu 4250, Samsung 4000, ...)
- 행 구조 (대부분 시트에서 동일):
    행 0:  Type / Design (타입명 헤더)
    행 1:  Built (건조 연도)
    행 2:  Number of vessel
    행 3:  Yard (조선소/국가)
    행 4:  Design DWT
    행 5:  Design Draft
    행 6:  Scantling DWT
    행 7:  Scantling Draft
    행 8:  GRT
    행 9:  TEU nom.
    행 10: TEU 14t (적재 가능)
    행 14: LOA
    행 16: BEAM
    행 21~26: 선속별 소모량 (23/19/18/17/16/14 knot)
    행 27: aux engine at sea / in port

표준 출력 형식:
1) types_df: 타입 마스터
    teu_class    type_name           teu_nominal   loa     beam    aux_at_sea   aux_at_port
    4000-4600    Jiangsu 4250        4249          261     32.2    9.0          9.6
    4000-4600    Samsung 4000        4253          260.05  32.25   6.2          5.7

2) speed_consumption_df: 선속-소모량 커브 (long format)
    type_name        speed   consumption
    Jiangsu 4250     23      115.0
    Jiangsu 4250     19      70.5
    Jiangsu 4250     18      59.5

조회 메서드:
- get_consumption(type_name, speed)   ← 보간 지원
- get_aux_consumption(type_name, mode)  # 'at_sea' / 'in_port'
- get_type_info(type_name)
- find_types_by_teu(teu_size, tolerance=0.15)
"""

import re
from pathlib import Path
import pandas as pd
from .base import BaseDataLoader


# 선속 행 위치 (실제 데이터 셀에서 검증된 위치)
SPEED_ROWS = {
    21: 23,  # 행 21: 23노트
    22: 19,
    23: 18,
    24: 17,
    25: 16,
    26: 14,
}


class VesselSpecLoader(BaseDataLoader):
    """선형 스펙 로더 (다중 시트)"""

    def _parse(self) -> dict:
        all_sheets = pd.read_excel(self.file_path, sheet_name=None, header=None)

        types_records = []
        speed_records = []

        for sheet_name, df in all_sheets.items():
            sheet_types = self._parse_sheet(sheet_name, df)
            for t in sheet_types:
                types_records.append(t["info"])
                for sp, cons in t["speed_curve"].items():
                    speed_records.append({
                        "type_name": t["info"]["type_name"],
                        "speed": sp,
                        "consumption": cons,
                    })

        types_df = pd.DataFrame(types_records)
        speed_df = pd.DataFrame(speed_records)

        # === 보완 파일 자동 병합 ===
        # 같은 폴더에 vessel_spec_supplement.xlsx가 있으면 빈 값만 채워줌
        supplement_path = self.file_path.parent / "vessel_spec_supplement.xlsx"
        if supplement_path.exists():
            types_df, speed_df = self._merge_supplement(
                types_df, speed_df, supplement_path,
            )

        return {
            "types": types_df,
            "speed_consumption": speed_df,
        }

    def _merge_supplement(self, types_df: pd.DataFrame, speed_df: pd.DataFrame,
                          supplement_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        보완 파일을 원본에 병합.
        - types: 비어있는 값만 보완
        - speed_consumption: 새 (선형명, 속도) 페어만 추가
        """
        try:
            sup = pd.read_excel(supplement_path, sheet_name="선형 스펙 입력")
        except Exception as e:
            print(f"⚠️ 보완 파일 읽기 실패: {e}")
            return types_df, speed_df

        # 한글 컬럼명 → 영문 매핑
        col_map = {
            "선형명": "type_name",
            "TEU급": "teu_class",
            "디자인 TEU": "teu_nominal",
            "14T TEU": "teu_at_14t",
            "Aux 항해중(톤/일)": "aux_at_sea",
            "Aux 정박중(톤/일)": "aux_at_port",
        }
        # 속도별 컬럼: "23kt 소모량(톤/일)" → 23
        speed_cols = {}
        for col in sup.columns:
            if isinstance(col, str) and "kt 소모량" in col:
                try:
                    speed = int(col.split("kt")[0].strip())
                    speed_cols[col] = speed
                except ValueError:
                    continue

        sup = sup.rename(columns={k: v for k, v in col_map.items() if k in sup.columns})

        if "type_name" not in sup.columns:
            print(f"⚠️ 보완 파일에 '선형명' 컬럼이 없습니다.")
            return types_df, speed_df

        # 1) types_df 병합 (빈 값만 채움)
        supplement_cols = ["teu_nominal", "teu_at_14t", "aux_at_sea", "aux_at_port"]
        supplement_cols = [c for c in supplement_cols if c in sup.columns]

        merged = types_df.copy().set_index("type_name")
        sup_indexed = sup.set_index("type_name")

        filled_count = {}
        for col in supplement_cols:
            if col not in merged.columns:
                continue
            sup_vals = sup_indexed[col]
            mask = merged[col].isna() & merged.index.isin(sup_vals.index)
            filled = mask.sum()
            if filled > 0:
                merged.loc[mask, col] = sup_vals.loc[merged.index[mask]].values
                filled_count[col] = int(filled)

        types_df_new = merged.reset_index()

        # 2) speed_consumption 병합 (없는 페어만 추가)
        speed_added = 0
        new_speed_rows = []
        existing_pairs = set(zip(speed_df["type_name"], speed_df["speed"]))

        for _, sup_row in sup.iterrows():
            type_name = sup_row.get("type_name")
            if pd.isna(type_name):
                continue
            for orig_col, speed in speed_cols.items():
                val = sup_row.get(orig_col)
                if pd.isna(val) or val == 0:
                    continue
                # 이미 있으면 건드리지 않음 (원본 우선)
                if (type_name, speed) in existing_pairs:
                    continue
                new_speed_rows.append({
                    "type_name": type_name,
                    "speed": speed,
                    "consumption": float(val),
                })
                speed_added += 1

        if new_speed_rows:
            speed_df_new = pd.concat(
                [speed_df, pd.DataFrame(new_speed_rows)],
                ignore_index=True,
            )
        else:
            speed_df_new = speed_df

        # 출력
        if filled_count or speed_added:
            print(f"✅ vessel_spec_supplement.xlsx에서 보완:")
            for col, n in filled_count.items():
                print(f"   {col}: {n}개 선형")
            if speed_added:
                print(f"   속도별 소모량: {speed_added}개 페어 추가")

        return types_df_new, speed_df_new

    def _parse_sheet(self, sheet_name: str, df: pd.DataFrame) -> list[dict]:
        """한 시트에서 모든 타입 파싱"""
        types = []

        if len(df) < 20:
            return types  # 너무 짧은 시트 스킵 (9K PLUS는 38행이라 OK)

        # 타입 이름 추출 (행 0의 컬럼들)
        header_row = df.iloc[0]
        type_columns = {}  # col_idx → type_name
        for col_idx, val in enumerate(header_row):
            if col_idx == 0:
                continue
            if pd.isna(val):
                continue
            name = str(val).strip()
            if not name or "Unnamed" in name or name.lower() in ("type / design", "name"):
                continue
            type_columns[col_idx] = name

        # 시트 내 라벨 위치를 미리 매핑 (행 구조 자동 인식)
        label_map = self._build_label_map(df)

        for col_idx, type_name in type_columns.items():
            info = self._extract_type_info(sheet_name, type_name, df, col_idx, label_map)
            speed_curve = self._extract_speed_curve(df, col_idx)
            if not speed_curve:
                continue
            types.append({
                "info": info,
                "speed_curve": speed_curve,
            })

        return types

    @staticmethod
    def _build_label_map(df: pd.DataFrame) -> dict:
        """
        시트의 첫 두 열(라벨)을 스캔해서 각 항목의 행 인덱스를 찾아냄.
        시트마다 행 구조가 달라서 고정 인덱스 사용이 위험함.

        Returns: {"teu_nominal": 9, "teu_at_14t": 10, ...}
        """
        result = {}
        for row_idx in range(min(30, len(df))):
            col0 = str(df.iloc[row_idx, 0]).strip().lower() if pd.notna(df.iloc[row_idx, 0]) else ""
            col1 = ""
            if df.shape[1] > 1 and pd.notna(df.iloc[row_idx, 1]):
                col1 = str(df.iloc[row_idx, 1]).strip().lower()

            # TEU nom.
            if (col0 == "teu" and col1 in ("nom.", "nom")) or col1 == "nom.":
                result["teu_nominal"] = row_idx
            # TEU 14t
            elif col1 in ("14t", "14ton", "14 t"):
                result["teu_at_14t"] = row_idx
            # LOA
            elif col0 == "loa":
                result["loa"] = row_idx
            # BEAM
            elif col0 in ("beam", "breadth"):
                result["beam"] = row_idx
            # Design DWT
            elif col0 == "design" and col1 == "dwt":
                result["design_dwt"] = row_idx
            elif col0 == "dwt" and col1 in ("design",):
                result["design_dwt"] = row_idx
            # Design DRAFT
            elif col0 == "design" and col1 == "draft":
                result["design_draft"] = row_idx
            elif col0 == "draft" and col1 == "design":
                result["design_draft"] = row_idx
            # Scantling DWT
            elif col0 == "scantling" and col1 == "dwt":
                result["scantling_dwt"] = row_idx
            elif col0 == "dwt" and col1 in ("scant.", "scant"):
                result["scantling_dwt"] = row_idx
            # Scantling DRAFT
            elif col0 == "scantling" and col1 == "draft":
                result["scantling_draft"] = row_idx
            elif col0 == "draft" and col1 in ("scant.", "scant"):
                result["scantling_draft"] = row_idx
            # GRT
            elif col0 == "grt":
                result["grt"] = row_idx
            # Year built
            elif col0 == "built":
                result["built"] = row_idx
            # Yard
            elif col0 == "yard":
                result["yard"] = row_idx

        return result

    def _extract_type_info(
        self, sheet_name: str, type_name: str, df: pd.DataFrame, col_idx: int,
        label_map: dict = None,
    ) -> dict:
        """타입의 기본 정보 추출 (라벨 위치 기반)"""
        if label_map is None:
            label_map = {}

        def safe_get(row_idx, default=None):
            if row_idx is None or row_idx >= len(df):
                return default
            val = df.iloc[row_idx, col_idx]
            return val if pd.notna(val) else default

        def safe_float(row_idx, default=None):
            v = safe_get(row_idx)
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        # aux engine: 마지막쯤에 "9.0 / 9.6" 형식 (at sea / in port)
        # 표준 시트에서는 27행 근처에 있음. 9K PLUS는 없을 수 있음.
        aux_str = ""
        # aux 위치 자동 탐색 (라벨에 'aux' 포함된 행 찾기)
        for row_idx in range(min(40, len(df))):
            col0 = str(df.iloc[row_idx, 0]).strip().lower() if pd.notna(df.iloc[row_idx, 0]) else ""
            if "aux" in col0:
                aux_str = str(safe_get(row_idx, ""))
                break
        if not aux_str:
            # 백업: 표준 위치 (27)
            aux_str = str(safe_get(27, ""))
        aux_at_sea, aux_at_port = self._parse_aux_engine(aux_str)

        return {
            "teu_class": sheet_name,
            "type_name": type_name,
            "built": str(safe_get(label_map.get("built"), "")),
            "yard": str(safe_get(label_map.get("yard"), "")),
            "design_dwt": safe_float(label_map.get("design_dwt")),
            "design_draft": safe_float(label_map.get("design_draft")),
            "scantling_dwt": safe_float(label_map.get("scantling_dwt")),
            "scantling_draft": safe_float(label_map.get("scantling_draft")),
            "grt": safe_float(label_map.get("grt")),
            "teu_nominal": safe_float(label_map.get("teu_nominal")),
            "teu_at_14t": safe_float(label_map.get("teu_at_14t")),
            "loa": safe_float(label_map.get("loa")),
            "beam": safe_float(label_map.get("beam")),
            "aux_at_sea": aux_at_sea,
            "aux_at_port": aux_at_port,
        }

    @staticmethod
    def _parse_aux_engine(s: str) -> tuple[float | None, float | None]:
        """'9.0 / 9.6' → (9.0, 9.6)"""
        if not s or s == "nan":
            return (None, None)
        m = re.match(r"\s*([\d.]+)\s*/\s*([\d.]+)", s)
        if m:
            try:
                return (float(m.group(1)), float(m.group(2)))
            except ValueError:
                return (None, None)
        return (None, None)

    def _extract_speed_curve(self, df: pd.DataFrame, col_idx: int) -> dict:
        """
        선속-소모량 커브 추출.
        시트마다 행 위치가 다를 수 있어서 라벨(첫 두 열)을 보고 속도 행을 동적 탐색.

        속도 라벨 위치:
        - 표준 시트: 행21~26 (23/19/18/17/16/14)
        - 9K PLUS: 행23~37 (10~23 다양)
        """
        curve = {}

        for row_idx in range(15, min(50, len(df))):
            # 속도 값 찾기 - 열0 또는 열1에 숫자형 속도가 있는지
            speed_val = None
            col0 = df.iloc[row_idx, 0] if pd.notna(df.iloc[row_idx, 0]) else None
            col1 = df.iloc[row_idx, 1] if df.shape[1] > 1 and pd.notna(df.iloc[row_idx, 1]) else None

            # 열0 또는 열1에서 속도 추출 시도
            for candidate in [col1, col0]:
                if candidate is None:
                    continue
                try:
                    v = float(candidate)
                    if 5 <= v <= 30:  # 합리적인 속도 범위
                        speed_val = v
                        break
                except (ValueError, TypeError):
                    continue

            if speed_val is None:
                continue

            # 해당 행, col_idx 컬럼에서 소모량 추출
            val = df.iloc[row_idx, col_idx]
            if pd.isna(val):
                continue
            if isinstance(val, str) and val.strip() in ("-", "", "N/A", "n/a"):
                continue
            try:
                consumption = float(val)
                if consumption > 0:
                    # 정수 속도면 정수로 변환 (15.0 → 15)
                    speed_key = int(speed_val) if speed_val == int(speed_val) else speed_val
                    curve[speed_key] = consumption
            except (ValueError, TypeError):
                continue

        return curve

    # ===== 조회 API =====
    def get_types(self) -> pd.DataFrame:
        return self.load()["types"]

    def get_speed_consumption(self) -> pd.DataFrame:
        return self.load()["speed_consumption"]

    def get_type_info(self, type_name: str) -> dict | None:
        df = self.get_types()
        result = df[df["type_name"] == type_name]
        if result.empty:
            return None
        return result.iloc[0].to_dict()

    def get_consumption(self, type_name: str, speed: float) -> float | None:
        """
        주어진 선속에서의 소모량 (ton/day).
        스펙에 없는 선속이면 선형 보간으로 추정.
        """
        df = self.get_speed_consumption()
        sub = df[df["type_name"] == type_name].sort_values("speed")
        if sub.empty:
            return None

        speeds = sub["speed"].tolist()
        cons = sub["consumption"].tolist()

        # 정확히 일치
        if speed in speeds:
            return cons[speeds.index(speed)]

        # 범위 밖은 가장 가까운 값
        if speed <= speeds[0]:
            return cons[0]
        if speed >= speeds[-1]:
            return cons[-1]

        # 선형 보간
        for i in range(len(speeds) - 1):
            s1, s2 = speeds[i], speeds[i + 1]
            if s1 <= speed <= s2:
                c1, c2 = cons[i], cons[i + 1]
                # 보간
                ratio = (speed - s1) / (s2 - s1)
                return c1 + (c2 - c1) * ratio
        return None

    def get_aux_consumption(
        self, type_name: str, mode: str = "at_sea"
    ) -> float | None:
        """보조엔진 소모량. mode = 'at_sea' or 'in_port' (또는 'at_port')"""
        info = self.get_type_info(type_name)
        if info is None:
            return None
        # 'in_port'와 'at_port'를 모두 'at_port' 키로 매핑
        if mode in ("in_port", "at_port"):
            return info.get("aux_at_port")
        return info.get(f"aux_{mode}")

    def find_types_by_teu(
        self, teu_size: int, tolerance: float = 0.15
    ) -> pd.DataFrame:
        """TEU ±tolerance 범위 내의 타입들"""
        df = self.get_types()
        df = df.dropna(subset=["teu_nominal"])
        lower = teu_size * (1 - tolerance)
        upper = teu_size * (1 + tolerance)
        return df[(df["teu_nominal"] >= lower) & (df["teu_nominal"] <= upper)]

    def get_teu_classes(self) -> list[str]:
        return sorted(self.get_types()["teu_class"].unique().tolist())
