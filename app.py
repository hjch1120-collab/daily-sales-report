import io
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from extract_raw import extract
from build_report import build, MONTHLY_TARGETS
from make_html import build_html

st.set_page_config(page_title="포쿨_온라인팀_일일보고서", page_icon="📊", layout="centered")

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
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                st.error(
                    "Chromium 설치에 실패했습니다. 아래 로그를 확인해주세요.\n\n"
                    f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
                )
                st.stop()
        return True


def html_to_pdf_bytes(html_path: Path):
    """HTML -> PDF (Chromium 렌더링). (pdf_bytes, page_count) 반환.
    2페이지 이상이면 일단 1페이지만 잘라 반환하되 page_count로 원래 몇 페이지였는지 알려준다."""
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
    page_count = len(reader.pages)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])  # 1페이지만
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), page_count


# ---------------------------------------------------------------------------
# 공유용 텍스트 (자연스러운 구어체 문장, 6개 섹션)
# ---------------------------------------------------------------------------
def _dir_word(p, verb_up="증가", verb_down="감소"):
    if p is None:
        return "변동이 없었습니다"
    if p > 0:
        return f"전일 대비 {p}% {verb_up}했습니다"
    if p < 0:
        return f"전일 대비 {abs(p)}% {verb_down}했습니다"
    return "변동이 없었습니다"


