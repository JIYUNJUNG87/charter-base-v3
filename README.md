# 차터베이스 시뮬레이션 시스템

회사 차터베이스(Charter Base) 화면의 양식을 그대로 유지하면서,
4가지 핵심 시뮬레이션을 빠르게 돌릴 수 있는 보조 도구입니다.

## 4가지 시뮬레이션 케이스

1. **운임 변동** - 방향별(E/W) 독립 조정 가능
2. **유가 변동** - 양방향 공통 적용
3. **선적량 변동** - 방향별 독립, 매출+화물변동비 동시 반영
4. **투입 선형 변경** - 선복량/용선료/연료비 일괄 변경

## 차터베이스 양식 호환

- East/West 양방향 분리 + 합계
- 5단계 손익: 매출 → 한계이익 → 운항이익
- 화물변동비/운항변동비/운항고정비 구분
- 포트 페어별 데이터 매트릭스
- COC/SOC 컨테이너 구분

## 실행

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 테스트
python tests/test_simulation.py

# 대시보드 실행
streamlit run src/ui/dashboard.py
```

## 데이터 소스 전환

`config.py`의 `DATA_SOURCE` 한 줄만 변경:
- `"mock"` : 차터베이스 화면 데이터 모사 (현재)
- `"oracle"` : Oracle DB 직접 연결 (DB 계정 발급 후)
- `"api"` : ERP REST API (API 발급 후)

엔진/UI 코드는 변경 없음.

## 위치

차터베이스(ERP) = 확정 실적의 단일 진실 공급원 (유지)
이 시스템 = 차터베이스 데이터를 베이스라인으로 받아 What-if 시뮬레이션만 수행

차터베이스를 대체하지 않고, 그 위에서 시나리오를 빠르게 돌리는 보조 도구로 작동.
