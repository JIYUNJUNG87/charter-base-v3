"""
더미(데모) 마스터 데이터 생성기.

목적: Streamlit Community Cloud 같은 외부 환경에서 실제 회사 운영 데이터
(BUNKER/HIRE/PORT_CHARGE/SERVICE_LIST/vessel_spec) 없이도 앱이 정상 동작하도록,
스키마는 동일하지만 수치는 합성된 데모용 Excel 5종을 생성한다.

생성 위치: data/master_demo/
실제 데이터(data/master/)는 건드리지 않으며, manager.py 가 실데이터가 없을 때만
data/master_demo/ 로 폴백한다.

사용:
    python scripts/generate_demo_data.py
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import random

import pandas as pd
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "master_demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 재현 가능한 데모 값
random.seed(42)


# ---------------------------------------------------------------------------
# 1. BUNKER.xls  (PLATTS 유가, MultiIndex header)
# ---------------------------------------------------------------------------
def generate_bunker() -> None:
    fuels = ["380CST", "180CST", "LSFO", "MGO", "LSMGO", "MOPS"]
    ports = ["SIN", "KOR", "HKG", "RUS", "FJR", "SHA"]

    # 유종별 기준가 (USD/ton). 합성치.
    base_prices = {
        "380CST": 380, "180CST": 410, "LSFO": 560,
        "MGO": 720, "LSMGO": 750, "MOPS": 600,
    }
    # 항구별 프리미엄/디스카운트
    port_adj = {"SIN": 0, "KOR": 15, "HKG": 25, "RUS": -10, "FJR": -5, "SHA": 10}

    # pandas 는 MultiIndex 컬럼 + index=False 쓰기를 지원하지 않으므로 openpyxl 직접 사용.
    # loader (bunker_loader.py) 는 header=[0,1] 로 2줄 헤더를 기대한다.
    wb = Workbook()
    ws = wb.active
    ws.title = "BUNKER"

    # 1행: DATE + 유종 헤더 (각 유종이 6번씩 반복되어야 read_excel header=[0,1]에서
    # MultiIndex 로 정상 인식됨; 병합 셀 없어도 동작.)
    header_row1 = ["DATE"] + [f for f in fuels for _ in ports]
    # 2행: (공백) + 항구 코드
    header_row2 = [""] + [p for _ in fuels for p in ports]
    ws.append(header_row1)
    ws.append(header_row2)

    start = date(2026, 1, 2)
    n_pairs = 0
    for i in range(30):
        d = start + timedelta(days=i)
        row_vals = [int(d.strftime("%Y%m%d"))]
        for f in fuels:
            for p in ports:
                drift = (i - 15) * 0.3
                noise = random.uniform(-4, 4)
                price = round(base_prices[f] + port_adj[p] + drift + noise, 1)
                row_vals.append(price)
                if i == 0:
                    n_pairs += 1
        ws.append(row_vals)

    wb.save(OUT_DIR / "BUNKER.xls")
    print(f"  BUNKER.xls  : 30 days x {n_pairs} fuel/port pairs")


# ---------------------------------------------------------------------------
# 2. HIRE.xls  (HRCI 용선료, CA1..CA20 x 월별)
# ---------------------------------------------------------------------------
def generate_hire() -> None:
    # (category, teu, name)
    cats = [
        ("CA1", 1030, "1,030teu Ice(2.5%)"),
        ("CA2", 1075, "1,075teu Std"),
        ("CA3", 1100, "1,100teu Wide"),
        ("CA4", 1200, "1,200teu Ice"),
        ("CA5", 1500, "1,500teu Std"),
        ("CA6", 1700, "1,700teu Gless Topaz (5.0%)"),
        ("CA7", 1770, "1,770teu Std"),
        ("CA8", 1900, "1,900teu Wide"),
        ("CA9", 2350, "2,350teu Std"),
        ("CA10", 2600, "2,600teu Std"),
        ("CA11", 2750, "2,750teu Wide"),
        ("CA12", 3150, "3,150teu Std"),
        ("CA13", 3900, "3,900teu Wide"),
        ("CA14", 4650, "4,650teu Std"),
        ("CA15", 5000, "5,000teu Std"),
        ("CA16", 5275, "5,275teu Wide"),
        ("CA17", 5500, "5,500teu Std"),
        ("CA18", 6500, "6,500teu Std"),
        ("CA19", 7000, "7,000teu Std"),
        ("CA20", 8500, "8,500teu GL"),
    ]
    months = [f"{m}-26" for m in
              ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]]

    # 원본 HIRE.xls 는 2단 헤더:
    #   Excel row 0 (pandas header): 거의 비어있고 col 3 만 "MONTH"
    #   Excel row 1 (raw.iloc[0])  : 실제 라벨 'YEAR','CATEGORY','NAME', Jan-26, ..., Grand Total
    #   Excel row 2+               : 데이터
    # pandas.read_excel 기본 header=0 이 첫 행을 컬럼명으로 흡수하므로
    # 더미 첫 행 → 실제 헤더 행 → 데이터 행 순서로 써준다.
    rows: list[list] = []
    n_cols = 3 + len(months) + 1
    dummy_top = [None] * n_cols
    dummy_top[3] = "MONTH"  # 원본 파일이 col 3 에 "MONTH" 표시
    rows.append(dummy_top)

    header = ["YEAR", "CATEGORY", "NAME"] + months + ["Grand Total"]
    rows.append(header)

    for i, (cat, teu, name) in enumerate(cats):
        # TEU 클수록 용선료 상승 (대략 USD/day)
        base = 8000 + teu * 4
        year_cell = 2026 if i == 0 else None
        monthly = [round(base + random.uniform(-1500, 1500), -2) for _ in months]
        total = round(sum(monthly) / len(monthly), -2)
        rows.append([year_cell, cat, name, *monthly, total])

    # 합계 행 (loader는 '2026 Total' 같은 라벨 만나면 break)
    rows.append(["2026 Total", None, None, *[None]*12, None])

    # 첫 row 가 헤더가 아니라 데이터의 0번째 row 로 들어가야 한다.
    # loader 는 raw.iloc[0] 을 header_row 로 사용 -> 그러므로 dummy column 헤더 + 첫 데이터행이 헤더
    df = pd.DataFrame(rows)
    df.to_excel(OUT_DIR / "HIRE.xls", index=False, header=False,
                engine="openpyxl")
    print(f"  HIRE.xls    : {len(cats)} categories x {len(months)} months")


# ---------------------------------------------------------------------------
# 3. PORT_CHARGE.xls  (항구 x 선형 카테고리 항비, USD)
# ---------------------------------------------------------------------------
def generate_port_charge() -> None:
    ports = [
        ("KRPUS", "Busan"), ("KRINC", "Incheon"), ("KRKAN", "Kwangyang"),
        ("CNSHA", "Shanghai"), ("CNNGB", "Ningbo"), ("HKHKG", "Hong Kong"),
        ("SGSIN", "Singapore"), ("JPYAT", "Yokohama"),
        ("VNSGN", "Ho Chi Minh"), ("THLCH", "Laem Chabang"),
        ("IDJKT", "Jakarta"), ("MYPKL", "Port Klang"),
        ("AEFJR", "Fujairah"), ("PHMNL", "Manila"),
        ("RUVST", "Vostochny"), ("INNSA", "Nhava Sheva"),
    ]
    # PORT_CHARGE.xls 는 CA1..CA16 까지 (CA17~ 는 실 데이터에도 없음)
    cats = [f"CA{i}" for i in range(1, 17)]

    rows: list[dict] = []
    for port_code, port_name in ports:
        # 항구별 기준 배율
        port_factor = {
            "KRPUS": 1.0, "KRINC": 0.95, "KRKAN": 0.9,
            "CNSHA": 1.05, "CNNGB": 1.0, "HKHKG": 1.4,
            "SGSIN": 1.2, "JPYAT": 1.6, "VNSGN": 0.85, "THLCH": 0.8,
            "IDJKT": 0.85, "MYPKL": 0.8, "AEFJR": 0.9, "PHMNL": 0.9,
            "RUVST": 1.0, "INNSA": 0.95,
        }.get(port_code, 1.0)

        row = {"PORT": port_code, "PORT NAME": port_name}
        for j, cat in enumerate(cats):
            # CA 클수록 항비 상승. CA16 은 실데이터에서 노이즈가 있다는 메모가
            # DATA_ISSUES.md 에 있지만, 데모에서는 일관되게 채움.
            base = 6000 + (j + 1) * 1500
            row[cat] = round(base * port_factor + random.uniform(-300, 300), -2)
        row["FROM DATE"] = datetime(2018, 1, 1)
        row["TO DATE"] = datetime(2999, 12, 31)
        rows.append(row)

    df = pd.DataFrame(rows, columns=["PORT", "PORT NAME"] + cats + ["FROM DATE", "TO DATE"])
    df.to_excel(OUT_DIR / "PORT_CHARGE.xls", index=False, engine="openpyxl")
    print(f"  PORT_CHARGE : {len(ports)} ports x {len(cats)} categories")


# ---------------------------------------------------------------------------
# 4. vessel_spec.xlsx  (선형 스펙, 시트별 TEU 클래스)
# ---------------------------------------------------------------------------
# 한 시트의 행 구조 (vessel_spec_loader._build_label_map 가 인식하는 라벨):
#   row 0 : col 0 = "Type / Design", col 1+ = 타입명들
#   row 1 : col 0 = "Built"
#   row 2 : col 0 = "Yard"
#   row 3 : col 0 = "Design",   col 1 = "DWT"
#   row 4 : col 0 = "Design",   col 1 = "Draft"
#   row 5 : col 0 = "Scantling",col 1 = "DWT"
#   row 6 : col 0 = "Scantling",col 1 = "Draft"
#   row 7 : col 0 = "GRT"
#   row 8 : col 0 = "TEU",      col 1 = "nom."
#   row 9 : col 0 = "",         col 1 = "14t"
#   row 14: col 0 = "LOA"
#   row 16: col 0 = "BEAM"
#   row 21..26: 속도 행 (col 1 에 속도, col 2+ 에 소모량)
#   row 27: col 0 = "aux engine at sea / in port"   값 = "X / Y"

SHEET_SPEC = [
    # (sheet_name,                  [(type_name, teu_nom, teu_14t, loa, beam, built, yard, aux_sea, aux_port, speed_curve)])
    ("1100TEU", [
        ("Hanjin 1100",  1100, 850,  150,  23,   2010, "HHI",  3.5, 3.2,
         {23: 60, 19: 38, 18: 33, 17: 29, 16: 26, 14: 22}),
        ("Hyundai 1050", 1050, 820,  149,  22.8, 2011, "DSME", 3.4, 3.1,
         {23: 58, 19: 37, 18: 32, 17: 28, 16: 25, 14: 21}),
    ]),
    ("1700TEU", [
        ("Hanjin 1700",  1700, 1300, 175,  27.4, 2009, "HHI",  4.5, 4.2,
         {23: 75, 19: 50, 18: 43, 17: 37, 16: 33, 14: 28}),
        ("Topaz 1700",   1720, 1320, 176,  27.5, 2012, "SHI",  4.6, 4.2,
         {23: 76, 19: 51, 18: 44, 17: 38, 16: 34, 14: 28}),
    ]),
    ("2500TEU", [
        ("Hanjin 2500",  2500, 1900, 200,  30,   2010, "HHI",  5.5, 5.0,
         {23: 95, 19: 60, 18: 52, 17: 45, 16: 40, 14: 33}),
        ("Hyundai 2700", 2700, 2050, 201,  30.2, 2013, "HHI",  5.7, 5.1,
         {23: 98, 19: 62, 18: 53, 17: 46, 16: 41, 14: 34}),
    ]),
    ("4000-4600TEU", [
        # ★ Jiangsu 4250 의 18kt 소모량 = 59.5  (tests/test_data_loaders.py 기대값)
        ("Jiangsu 4250", 4249, 3300, 261,    32.2,  2008, "Jiangsu",  9.0, 9.6,
         {23: 115, 19: 70.5, 18: 59.5, 17: 51, 16: 45, 14: 36}),
        ("Samsung 4000", 4253, 3310, 260.05, 32.25, 2010, "Samsung", 6.2, 5.7,
         {23: 112, 19: 69, 18: 58, 17: 50, 16: 44, 14: 35}),
    ]),
    ("5000TEU", [
        ("Hyundai 5000", 5000, 3850, 280,   32.2, 2011, "HHI",  7.0, 6.5,
         {23: 130, 19: 80, 18: 70, 17: 60, 16: 53, 14: 42}),
    ]),
    ("6500TEU", [
        ("Hyundai 6500", 6500, 5000, 305,   40,   2014, "HHI",  7.8, 7.2,
         {23: 165, 19: 100, 18: 85, 17: 73, 16: 64, 14: 50}),
    ]),
    ("8000TEU", [
        ("Daewoo 8000",  8500, 6500, 335,   43,   2016, "DSME", 9.0, 8.4,
         {23: 200, 19: 125, 18: 105, 17: 90, 16: 78, 14: 60}),
    ]),
]


def generate_vessel_spec() -> None:
    out_path = OUT_DIR / "vessel_spec.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet_name, types in SHEET_SPEC:
            n_types = len(types)
            n_cols = 2 + n_types  # col0, col1, then one col per type

            # 28 rows x n_cols (행 27 까지 사용)
            grid: list[list] = [[None] * n_cols for _ in range(28)]

            # row 0: type 헤더
            grid[0][0] = "Type / Design"
            for i, (name, *_) in enumerate(types):
                grid[0][2 + i] = name

            # row 1: Built
            grid[1][0] = "Built"
            for i, t in enumerate(types):
                grid[1][2 + i] = t[5]
            # row 2: Yard
            grid[2][0] = "Yard"
            for i, t in enumerate(types):
                grid[2][2 + i] = t[6]
            # row 3: Design DWT
            grid[3][0] = "Design"
            grid[3][1] = "DWT"
            for i, t in enumerate(types):
                grid[3][2 + i] = round(t[1] * 12)  # 가상 DWT = TEU*12
            # row 4: Design Draft
            grid[4][0] = "Design"
            grid[4][1] = "Draft"
            for i, t in enumerate(types):
                grid[4][2 + i] = 11.5 + t[1] / 4000
            # row 5: Scantling DWT
            grid[5][0] = "Scantling"
            grid[5][1] = "DWT"
            for i, t in enumerate(types):
                grid[5][2 + i] = round(t[1] * 13)
            # row 6: Scantling Draft
            grid[6][0] = "Scantling"
            grid[6][1] = "Draft"
            for i, t in enumerate(types):
                grid[6][2 + i] = 12 + t[1] / 4000
            # row 7: GRT
            grid[7][0] = "GRT"
            for i, t in enumerate(types):
                grid[7][2 + i] = round(t[1] * 8)
            # row 8: TEU nom.
            grid[8][0] = "TEU"
            grid[8][1] = "nom."
            for i, t in enumerate(types):
                grid[8][2 + i] = t[1]
            # row 9: TEU 14t
            grid[9][1] = "14t"
            for i, t in enumerate(types):
                grid[9][2 + i] = t[2]
            # row 14: LOA
            grid[14][0] = "LOA"
            for i, t in enumerate(types):
                grid[14][2 + i] = t[3]
            # row 16: BEAM
            grid[16][0] = "BEAM"
            for i, t in enumerate(types):
                grid[16][2 + i] = t[4]
            # row 21..26: 속도 행 (23/19/18/17/16/14)
            speed_rows = [(21, 23), (22, 19), (23, 18), (24, 17), (25, 16), (26, 14)]
            for row_idx, speed in speed_rows:
                grid[row_idx][1] = speed
                for i, t in enumerate(types):
                    grid[row_idx][2 + i] = t[9].get(speed)
            # row 27: aux engine
            grid[27][0] = "aux engine at sea / in port"
            for i, t in enumerate(types):
                grid[27][2 + i] = f"{t[7]} / {t[8]}"

            df = pd.DataFrame(grid)
            df.to_excel(writer, sheet_name=sheet_name, header=False, index=False)

    n_types = sum(len(types) for _, types in SHEET_SPEC)
    print(f"  vessel_spec : {len(SHEET_SPEC)} sheets, {n_types} vessel types")


# ---------------------------------------------------------------------------
# 5. SERVICE_LIST.xls  (프로포마 스케줄, 서비스 블록을 세로로 쌓음)
# ---------------------------------------------------------------------------
SERVICES = [
    {
        "code": "ANX",
        "name": "ASIA NEW EXPRESS",
        # (seq, from_port, wharf, to_port, bnd, distance_nm, speed, sea_time, tml, tb_manv, td_manv, sea_buff, total)
        "legs": [
            (1, "KRPUS", "PNIT", "CNSHA", "W", 510, 18, "028:20", "020:00", "01:30", "01:30", "002:00", "053:20"),
            (2, "CNSHA", "WGQ",  "CNNGB", "W", 130, 16, "008:08", "018:00", "01:30", "01:30", "002:00", "031:08"),
            (3, "CNNGB", "BLT",  "HKHKG", "S", 845, 19, "044:28", "020:00", "01:30", "01:30", "004:00", "071:28"),
            (4, "HKHKG", "HIT",  "SGSIN", "S", 1450, 20, "072:30", "022:00", "01:30", "01:30", "006:00", "103:30"),
            (5, "SGSIN", "PSA",  "KRPUS", "E", 2820, 19, "148:25", "024:00", "01:30", "01:30", "010:00", "185:25"),
        ],
    },
    {
        "code": "KIX",
        "name": "KOREA INDIA EXPRESS",
        "legs": [
            (1, "KRPUS", "PNIT", "CNSHA", "W", 510, 17, "030:00", "020:00", "01:30", "01:30", "002:00", "055:00"),
            (2, "CNSHA", "WGQ",  "SGSIN", "S", 2370, 19, "124:45", "024:00", "01:30", "01:30", "008:00", "159:45"),
            (3, "SGSIN", "PSA",  "INNSA", "W", 2500, 18, "138:53", "030:00", "01:30", "01:30", "010:00", "181:53"),
            (4, "INNSA", "JNPT", "KRPUS", "E", 5200, 19, "273:41", "022:00", "01:30", "01:30", "012:00", "310:41"),
        ],
    },
    {
        "code": "JKX",
        "name": "JAPAN KOREA EXPRESS",
        "legs": [
            (1, "KRPUS", "PNIT", "JPYAT", "E", 540, 17, "031:46", "018:00", "01:30", "01:30", "002:00", "054:46"),
            (2, "JPYAT", "YIT",  "KRPUS", "W", 540, 17, "031:46", "020:00", "01:30", "01:30", "002:00", "056:46"),
        ],
    },
]

# SERVICE_LIST.xls 한 블록 컬럼 헤더
SVC_COLS = ["SEQ", "FRPORT", "WHARF", "TOPORT", "BND", "ETA", "TBMANV", "ETB",
            "ETBDAY", "TDMANV", "TML", "ETD", "ETDDAY", "DISTANCE", "SPEED",
            "SEATIME", "DIFF", "SEABUFF", "TOALTIME"]


def generate_service_list() -> None:
    """
    원본 SERVICE_LIST.xls 구조 = 서비스마다 헤더 + 컬럼라벨 + 데이터 + 공백.
    한 시트에 모든 서비스를 세로로 누적해서 기록한다 (loader 가 그 형태를 기대).
    """
    rows: list[list] = []
    for svc in SERVICES:
        # 1) 서비스 헤더
        rows.append([f"{svc['code']}  Service ({svc['name']})"] + [None] * (len(SVC_COLS) - 1))
        # 2) 컬럼 헤더
        rows.append(list(SVC_COLS))
        # 3) 데이터 행 (ETA/ETB/ETD/DAY 등은 더미)
        eta_label = "MON 06:00"
        etb_label = "MON 08:00"
        etd_label = "TUE 04:00"
        etb_day = "MON"
        etd_day = "TUE"
        diff = "+09:00"
        for leg in svc["legs"]:
            (seq, fr, wharf, to, bnd, dist, spd,
             seatime, tml, tb_manv, td_manv, sea_buff, total) = leg
            rows.append([
                seq, fr, wharf, to, bnd, eta_label, tb_manv, etb_label,
                etb_day, td_manv, tml, etd_label, etd_day, dist, spd,
                seatime, diff, sea_buff, total,
            ])
        # 4) 공백 행
        rows.append([None] * len(SVC_COLS))

    df = pd.DataFrame(rows)
    df.to_excel(OUT_DIR / "SERVICE_LIST.xls", index=False, header=False, engine="openpyxl")
    print(f"  SERVICE_LIST: {len(SERVICES)} services, "
          f"{sum(len(s['legs']) for s in SERVICES)} legs")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"[generate_demo_data] writing to {OUT_DIR}")
    generate_bunker()
    generate_hire()
    generate_port_charge()
    generate_vessel_spec()
    generate_service_list()
    print("[done]")


if __name__ == "__main__":
    main()
