import streamlit as st

st.set_page_config(
    page_title="포쿨_온라인팀 보고서",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("📊 포쿨_온라인팀 보고서")
st.caption("아래 링크를 눌러 원하는 보고서로 이동해주세요.")

st.divider()

st.markdown(
    """
<style>
.report-link {
    display: block;
    padding: 16px 20px;
    margin-bottom: 12px;
    border: 1px solid #e3e3ea;
    border-radius: 8px;
    text-decoration: none;
    color: #1a1a2e;
    background: #fafafc;
    font-weight: 600;
    font-size: 16px;
}
.report-link:hover { background: #f0f0f5; }
.report-link .desc { display: block; font-weight: 400; font-size: 12px; color: #888; margin-top: 4px; }
</style>
<a class="report-link" href="일일보고서" target="_self">
📄 일일보고서 열기
<span class="desc">RAW 엑셀(또는 1차가공 CSV)을 올리면 A4 1페이지 PDF 일일 판매보고서를 바로 만들어드립니다.</span>
</a>
<a class="report-link" href="월간보고서" target="_self">
📆 월간보고서 열기
<span class="desc">준비 중입니다.</span>
</a>
""",
    unsafe_allow_html=True,
)

st.divider()
st.caption("링크가 안 눌리면, 화면 왼쪽 가장자리의 \">\" 아이콘을 눌러 사이드바를 펼쳐서 메뉴를 선택하실 수도 있어요.")
