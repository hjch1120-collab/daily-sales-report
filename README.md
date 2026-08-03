# 일일 판매 보고서 웹앱

RAW 엑셀 또는 1차가공 CSV를 업로드하면 A4 1페이지 PDF 일일 보고서를 만들어주는 Streamlit 웹앱입니다.

## 로컬에서 먼저 테스트해보기 (선택)

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속하면 바로 써볼 수 있습니다.

## 팀원들과 공유하기 (Streamlit Community Cloud, 무료)

1. https://github.com 에서 새 저장소(Repository)를 하나 만듭니다. (Private로 해도 됩니다)
2. 이 폴더 안의 파일들을 전부 그 저장소에 업로드합니다.
   - app.py
   - build_report.py
   - make_html.py
   - extract_raw.py
   - requirements.txt
   - packages.txt
3. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
4. "New app" → 방금 만든 저장소 선택 → Main file path에 `app.py` 입력 → Deploy
5. 몇 분 뒤 `https://xxxx.streamlit.app` 같은 링크가 생성됩니다. 이 링크를 팀원들에게 공유하면 됩니다.

### 참고
- 첫 실행(또는 앱이 잠시 잠들었다가 깨어날 때) PDF 생성이 1~2분 정도 느릴 수 있습니다. Chromium을 자동으로 설치하는 과정이 한 번 들어가기 때문입니다. 그 다음부터는 빠릅니다.
- 이번 달 목표매출은 화면의 "이번 달 목표매출 설정"에서 입력하면 그 세션에서 반영됩니다. 매달 고정으로 쓰려면 `build_report.py`의 `MONTHLY_TARGETS` 딕셔너리에 직접 추가해두는 걸 추천합니다.
- 로직(매출액 산정, 채널 그룹, 급증/급감 기준 등)을 수정하고 싶으면 `build_report.py`만 고치면 됩니다. 지금 쓰고 있는 로직과 동일한 파일입니다.
