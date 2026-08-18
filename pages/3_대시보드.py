import io
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from extract_raw import extract
from build_report import build, build_weekly, MONTHLY_TARGETS, _read_csv_any_encoding
from make_html import build_html

st.set_page_config(page_title="대시보드 · 포쿨_온라인팀", page_icon="📊", layout="wide")

WORKDIR = Path("/tmp/dashboard_app")
WORKDIR.mkdir(exist_ok=True)


@st.cache_resource(show_spinner=False)
def ensure_chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception:
        with st.spinner("최초 실행 준비 중입니다 (1~2분 정도 걸려요)..."):
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                st.error(f"Chromium 설치 실패\n\n{result.stderr}")
                st.stop()
        return True


def html_to_pdf_bytes(html_path: Path):
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader, PdfWriter

    raw_pdf = html_path.with_suffix(".raw.pdf")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(f"file://{html_path.resolve()}")
        page.pdf(path=str(raw_pdf), print_background=True, format="A4",
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()

    reader = PdfReader(str(raw_pdf))
    page_count = len(reader.pages)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), page_count


st.title("📊 포쿨_온라인팀 대시보드")
st.caption("파일을 한 번 올리면, 아래 탭에서 일일/주간(월간은 준비중) 데이터를 바로 확인할 수 있어요.")

file_kind = st.radio("업로드할 파일 종류", ["RAW 엑셀 (주문별매출보고서)", "1차가공 CSV"], horizontal=True)
uploaded = st.file_uploader("파일 업로드", type=["xlsx", "csv"])

