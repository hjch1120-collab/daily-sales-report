import streamlit as st

st.set_page_config(
    page_title="포쿨_온라인팀 보고서",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("📊 포쿨_온라인팀 보고서")
st.caption("아래 버튼을 눌러 원하는 보고서로 이동해주세요.")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/1_일일보고서.py", label="📄 일일보고서 열기", icon="📄", use_container_width=True)
    st.caption("RAW 엑셀(또는 1차가공 CSV)을 올리면 A4 1페이지 PDF 일일 판매보고서를 바로 만들어드립니다.")
with col2:
    st.page_link("pages/2_월간보고서.py", label="📆 월간보고서 열기", icon="📆", use_container_width=True)
    st.caption("준비 중입니다.")

st.divider()
st.caption("버튼이 안 보이면, 화면 왼쪽 가장자리의 \">\" 아이콘을 눌러 사이드바를 펼쳐서 메뉴를 선택하실 수도 있어요.")