def build_share_text(data: dict) -> str:
    d = data["daily"]
    wt = data["weekly_trend"]
    mo = data["monthly"]
    manage_models = data.get("manage_models", [])
    spikes = data.get("spikes", [])
    drops = data.get("drops", [])
    new_sale = data.get("new_sale", {"silent_60": [], "gap_30": []})

    parts = []

    # ① 매출/판매
    bm = d.get("best_model")
    s1 = (
        f"{d['date']} 매출은 {d['revenue']:,}원으로 {_dir_word(d['revenue_pct'])}. "
        f"판매수량은 {d['qty']:,}개로 {_dir_word(d['qty_pct'])}."
    )
    if bm:
        s1 += f" 베스트모델은 {bm['원품명']}이며, {bm['수량']:,}개 · {int(bm['매출액']):,}원의 매출을 기록했습니다."
    else:
        s1 += " 기준일 판매 데이터는 없었습니다."
    parts.append("[매출/판매]\n" + s1)

    # ② 주간/월누적
    cur_week = next((w for w in wt if w.get("is_current")), None)
    s2_lines = []
    if cur_week:
        s2_lines.append(
            f"이번주({cur_week['range']}) 누적매출은 {cur_week['revenue']:,}원으로 "
            f"{_dir_word(cur_week['revenue_pct'], '증가', '감소').replace('전일', '전주')}."
        )
    s2_lines.append(
        f"이번달({mo['range']}) 누적매출은 {mo['revenue']:,}원, 누적수량은 {mo['qty']:,}개입니다."
    )
    if mo.get("target_revenue"):
        tp = mo.get("target_pct")
        tp_txt = f"{tp}%" if tp is not None else "산정 불가"
        s2_lines.append(f"이번달 목표매출 대비 진행률은 {tp_txt}입니다.")
    parts.append("[주간/월누적]\n" + " ".join(s2_lines))

    # ③ 관리모델
    if manage_models:
        s3_lines = []
        for m in manage_models:
            if m["baseline"] > 0:
                sign = "증가" if m["diff"] > 0 else ("감소" if m["diff"] < 0 else "동일")
                s3_lines.append(
                    f"{m['원품명']}은(는) 평소 평균 {m['baseline']}개 대비 오늘 {m['today_qty']}개로, "
                    f"{abs(m['diff'])}개({abs(m['diff_pct']) if m['diff_pct'] is not None else '-'}%) {sign}했습니다."
                )
            else:
                s3_lines.append(f"{m['원품명']}은(는) 기준평균 데이터가 없어 오늘 {m['today_qty']}개 판매로만 확인됩니다.")
        parts.append("[관리모델]\n" + " ".join(s3_lines))

    # ④ 급증 모델 (1순위 위주)
    top_spikes = [s for s in spikes if s["tier"] == 1]
    if top_spikes:
        s4_lines = [
            f"{s['원품명']}이(가) 평균 {s['baseline']}개 대비 오늘 {s['today_qty']}개로 {s['diff']}개 늘었습니다."
            for s in top_spikes
        ]
        parts.append("[급증 모델]\n" + " ".join(s4_lines))

    # ⑤ 급감 모델 (1순위 위주 + 원인 점검 문구)
    top_drops = [s for s in drops if s["tier"] == 1]
    if top_drops:
        s5_lines = [
            f"{s['원품명']}이(가) 평균 {s['baseline']}개 대비 오늘 {s['today_qty']}개로 {abs(s['diff'])}개 줄었습니다."
            for s in top_drops
        ]
        s5_lines.append(
            "품절·재고 소진 여부, 노출순위 하락이나 프로모션 종료 여부, 경쟁사 가격변동으로 인한 가격 경쟁력 저하 여부, "
            "광고 예산 소진 여부, 리뷰·CS 이슈 여부를 함께 점검이 필요합니다."
        )
        parts.append("[급감 모델 · 원인 점검 필요]\n" + " ".join(s5_lines))

    # ⑥ 신규 판매 모델
    silent_60 = new_sale.get("silent_60", [])
    gap_30 = new_sale.get("gap_30", [])
    if silent_60 or gap_30:
        s6_lines = []
        if silent_60:
            s6_lines.append(f"최근 60일간 판매 이력이 없다가 오늘 판매된 모델은 {', '.join(silent_60)}로, 신상품일 가능성이 있습니다.")
        if gap_30:
            s6_lines.append(f"최근 30일간 공백이 있다가 오늘 다시 판매된 모델은 {', '.join(gap_30)}입니다.")
        parts.append("[신규 판매 모델]\n" + " ".join(s6_lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📊 포쿨_온라인팀_일일보고서")
st.caption("RAW 엑셀 또는 1차가공 CSV를 올리면 A4 PDF 보고서를 바로 만들어줍니다.")

file_kind = st.radio(
    "업로드할 파일 종류",
    ["1차가공 CSV", "RAW 엑셀 (주문별매출보고서)"],
    horizontal=True,
)

uploaded = st.file_uploader("파일 업로드", type=["csv", "xlsx"])

manage_input = st.text_input(
    "관리모델 (쉼표로 구분해서 원품명 입력, 예: FRE-465RF, FC-49MSW)",
    value="",
    help="지정한 모델은 순위와 무관하게 항상 ★관리모델 섹션에 표시됩니다. 비워두면 관리모델 섹션은 빈 상태로 나옵니다.",
)
manage_models = [m.strip() for m in manage_input.split(",") if m.strip()]

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

    try:
        preview = pd.read_csv(csv_path, encoding="utf-8-sig")
        preview["주문일자"] = pd.to_datetime(preview["주문일자"], errors="coerce")
        max_date = preview["주문일자"].max()
        default_date = (max_date - timedelta(days=1)).date() if pd.notna(max_date) else date.today()
    except Exception:
        default_date = date.today() - timedelta(days=1)

    report_date = st.date_input("보고서 기준일", value=default_date)

    if st.button("📄 일일보고서 생성", type="primary"):
        try:
            ensure_chromium()

            if target_input:
                MONTHLY_TARGETS[target_key_hint] = target_input

            with st.spinner("데이터 계산 중..."):
                data = build(
                    src=str(csv_path),
                    report_date=report_date.strftime("%Y-%m-%d"),
                    manage_models=manage_models,
                )

            html_str = build_html(data)
            html_path = WORKDIR / "report.html"
            html_path.write_text(html_str, encoding="utf-8")

            with st.spinner("PDF 생성 중 (최초 1회는 다소 걸릴 수 있어요)..."):
                pdf_bytes, page_count = html_to_pdf_bytes(html_path)
        except Exception as e:
            st.error("보고서 생성 중 오류가 발생했습니다. 아래 상세 내용을 캡처해서 전달해주세요.")
            st.exception(e)
            st.stop()

        st.success("보고서 생성 완료!")

        if page_count > 1:
            st.warning(
                f"⚠ PDF가 {page_count}페이지로 생성됐어요. 데이터가 많은 날이라 1페이지에 다 안 들어갔을 수 있습니다. "
                "PDF를 열어서 2페이지에 잘린 내용이 없는지 확인해주세요. (지금 다운로드되는 파일은 1페이지만 포함됩니다.)"
            )

        st.download_button(
            "📥 PDF 다운로드",
            data=pdf_bytes,
            file_name=f"일일판매보고서_{data['daily']['date']}.pdf",
            mime="application/pdf",
        )

        st.subheader("공유용 텍스트")
        share_text = build_share_text(data)
        st.text_area("공유용 텍스트", value=share_text, height=400, label_visibility="collapsed")

        with st.expander("미리보기 (HTML)"):
            st.components.v1.html(html_str, height=1400, scrolling=True)
else:
    st.info("파일을 업로드하면 이어서 진행할 수 있어요.")
