"""
RAW 주문별매출보고서(.xlsx) -> 1차가공.csv 추출 스크립트

사용법:
    python3 extract_raw.py <raw_xlsx_path> <output_csv_path>

동작:
    1. RAW 엑셀(첫 번째 시트)을 읽는다.
    2. 아래 9개 컬럼만 원본 값 그대로 추출한다:
       쇼핑몰, 주문일자, 출고일자, 취소일자, 매입처, 제조사, 원품명, 수량, 판매단가
    3. 쇼핑몰이 비어있는 행(맨 아래 요약/합계성 행)은 제외한다.
    4. build_report.py가 바로 읽을 수 있도록 utf-8-sig 인코딩 CSV로 저장한다.
"""
import sys
import pandas as pd

KEEP_COLS = ['쇼핑몰', '주문일자', '출고일자', '취소일자', '매입처', '제조사', '원품명', '수량', '판매단가']

def extract(raw_path, out_path):
    df = pd.read_excel(raw_path, sheet_name=0)

    missing = [c for c in KEEP_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"RAW 파일에 다음 컬럼이 없습니다: {missing}")

    out = df[KEEP_COLS].copy()

    # 맨 아래 요약/합계성 행 등 쇼핑몰이 비어있는 행 제외
    before = len(out)
    out = out[out['쇼핑몰'].notna()].copy()
    dropped = before - len(out)

    # 날짜 컬럼은 YYYY-MM-DD 형식 문자열로 저장 (build_report.py에서 pd.to_datetime으로 재파싱)
    for col in ['주문일자', '출고일자', '취소일자']:
        out[col] = pd.to_datetime(out[col], errors='coerce').dt.strftime('%Y-%m-%d')

    out.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f"원본 행 수: {before}")
    print(f"제외된 행 수(쇼핑몰 없음): {dropped}")
    print(f"저장된 행 수: {len(out)}")
    print(f"저장 경로: {out_path}")
    return out

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("사용법: python3 extract_raw.py <raw_xlsx_path> <output_csv_path>")
        sys.exit(1)
    extract(sys.argv[1], sys.argv[2])