if uploaded is not None:
    csv_path = WORKDIR / "1차가공.csv"
    if file_kind == "RAW 엑셀 (주문별매출보고서)":
        raw_path = WORKDIR / "raw.xlsx"
        raw_path.write_bytes(uploaded.getvalue())
        with st.spinner("RAW 엑셀에서 데이터 추출 중..."):
            out_df = extract(str(raw_path), str(csv_path))
        st.success(f"CSV 추출 완료 ({len(out_df):,}행)")
    else:
        csv_path.write_bytes(uploaded.getvalue())

    try:
        preview = _read_csv_any_encoding(csv_path)
        preview["주문일자"] = pd.to_datetime(preview["주문일자"], errors="coerce")
        max_date = preview["주문일자"].max()
        default_date = (max_date - timedelta(days=1)).date() if pd.notna(max_date) else date.today()
    except Exception:
        default_date = date.today() - timedelta(days=1)

    report_date = st.date_input("기준일 (일일/주간 탭 공통)", value=default_date)

    tab_daily, tab_weekly, tab_monthly = st.tabs(["📄 일일", "📆 주간", "🗓️ 월간 (준비중)"])

    # ---------------------------------------------------------------
    # 일일 탭
    # ---------------------------------------------------------------
    with tab_daily:
        manage_input = st.text_input(
            "★ 표시할 모델 (쉼표로 구분, 최대 5개)", value="", key="daily_manage",
        )
        manage_models = [m.strip() for m in manage_input.split(",") if m.strip()][:5]

        if st.button("일일 데이터 불러오기", type="primary", key="daily_btn"):
            try:
                with st.spinner("계산 중..."):
                    data = build(src=str(csv_path), report_date=report_date.strftime("%Y-%m-%d"), manage_models=manage_models)
                d = data["daily"]
                c1, c2, c3 = st.columns(3)
                c1.metric("일간 매출", f"{d['revenue']:,}원", f"{d['revenue_pct']}%" if d['revenue_pct'] is not None else None)
                c2.metric("일간 판매수량", f"{d['qty']:,}개", f"{d['qty_pct']}%" if d['qty_pct'] is not None else None)
                bm = d.get("best_model")
                c3.metric("베스트모델", bm["원품명"] if bm else "-", f"{bm['수량']}개" if bm else None)

                st.subheader("🔺 급증 모델")
                if data["spikes"]:
                    st.dataframe(
                        pd.DataFrame([{"모델명": s["원품명"], "순위": s["tier"], "직전7일평균": s["baseline"], "기준일": s["today_qty"], "증감": s["diff"]} for s in data["spikes"]]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("해당 없음")

                st.subheader("🔻 급감 모델")
                if data["drops"]:
                    st.dataframe(
                        pd.DataFrame([{"모델명": s["원품명"], "순위": s["tier"], "직전7일평균": s["baseline"], "기준일": s["today_qty"], "증감": s["diff"]} for s in data["drops"]]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("해당 없음")

                # PDF 다운로드도 제공
                ensure_chromium()
                zoom = 0.92
                html_path = WORKDIR / "daily_report.html"
                with st.spinner("PDF 생성 중..."):
                    for _ in range(6):
                        html_str = build_html(data, zoom=zoom)
                        html_path.write_text(html_str, encoding="utf-8")
                        pdf_bytes, page_count = html_to_pdf_bytes(html_path)
                        if page_count <= 1:
                            break
                        zoom = round(zoom - 0.04, 2)
                        if zoom < 0.70:
                            break
                st.download_button("📥 일일보고서 PDF 다운로드", data=pdf_bytes,
                                    file_name=f"일일판매보고서_{data['daily']['date']}.pdf", mime="application/pdf")
            except Exception as e:
                st.error("오류가 발생했습니다.")
                st.exception(e)

    # ---------------------------------------------------------------
    # 주간 탭
    # ---------------------------------------------------------------
    with tab_weekly:
        st.caption("⚠️ 1차 버전입니다 — 급증/급감 기준(직전4주 평균 대비)은 추후 다듬을 예정이에요.")
        if st.button("주간 데이터 불러오기", type="primary", key="weekly_btn"):
            try:
                with st.spinner("계산 중..."):
                    wdata = build_weekly(src=str(csv_path), report_date=report_date.strftime("%Y-%m-%d"))
                w = wdata["weekly"]
                c1, c2, c3 = st.columns(3)
                c1.metric(f"이번주 매출 ({w['range']})", f"{w['revenue']:,}원", f"{w['revenue_pct']}%" if w['revenue_pct'] is not None else None)
                c2.metric("이번주 판매수량", f"{w['qty']:,}개", f"{w['qty_pct']}%" if w['qty_pct'] is not None else None)
                bm = w.get("best_model")
                c3.metric("이번주 베스트모델", bm["원품명"] if bm else "-", f"{bm['수량']}개" if bm else None)

                st.caption(f"기준선(직전4주 일평균): {wdata['baseline_range']}")

                st.subheader("🔺 급증 모델 (주간)")
                if wdata["spikes"]:
                    st.dataframe(
                        pd.DataFrame([{"모델명": s["원품명"], "순위": s["tier"], "직전4주 일평균": s["baseline"], "이번주 일평균": s["this_week_avg"], "증감": s["diff"]} for s in wdata["spikes"]]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("해당 없음")

                st.subheader("🔻 급감 모델 (주간)")
                if wdata["drops_is_fallback"]:
                    st.caption("1~2순위 없어 근접 3순위로 대체 표시됨")
                if wdata["drops"]:
                    st.dataframe(
                        pd.DataFrame([{"모델명": s["원품명"], "순위": s["tier"], "직전4주 일평균": s["baseline"], "이번주 일평균": s["this_week_avg"], "증감": s["diff"]} for s in wdata["drops"]]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("해당 없음")
            except Exception as e:
                st.error("오류가 발생했습니다.")
                st.exception(e)

    # ---------------------------------------------------------------
    # 월간 탭
    # ---------------------------------------------------------------
    with tab_monthly:
        st.info("월간보고서는 별도 대화창에서 준비 중입니다. 완성되면 이 탭에 반영됩니다.")

else:
    st.info("파일을 업로드하면 이어서 진행할 수 있어요.")
