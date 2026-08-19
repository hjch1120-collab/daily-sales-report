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


def _tier_table(records, base_key="baseline", base_label="평균"):
    if not records:
        return None
    return pd.DataFrame([
        {
            "모델명": s["원품명"],
            "순위": f'{s["tier"]}순위',
            base_label: s[base_key],
            "기준일/이번주": s.get("today_qty", s.get("this_week_avg")),
            "증감": s["diff"],
        }
        for s in records
    ])


st.title("📊 포쿨_온라인팀 대시보드")
st.caption("파일을 올리면 아래 탭(일일/주간/월간)에서 바로 데이터를 확인할 수 있어요. 버튼 없이 자동으로 갱신됩니다.")

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

    col_date, col_manage = st.columns([1, 2])
    with col_date:
        report_date = st.date_input("기준일 (일일/주간 탭 공통)", value=default_date)
    with col_manage:
        manage_input = st.text_input("★ 표시할 모델 (쉼표로 구분, 최대 5개, 일일 탭에 적용)", value="")
    manage_models = list(dict.fromkeys(m.strip() for m in manage_input.split(",") if m.strip()))[:5]

    tab_daily, tab_weekly, tab_monthly = st.tabs(["📄 일일", "📆 주간", "🗓️ 월간 (준비중)"])

    # ---------------------------------------------------------------
    # 일일 탭 — 파일/기준일만 있으면 버튼 없이 바로 표시
    # ---------------------------------------------------------------
    with tab_daily:
        try:
            data = build(src=str(csv_path), report_date=report_date.strftime("%Y-%m-%d"), manage_models=manage_models)
            d = data["daily"]

            # 일간 KPI
            c1, c2, c3 = st.columns(3)
            c1.metric("일간 매출", f"{d['revenue']:,}원", f"{d['revenue_pct']}%" if d['revenue_pct'] is not None else None)
            c1.caption(f"전주 {d['prev_sameweekday_weekday']}요일 대비 {d['prev_sameweekday_revenue_pct']}%" if d.get('prev_sameweekday_revenue_pct') is not None else "")
            c2.metric("일간 판매수량", f"{d['qty']:,}개", f"{d['qty_pct']}%" if d['qty_pct'] is not None else None)
            c2.caption(f"전주 {d['prev_sameweekday_weekday']}요일 대비 {d['prev_sameweekday_qty_pct']}%" if d.get('prev_sameweekday_qty_pct') is not None else "")
            bm = d.get("best_model")
            c3.metric("베스트모델", bm["원품명"] if bm else "-", f"{bm['수량']}개 · {int(bm['매출액']):,}원" if bm else None)

            st.divider()

            # 주간 매출 추이 + 월 누적매출
            col_w, col_m = st.columns(2)
            with col_w:
                st.subheader("📈 주간 매출 추이 (최근 3주)")
                wt = data["weekly_trend"]
                if wt:
                    st.dataframe(
                        pd.DataFrame([{"기간": w["range"] + (" (이번주)" if w.get("is_current") else ""),
                                        "매출액": f'{w["revenue"]:,}원',
                                        "증감": f'{w["revenue_pct"]}%' if w["revenue_pct"] is not None else "-"} for w in wt]),
                        hide_index=True, use_container_width=True,
                    )
            with col_m:
                mo = data["monthly"]
                st.subheader(f"💰 {mo['range']} 누적매출")
                st.metric("누적매출", f"{mo['revenue']:,}원", f"{mo['qty']:,}개")
                st.caption(f"전월({mo['prev_month_full_range']}) 총매출 {mo['prev_month_full_revenue']:,}원")
                if mo.get("projected_revenue"):
                    st.caption(f"예상 이번달 총매출: **{mo['projected_revenue']:,}원** (이번달 {mo['projection_days_elapsed']}일간 일평균×{mo['projection_days_in_month']}일)")
                if mo.get("target_revenue"):
                    pct_txt = f"{mo['projected_target_pct']}%" if mo.get("projected_target_pct") is not None else "-"
                    st.caption(f"목표매출 {mo['target_revenue']:,}원 · 예상 달성률 {pct_txt}")

            st.divider()

            # 체크모델
            if data.get("check_models"):
                st.subheader("★ 체크모델 (직접 입력한 모델만)")
                st.dataframe(
                    pd.DataFrame([{"모델명": m["원품명"], "직전7일평균": m["baseline"], "기준일": m["today_qty"], "증감": m["diff"]} for m in data["check_models"]]),
                    hide_index=True, use_container_width=True,
                )
                st.divider()

            # 급증/급감
            col_s, col_dr = st.columns(2)
            with col_s:
                st.subheader(f"🔺 급증 모델 ({len(data['spikes'])}건)")
                tbl = _tier_table(data["spikes"], base_label="직전7일평균")
                if tbl is not None:
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.caption("해당 없음")
            with col_dr:
                fallback_note = " (근접 3순위 대체)" if data.get("drops_is_fallback") else ""
                st.subheader(f"🔻 급감 모델{fallback_note} ({len(data['drops'])}건)")
                tbl = _tier_table(data["drops"], base_label="직전7일평균")
                if tbl is not None:
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.caption("해당 없음")

            # 장기 하락세 모델
            if data.get("long_decline_models"):
                st.divider()
                st.subheader(f"📉 장기 하락세 모델 ({len(data['long_decline_models'])}건)")
                st.caption("3개월→2개월→1개월 일평균 15%+ 연속 하락 · 오늘의 급감모델과는 별개 지표")
                st.dataframe(
                    pd.DataFrame([{
                        "모델명": m["원품명"], "3개월 일평균": m["avg_3mo"], "2개월 일평균": m["avg_2mo"],
                        "1개월 일평균": m["avg_month"], "기준일": m["today_qty"],
                        "단계별 하락률": f'-{m["drop1_pct"]}%→-{m["drop2_pct"]}%',
                    } for m in data["long_decline_models"]]),
                    hide_index=True, use_container_width=True,
                )

            # 신규 판매 모델
            new_sale = data.get("new_sale", {})
            silent_60 = new_sale.get("silent_60", [])
            gap_30 = new_sale.get("gap_30", [])
            if silent_60 or gap_30:
                st.divider()
                st.subheader(f"🆕 신규 판매 모델 ({len(silent_60) + len(gap_30)}건)")
                if silent_60:
                    st.markdown("**60일 침묵 모델 (신상품 가능성):** " + ", ".join(silent_60))
                if gap_30:
                    st.markdown("**1개월 공백 재판매:** " + ", ".join(gap_30))

            st.divider()

            # PDF 다운로드는 별도 버튼 (느려서 분리)
            if st.button("📥 PDF로 만들기", key="daily_pdf_btn"):
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
        try:
            wdata = build_weekly(src=str(csv_path), report_date=report_date.strftime("%Y-%m-%d"))
            w = wdata["weekly"]
            c1, c2, c3 = st.columns(3)
            c1.metric(f"이번주 매출 ({w['range']})", f"{w['revenue']:,}원", f"{w['revenue_pct']}%" if w['revenue_pct'] is not None else None)
            c2.metric("이번주 판매수량", f"{w['qty']:,}개", f"{w['qty_pct']}%" if w['qty_pct'] is not None else None)
            bm = w.get("best_model")
            c3.metric("이번주 베스트모델", bm["원품명"] if bm else "-", f"{bm['수량']}개 · {int(bm['매출액']):,}원" if bm else None)

            st.caption(f"기준선(직전4주 일평균): {wdata['baseline_range']} · 이번주는 {w['days_elapsed']}일차까지 누적")

            st.divider()

            col_s, col_dr = st.columns(2)
            with col_s:
                st.subheader(f"🔺 급증 모델 ({len(wdata['spikes'])}건)")
                tbl = _tier_table(wdata["spikes"], base_label="직전4주일평균")
                if tbl is not None:
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.caption("해당 없음")
            with col_dr:
                fallback_note = " (근접 3순위 대체)" if wdata.get("drops_is_fallback") else ""
                st.subheader(f"🔻 급감 모델{fallback_note} ({len(wdata['drops'])}건)")
                tbl = _tier_table(wdata["drops"], base_label="직전4주일평균")
                if tbl is not None:
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
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
