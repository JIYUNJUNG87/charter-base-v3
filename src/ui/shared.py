"""
공통 캐시된 리소스 (모든 UI 페이지가 공유).

각 페이지마다 @st.cache_resource로 함수를 따로 정의하면
인스턴스가 페이지별로 분리되어 마법사→대시보드 데이터 공유가 안됨.
이 모듈을 통해 단일 인스턴스 공유 보장.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import streamlit as st
from src.data_loaders import MasterDataManager
from src.cost_calculators import VoyageCostIntegrator
from src.wizard import ProformaBuilder
from src.wizard.distance_matrix import DistanceMatrix
from src.engine.scenario_compare import ScenarioComparator
from src.datasources.base import DataSourceFactory


# 기본 데이터 소스 (대시보드와 동일하게 mock 사용)
import os
DATA_SOURCE = os.getenv("DATA_SOURCE", "mock")


@st.cache_resource
def get_data_manager():
    """모든 페이지가 공유하는 단일 MasterDataManager"""
    return MasterDataManager()


@st.cache_resource
def get_integrator():
    return VoyageCostIntegrator(get_data_manager())


@st.cache_resource
def get_builder():
    return ProformaBuilder(get_data_manager())


@st.cache_resource
def get_distance_matrix():
    return DistanceMatrix(get_data_manager())


@st.cache_resource
def get_comparator():
    return ScenarioComparator(get_data_manager())


@st.cache_resource
def get_baseline_source():
    return DataSourceFactory.create(DATA_SOURCE)
