"""
데이터 로더 공통 베이스.

원본 Excel 파일들을 깨끗한 표준 형식으로 변환해주는 로더들의 공통 인터페이스.

설계 원칙:
- 원본 Excel은 데이터 셀이 병합되어 있거나 헤더가 여러 줄이거나 깔끔하지 않음
- 각 로더는 원본의 양식이 어떻든 표준화된 DataFrame 또는 dict로 변환
- 이후 계산기 모듈들은 표준 형식만 알면 됨 (원본 양식 변경에도 영향 없음)
- 캐싱: 한 번 읽으면 메모리에 보관 (Excel 읽기는 느림)
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd


def read_excel_auto(file_path: Path, **kwargs) -> pd.DataFrame | dict:
    """
    Excel 파일 자동 감지 읽기.
    확장자가 .xls여도 실제 xlsx인 경우, 또는 그 반대인 경우 자동 처리.
    """
    try:
        return pd.read_excel(file_path, **kwargs)
    except Exception:
        # 엔진 지정해서 재시도
        for engine in ("openpyxl", "xlrd"):
            try:
                return pd.read_excel(file_path, engine=engine, **kwargs)
            except Exception:
                continue
        raise


class BaseDataLoader(ABC):
    """모든 데이터 로더의 베이스"""

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {self.file_path}")
        self._cache: Any = None

    def load(self) -> Any:
        """데이터 로드 (캐싱)"""
        if self._cache is None:
            self._cache = self._parse()
        return self._cache

    def reload(self) -> Any:
        """캐시 무시하고 재로드 (파일 갱신 시 사용)"""
        self._cache = None
        return self.load()

    @abstractmethod
    def _parse(self) -> Any:
        """실제 파싱 로직. 하위 클래스에서 구현."""
        pass
