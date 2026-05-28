# data/master_demo/

**합성 데이터입니다. 실제 운영 수치 아닙니다.**

이 폴더의 BUNKER/HIRE/PORT_CHARGE/SERVICE_LIST/vessel_spec 파일은
`scripts/generate_demo_data.py` 로 생성한 데모용 더미입니다.

목적:
- Streamlit Community Cloud 등 외부 환경에 회사 운영 데이터(`data/master/`)를
  올리지 않고도 앱을 시연할 수 있게 함
- 스키마(시트/컬럼 구조)는 실제 파일과 동일하므로 로더가 그대로 동작

`MasterDataManager()` 호출 시 우선순위:
1. 인자로 명시한 master_dir
2. 환경변수 `CHARTERBASE_MASTER_DIR`
3. `data/master/` (실데이터)
4. `data/master_demo/` (이 폴더, 폴백)

실데이터를 데모로 덮어쓰지 않도록 절대 이 폴더에 실수치를 넣지 마세요.
재생성이 필요하면 `python scripts/generate_demo_data.py` 실행.
