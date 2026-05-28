"""AI 리포트 모듈"""
from .base import BaseReportGenerator, ReportConfig, ReportResult
from .simulation_report import SimulationReportGenerator
from .vessel_recommendation import VesselRecommendationGenerator

__all__ = [
    "BaseReportGenerator", "ReportConfig", "ReportResult",
    "SimulationReportGenerator", "VesselRecommendationGenerator",
]
