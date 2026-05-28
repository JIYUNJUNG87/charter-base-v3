"""
AI 리포트 베이스 클래스.

설계 원칙:
1. API 키 없으면 템플릿 기반 리포트 자동 생성
2. API 키 있으면 Claude API로 풍부한 분석
3. 데이터 마스킹 옵션 (보안 정책에 따라)
4. 숫자/표는 코드가 직접 생성 → AI 환각 방지
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReportConfig:
    """리포트 생성 설정"""
    api_key: Optional[str] = None
    model: str = "claude-opus-4-7"
    max_tokens: int = 2000
    use_template_fallback: bool = True   # API 실패/없을 시 템플릿 사용
    mask_sensitive_data: bool = False    # 매출/원가 마스킹 여부
    language: str = "ko"                  # 한국어/영어

    def has_api(self) -> bool:
        if self.api_key:
            return True
        # 환경변수 확인
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def get_api_key(self) -> Optional[str]:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY")


@dataclass
class ReportResult:
    """리포트 결과"""
    content: str                          # 마크다운 형식 리포트
    generated_by: str = "template"        # "template" 또는 "claude"
    model_used: str = ""
    warnings: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)  # 디버깅용


class BaseReportGenerator(ABC):
    """모든 리포트 생성기의 베이스"""

    def __init__(self, config: ReportConfig = None):
        self.config = config or ReportConfig()

    @abstractmethod
    def _build_template(self, data: dict) -> str:
        """템플릿 기반 리포트 (API 없이)"""
        pass

    @abstractmethod
    def _build_prompt(self, data: dict) -> str:
        """Claude API용 프롬프트"""
        pass

    def generate(self, data: dict) -> ReportResult:
        """리포트 생성. API 가능하면 Claude, 아니면 템플릿."""
        warnings = []

        # 데이터 마스킹
        if self.config.mask_sensitive_data:
            data = self._mask_data(data)
            warnings.append("민감 데이터 마스킹 적용됨")

        # API 시도
        if self.config.has_api():
            try:
                content = self._call_claude(data)
                return ReportResult(
                    content=content,
                    generated_by="claude",
                    model_used=self.config.model,
                    warnings=warnings,
                    raw_data=data,
                )
            except Exception as e:
                warnings.append(f"API 호출 실패: {e}, 템플릿으로 대체")
                if not self.config.use_template_fallback:
                    raise

        # 템플릿 fallback
        content = self._build_template(data)
        if not self.config.has_api():
            warnings.append("API 키 없음 - 템플릿 기반 리포트 생성")

        return ReportResult(
            content=content,
            generated_by="template",
            warnings=warnings,
            raw_data=data,
        )

    def _call_claude(self, data: dict) -> str:
        """Claude API 호출"""
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("`pip install anthropic` 필요")

        client = Anthropic(api_key=self.config.get_api_key())
        prompt = self._build_prompt(data)

        message = client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        # 첫 번째 text 블록만 추출
        for block in message.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    def _mask_data(self, data: dict) -> dict:
        """민감 데이터 마스킹 (금액을 비율로 변환 등)"""
        # 깊은 복사 후 마스킹
        import copy
        masked = copy.deepcopy(data)

        # 금액 관련 키를 비율로 변환
        sensitive_keys = {"total_revenue", "operating_profit", "freight_revenue",
                         "fuel_cost", "port_charge", "charter_hire"}

        def mask_dict(d, depth=0):
            if not isinstance(d, dict):
                return d
            for k, v in d.items():
                if k in sensitive_keys and isinstance(v, (int, float)):
                    # 단위 변환: 실제 금액 대신 "백만 USD 단위"로
                    d[k] = round(v / 1_000_000, 2)
                elif isinstance(v, dict):
                    mask_dict(v, depth + 1)
            return d

        mask_dict(masked)
        return masked
