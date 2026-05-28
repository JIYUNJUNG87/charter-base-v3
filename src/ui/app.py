"""
메인 진입점.
st.navigation으로 페이지 순서 명시적 제어.

순서 (사이드바 표시 순):
  1. 신규 항로 마법사 (Wizard)
  2. 차터베이스 대시보드 (Dashboard)
  3. 시나리오 비교 (Scenario Compare) - SMX 업사이징 같은 다중 비교
  4. AI 리포트 (AI Report)

실행: streamlit run src/ui/app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import streamlit as st


wizard_page = st.Page(
    "pages/route_wizard.py",
    title="신규 항로 마법사",
    icon="🆕",
    default=True,
)

dashboard_page = st.Page(
    "dashboard.py",
    title="차터베이스 대시보드",
    icon="🚢",
)

scenario_page = st.Page(
    "pages/scenario_compare.py",
    title="시나리오 비교",
    icon="🔀",
)

report_page = st.Page(
    "pages/ai_report.py",
    title="AI 리포트",
    icon="🤖",
)

pg = st.navigation([wizard_page, dashboard_page, scenario_page, report_page])
pg.run()
