"""
설정 파일. DATA_SOURCE 값만 바꾸면 ERP 연결로 전환됩니다.
"""

DATA_SOURCE = "mock"  # "mock" / "oracle" / "api"

ORACLE_CONFIG = {
    "user": "your_user",
    "password": "your_password",
    "dsn": "host:port/service_name",
}

API_CONFIG = {
    "base_url": "https://erp.yourcompany.com/api/v1",
    "auth_token": "",
    "timeout": 30,
}

ANTHROPIC_API_KEY = ""
AI_MODEL = "claude-opus-4-7"


# ============================================================
# 연료 계산 가정값 (FUEL_ASSUMPTIONS)
# ============================================================
# 운항팀에 명시적 기준이 없어서 업계 일반 가정값을 사용 중.
# 실제 운항 데이터 누적되면 이 값들을 검증/조정할 것.
FUEL_ASSUMPTIONS = {
    # Maneuvering 시 메인엔진 소모량 = 설계 선속 소모량 × 이 비율
    # 업계 일반값: 30~50%, 표준값 40% 사용
    "manv_main_engine_ratio": 0.40,

    # Maneuvering 시 사용할 기준 선속 (design speed)
    # None이면 해당 선형의 최고 등재 선속 사용
    "manv_reference_speed": None,

    # Buffer 구간(SEABUFF)을 어떻게 처리할지
    # "in_port": 정박과 동일 (보조엔진만)
    # "at_sea": 항해와 동일 (메인+보조)
    "buffer_mode": "in_port",

    # 항해 중 메인엔진 외에 보조엔진도 가동
    "include_aux_at_sea": True,
}

# ============================================================
# 연료 단가 기본 설정
# ============================================================
FUEL_PRICE_DEFAULTS = {
    # 기본 사용 유종 (LSFO = Low Sulfur Fuel Oil, IMO 2020 규제 대응)
    "default_fuel_type": "LSFO",

    # 항구 코드 → BUNKER 파일의 단가 항구 매핑
    # 실제 항구가 BUNKER 단가 항구 목록에 없으면 가장 가까운 단가 항구를 사용
    "port_to_bunker_port": {
        # 한국
        "KRPUS": "KOR", "KRINC": "KOR", "KRKAN": "KOR", "KRUSN": "KOR",
        # 중국
        "CNSHA": "SHA", "CNNGB": "SHA", "CNSHK": "SHA",
        # 홍콩
        "HKHKG": "HKG",
        # 싱가포르 (동남아 기본)
        "SGSIN": "SIN", "VNSGN": "SIN", "VNHPH": "SIN", "THLCH": "SIN",
        "IDJKT": "SIN", "MYPKL": "SIN", "PHMNL": "SIN",
        # 푸자이라 (중동 기본)
        "AEFJR": "FJR", "AEDXB": "FJR", "AEAUH": "FJR",
        # 러시아
        "RUVST": "RUS", "RUVVO": "RUS",
        # 인도/파키스탄 (중동 단가 사용)
        "INNSA": "FJR", "INMUN": "FJR", "PKKHI": "FJR",
    },

    # 매핑되지 않은 항구의 fallback 단가 항구
    "fallback_bunker_port": "SIN",
}
