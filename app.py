import streamlit as st

st.set_page_config(page_title="포쿨_온라인팀 보고서", page_icon="📊", layout="centered")

st.title("📊 포쿨_온라인팀 보고서")
st.caption("왼쪽 사이드바에서 원하는 보고서를 선택해주세요.")

st.markdown(
    """
### 사용 가능한 보고서

- **일일보고서** — RAW 엑셀(또는 1차가공 CSV)을 올리면 A4 1페이지 PDF 일일 판매보고서를 바로 만들어드립니다.
- **월간보고서** — 준비 중입니다.

왼쪽 사이드바(모바일에서는 화면 좌측 상단 `>` 아이콘)에서 보고서를 선택해주세요.
"""
)
