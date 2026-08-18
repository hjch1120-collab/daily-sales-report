from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from extract_raw import extract
from build_report import load as load_valid

st.set_page_config(page_title="실시간 대시보드 · 포쿨_온라인팀", page_icon="📡", layout="wide")

WORKDIR = Path("/tmp/live_dashboard")
WORKDIR.mkdir(exist_ok=True)

SHEET_ID = "15rtXN3BkzPh9EKJ4AFZVziz1c5XbwzEduzFCVt6NOjE"
WORKSHEET_NAME = "일일데이터"


# ---------------------------------------------------------------------------
# 구글시트 연결
# ---------------------------------------------------------------------------
def _secrets_ready() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


def _get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=10)
        ws.update([["날짜", "원품명", "수량", "매출액"]])
    return ws


def sync_to_sheet(valid_df: pd.DataFrame):
    """업로드한 파일의 날짜 구간을 통째로 최신값으로 덮어쓴다 (취소/반품 정정 자동 반영)."""
    ws = _get_worksheet()

    agg = valid_df.groupby(["주문일자", "원품명"]).agg(
        수량=("수량", "sum"), 매출액=("매출액", "sum")
    ).reset_index()
    agg["날짜"] = agg["주문일자"].dt.strftime("%Y-%m-%d")
    agg = agg[["날짜", "원품명", "수량", "매출액"]]

    records = ws.get_all_records()
    existing_df = pd.DataFrame(records) if records else pd.DataFrame(columns=["날짜", "원품명", "수량", "매출액"])

    upload_dates = set(agg["날짜"])
    if not existing_df.empty:
        existing_df["날짜"] = existing_df["날짜"].astype(str)
        keep_df = existing_df[~existing_df["날짜"].isin(upload_dates)]
    else:
        keep_df = existing_df

    final_df = pd.concat([keep_df, agg], ignore_index=True)
    final_df = final_df.sort_values(["날짜", "원품명"]).reset_index(drop=True)

    ws.clear()
    ws.update([final_df.columns.tolist()] + final_df.astype(str).values.tolist())
    return len(agg), sorted(upload_dates)[0], sorted(upload_dates)[-1]


@st.cache_data(ttl=60, show_spinner=False)
def load_from_sheet():
    ws = _get_worksheet()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0)
    df["매출액"] = pd.to_numeric(df["매출액"], errors="coerce").fillna(0)
    return df.dropna(subset=["날짜"])


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📡 실시간 대시보드")
st.caption("파일을 올리면 구글시트에 자동 반영되고, 업로드 없이 들어와도 지금까지 쌓인 데이터를 항상 볼 수 있어요.")

if not _secrets_ready():
    st.error(
        "구글시트 연결 정보(gcp_service_account)가 아직 설정 안 됐어요. "
        "Streamlit Cloud의 'Manage app → Settings → Secrets'에서 설정해주세요."
    )
    st.stop()

with st.expander("📤 RAW 엑셀 업로드해서 최신 데이터 반영하기", expanded=False):
    uploaded = st.file_uploader("RAW 엑셀 (주문별매출보고서)", type=["xlsx"])
    if uploaded is not None:
        raw_path = WORKDIR / "raw.xlsx"
        raw_path.write_bytes(uploaded.getvalue())
        csv_path = WORKDIR / "1차가공.csv"
        with st.spinner("데이터 추출 중..."):
            extract(str(raw_path), str(csv_path))
        valid_df = load_valid(str(csv_path))
        valid_df = valid_df[valid_df["취소일자"].isna()]

        if st.button("📡 구글시트에 반영하기", type="primary"):
            try:
                with st.spinner("구글시트에 반영 중... (데이터가 많으면 시간이 좀 걸려요)"):
                    n_rows, d_start, d_end = sync_to_sheet(valid_df)
                st.success(f"반영 완료! {d_start} ~ {d_end} 구간, {n_rows}개 행이 최신화됐어요.")
                load_from_sheet.clear()
            except Exception as e:
                st.error("구글시트 반영 중 오류가 발생했어요.")
                st.exception(e)

st.divider()

# ---------------------------------------------------------------------------
# 누적 데이터 표시 (업로드 없이도 항상 보임)
# ---------------------------------------------------------------------------
try:
    df = load_from_sheet()
except Exception as e:
    st.error("구글시트에서 데이터를 불러오는 중 오류가 발생했어요.")
    st.exception(e)
    st.stop()

if df.empty:
    st.info("아직 구글시트에 쌓인 데이터가 없어요. 위에서 RAW 엑셀을 올려서 반영해주세요.")
else:
    min_d, max_d = df["날짜"].min().date(), df["날짜"].max().date()
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작일", value=max(min_d, max_d - timedelta(days=29)), min_value=min_d, max_value=max_d)
    with col2:
        end_date = st.date_input("종료일", value=max_d, min_value=min_d, max_value=max_d)

    mask = (df["날짜"].dt.date >= start_date) & (df["날짜"].dt.date <= end_date)
    view = df[mask]

    c1, c2, c3 = st.columns(3)
    c1.metric("선택 구간 매출", f"{int(view['매출액'].sum()):,}원")
    c2.metric("선택 구간 판매수량", f"{int(view['수량'].sum()):,}개")
    c3.metric("데이터 보유 기간", f"{min_d} ~ {max_d}")

    st.subheader("📈 일별 매출/판매수량 추이")
    daily = view.groupby("날짜").agg(매출액=("매출액", "sum"), 수량=("수량", "sum")).reset_index()
    if not daily.empty:
        fig = px.line(daily, x="날짜", y="매출액", markers=True, title=None)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=350)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🏆 모델별 랭킹 (선택 구간)")
    ranking = view.groupby("원품명").agg(수량=("수량", "sum"), 매출액=("매출액", "sum")).sort_values("수량", ascending=False).reset_index()
    top_n = st.slider("표시 개수", 5, 50, 15)
    st.dataframe(ranking.head(top_n), hide_index=True, use_container_width=True)

    with st.expander(f"📌 특정 모델만 따로 보기"):
        model_pick = st.selectbox("모델 선택", ranking["원품명"].tolist())
        if model_pick:
            model_daily = view[view["원품명"] == model_pick].groupby("날짜").agg(수량=("수량", "sum")).reset_index()
            fig2 = px.bar(model_daily, x="날짜", y="수량", title=f"{model_pick} 일별 판매수량")
            fig2.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
            st.plotly_chart(fig2, use_container_width=True)
