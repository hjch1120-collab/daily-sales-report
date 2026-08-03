import io
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from extract_raw import extract, KEEP_COLS
from build_report import build, MONTHLY_TARGETS
from make_html import build_html

st.set_page_config(page_title="일일 판매 보고서", page_icon="📊", layout="centered")

WORKDIR = Path("/tmp/daily_report_app")
WORKDIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Playwright(Chromium) 최초 1회 자동 설치 (무료 호스팅 환경 대응)
# ---------------------------------------------------------------------------
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
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                check=True,
            )
        return True


def html_to_pdf_bytes(html_path: Path) -> bytes:
    """HTML -> PDF (Chromium 렌더링) -> 1페이지만 남기고 반환"""
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader, PdfWriter

    raw_pdf = html_path.with_suffix(".raw.pdf")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(f"file://{html_path.resolve()}")
        page.pdf(
            path=str(raw_pdf),
            print_background=True,
            format="A4",
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        b.close()

    reader = PdfReader(str(raw_pdf))
    writer = PdfWriter()
    writer.add_page(reader.pages[0])  # 1페이지만
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def build_share_text(data: dict) -> str:
    d = data["daily"]
    w = data["weekly"]

    if data.get("incomplete_warning"):
        return (
            f"⚠ {d['date']} 데이터가 평소보다 적어(채널 {data['today_channels']}개 / "
            f"최근 7일 평균 {data['avg_channels']}개) 마감 전 데이터일 수 있습니다."
        )

    def pct_str(p):
        if p is None:
            return "변동 없음"
        return f"{'+' if p > 0 else ''}{p}%"

    lines = [
        f"[일일 판매 보고서 {d['date'][5:].replace('-', '/')}] "
        f"{d['date']} 매출 {d['revenue']:,}원 (전일 {pct_str(d['revenue_pct'])}), "
        f"주간 누적 {w['revenue']:,}원 (전주 {pct_str(w['revenue_pct'])})"
    ]

    if data["spikes"]:
        top = data["spikes"][0]
        if top["ratio"] is not None:
            lines.append(f"{top['원품명']}이(가) 평소보다 {top['ratio']}배 급증했습니다.")
        else:
            lines.append(f"{top['원품명']}이(가) 신규로 급증 판매되었습니다.")
    elif data["drops"]:
        top = data["drops"][0]
        lines.append(f"{top['원품명']} 판매가 평소보다 크게 줄었습니다.")

    if data["cancel_top"]:
        c = data["cancel_top"][0]
        lines.append(f"취소 다발: {c['원품명']} {int(c['취소수량']):,}개 · {int(c['취소금액']):,}원")

    mo = data["monthly"]
    if mo.get("target_revenue"):
        lines.append(f"목표매출 진행률 {pct_str(mo['target_pct'])}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📊 일일 판매 보고서")
st.caption("RAW 엑셀 또는 1차가공 CSV를 올리면 A4 PDF 보고서를 바로 만들어줍니다.")

file_kind = st.radio(
    "업로드할 파일 종류",
    ["1차가공 CSV", "RAW 엑셀 (주문별매출보고서)"],
    horizontal=True,
)

uploaded = st.file_uploader(
    "파일 업로드",
    type=["csv", "xlsx"],
)

target_key_hint = date.today().strftime("%Y-%m")
with st.expander("⚙️ 이번 달 목표매출 설정 (선택)"):
    default_target = MONTHLY_TARGETS.get(target_key_hint, 0)
    target_input = st.number_input(
        f"{target_key_hint} 목표매출 (원, 0이면 미사용)",
        min_value=0,
        value=int(default_target),
        step=1_000_000,
    )

if uploaded is not None:
    # 1) CSV 확보
    csv_path = WORKDIR / "1차가공.csv"

    if file_kind == "RAW 엑셀 (주문별매출보고서)":
        raw_path = WORKDIR / "raw.xlsx"
        raw_path.write_bytes(uploaded.getvalue())
        with st.spinner("RAW 엑셀에서 데이터 추출 중..."):
            out_df = extract(str(raw_path), str(csv_path))
        st.success(f"CSV 추출 완료 ({len(out_df):,}행)")
        st.download_button(
            "1차가공.csv 다운로드",
            data=csv_path.read_bytes(),
            file_name="1차가공.csv",
            mime="text/csv",
        )
    else:
        csv_path.write_bytes(uploaded.getvalue())

    # 2) 기준일 선택
    try:
        preview = pd.read_csv(csv_path, encoding="utf-8-sig")
        preview["주문일자"] = pd.to_datetime(preview["주문일자"], errors="coerce")
        max_date = preview["주문일자"].max()
        default_date = (max_date - timedelta(days=1)).date() if pd.notna(max_date) else date.today()
    except Exception:
        default_date = date.today() - timedelta(days=1)

    report_date = st.date_input("보고서 기준일", value=default_date)

    if st.button("📄 일일보고서 생성", type="primary"):
        ensure_chromium()

        if target_input:
            MONTHLY_TARGETS[target_key_hint] = target_input

        with st.spinner("데이터 계산 중..."):
            data = build(src=str(csv_path), report_date=report_date.strftime("%Y-%m-%d"))

        html_str = build_html(data)
        html_path = WORKDIR / "report.html"
        html_path.write_text(html_str, encoding="utf-8")

        with st.spinner("PDF 생성 중 (최초 1회는 다소 걸릴 수 있어요)..."):
            pdf_bytes = html_to_pdf_bytes(html_path)

        st.success("보고서 생성 완료!")

        if data.get("incomplete_warning"):
            st.warning(
                f"⚠ {data['daily']['date']} 데이터가 평소보다 적습니다 "
                f"(채널 {data['today_channels']}개 / 최근 7일 평균 {data['avg_channels']}개). "
                "마감 전 데이터일 수 있어요."
            )

        st.download_button(
            "📥 PDF 다운로드",
            data=pdf_bytes,
            file_name=f"일일판매보고서_{data['daily']['date']}.pdf",
            mime="application/pdf",
        )

        st.subheader("공유용 텍스트")
        share_text = build_share_text(data)
        st.code(share_text, language=None)

        with st.expander("미리보기 (HTML)"):
            st.components.v1.html(html_str, height=1100, scrolling=True)
else:
    st.info("파일을 업로드하면 이어서 진행할 수 있어요.")
