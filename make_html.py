import json

def krw(n):
    n = int(round(n))
    return f"{n:,}원"

def krw_k(n):
    n = int(round(n / 1000))
    return f"{n:,}천원"

def pct_badge(p):
    if p is None:
        return '<span class="badge flat">-</span>'
    cls = 'up' if p > 0 else ('down' if p < 0 else 'flat')
    sign = '+' if p > 0 else ''
    arrow = '▲' if p > 0 else ('▼' if p < 0 else '·')
    return f'<span class="badge {cls}">{arrow} {sign}{p}%</span>'

def diff_badge(n):
    n = int(round(n))
    cls = 'up' if n > 0 else ('down' if n < 0 else 'flat')
    sign = '+' if n > 0 else ''
    arrow = '▲' if n > 0 else ('▼' if n < 0 else '·')
    return f'<span class="badge {cls}">{arrow} {sign}{n:,}원</span>'

def build_html(data):
    d = data['daily']
    w = data['weekly']
    mo = data['monthly']

    bm = d.get('best_model')
    if bm:
        best_model_html = f"""
      <div class="value model-name">{bm['원품명']}</div>
      <div class="meta">{bm['수량']:,}개 &nbsp;·&nbsp; {krw(bm['매출액'])}</div>"""
    else:
        best_model_html = """<div class="value model-name">-</div><div class="meta">기준일 판매 데이터 없음</div>"""

    summary_html = f"""
        <div class="summary{' warn' if data.get('incomplete_warning') else ''}">
          {'⚠ ' if data.get('incomplete_warning') else '📌 '}{data.get('summary', '')}
        </div>"""

    # 주간 매출 추이 (최근 3주)
    wt_rows = ""
    for wt in data.get('weekly_trend', []):
        row_cls = ' class="current-week"' if wt.get('is_current') else ''
        wt_rows += f"""<tr{row_cls}><td class="name">{wt['range']}{' (이번주)' if wt.get('is_current') else ''}</td>
          <td class="num">{krw(wt['revenue'])}</td>
          <td class="num">{pct_badge(wt['revenue_pct'])}</td></tr>"""
    if not data.get('weekly_trend'):
        wt_rows = '<tr><td colspan="3" class="empty">데이터 없음</td></tr>'

    # 월 목표매출 대비 진행률
    if mo.get('target_revenue'):
        target_html = f"""<div class="meta sub-line">목표매출 {krw(mo['target_revenue'])} 대비 {pct_badge(mo['target_pct'])}</div>"""
    else:
        target_html = ""

    # 관리모델 (직전 7일 평균 대비 형식)
    def ratio_txt(r):
        return f"{r}배" if r is not None else "신규"

    mm_rows = ""
    for i, m in enumerate(data['manage_models'], 1):
        r = m['ratio']
        cls = 'down-text' if (r is not None and r < 1) else 'up-text'
        mm_rows += f"""<tr><td class="rank">{i}</td><td class="name">{m['원품명']}</td>
          <td class="num">{m['today_qty']}개</td><td class="num">{m['avg7']}개</td>
          <td class="num highlight {cls}">{ratio_txt(r)}</td></tr>"""
    if not data['manage_models']:
        mm_rows = '<tr><td colspan="5" class="empty">기준일 판매 데이터 없음</td></tr>'

    # 특이 매출수량 - 급증
    spike_rows = ""
    for s in data['spikes']:
        spike_rows += f"""<tr><td class="name">{s['원품명']}</td>
          <td class="num">{s['today_qty']}개</td><td class="num">{s['avg7']}개</td>
          <td class="num highlight up-text">{ratio_txt(s['ratio'])}</td></tr>"""
    if not data['spikes']:
        spike_rows = '<tr><td colspan="4" class="empty">직전 7일 평균 대비 특이 급증 모델 없음</td></tr>'

    # 특이 매출수량 - 급감
    drop_rows = ""
    for s in data.get('drops', []):
        drop_rows += f"""<tr><td class="name">{s['원품명']}</td>
          <td class="num">{s['today_qty']}개</td><td class="num">{s['avg7']}개</td>
          <td class="num highlight down-text">{ratio_txt(s['ratio'])}</td></tr>"""
    if not data.get('drops'):
        drop_rows = '<tr><td colspan="4" class="empty">직전 7일 평균 대비 특이 급감 모델 없음</td></tr>'

    # 주간/월간 TOP5
    def top_rows(lst):
        rows = ""
        for i, m in enumerate(lst, 1):
            rows += f"""<tr><td class="rank">{i}</td><td class="name">{m['원품명']}</td>
              <td class="num">{krw(m['매출액'])}</td></tr>"""
        return rows or '<tr><td colspan="3" class="empty">데이터 없음</td></tr>'

    week_top_rows = top_rows(data['week_top'])
    month_top_rows = top_rows(data['month_top'])

    # 채널별 실적
    ch_rows = ""
    for c in data['channels']:
        ch_rows += f"""<tr><td class="name">{c['채널']}</td>
          <td class="num">{krw(c['매출액'])}</td>
          <td class="num sub">{krw(c['전일매출'])}</td>
          <td class="num">{pct_badge(c['pct'])}</td></tr>"""
    if not data['channels']:
        ch_rows = '<tr><td colspan="4" class="empty">기준일 채널 매출 없음</td></tr>'

    # 취소 TOP3
    cancel_rows = ""
    for i, c in enumerate(data['cancel_top'], 1):
        cancel_rows += f"""<tr><td class="rank">{i}</td><td class="name">{c['원품명']}</td>
          <td class="num">{int(c['취소수량']):,}개</td><td class="num">{krw(c['취소금액'])}</td></tr>"""
    if not data['cancel_top']:
        cancel_rows = '<tr><td colspan="4" class="empty">당월 취소 데이터 없음</td></tr>'

    # 요일별 평균 매출 vs 최근 실적 (직전 3주 평균, 최근값 자기참조 제외)
    wd_rows = ""
    for w_ in data.get('weekday_summary', []):
        row_cls = ' class="current-week"' if w_.get('is_today') else ''
        if w_.get('최근매출') is not None:
            recent_amt = krw_k(w_['최근매출'])
            recent_date = w_['최근날짜']
            recent_badge = pct_badge(w_['최근pct'])
        else:
            recent_amt = '<span class="dim">-</span>'
            recent_date = ''
            recent_badge = ''
        wd_rows += f"""<tr{row_cls}><td class="name">{w_['요일']}요일{' (기준일)' if w_.get('is_today') else ''}</td>
          <td class="num">{krw_k(w_['평균매출'])}</td>
          <td class="num">{recent_amt}</td>
          <td class="num wd-date-col">{recent_date}</td>
          <td class="num">{recent_badge}</td></tr>"""
    if not data.get('weekday_summary'):
        wd_rows = '<tr><td colspan="5" class="empty">데이터 없음</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', sans-serif;
    width: 210mm;
    color: #1a1a2e;
    background: #ffffff;
    zoom: 1.3025;
  }}
  .page {{ width: 210mm; height: 297mm; padding: 12mm 13mm; display: flex; flex-direction: column; }}

  .header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    border-bottom: 3px solid #1a1a2e; padding-bottom: 8px; margin-bottom: 10px;
  }}
  .header h1 {{ font-size: 20px; letter-spacing: -0.3px; }}
  .header .sub {{ font-size: 11px; color: #666; margin-top: 3px; }}
  .header .date-badge {{
    background: #1a1a2e; color: #fff; font-size: 13px; font-weight: 700;
    padding: 6px 14px; border-radius: 4px;
  }}

  .summary {{
    background: #eef2ff; border: 1px solid #c7d2fe; color: #33389b;
    font-size: 11px; padding: 7px 10px; border-radius: 4px; margin-bottom: 10px; font-weight: 500;
  }}
  .summary.warn {{
    background: #fff4e5; border: 1px solid #f0b429; color: #8a5a00;
  }}

  .kpi-row {{ display: flex; gap: 10px; margin-bottom: 12px; }}
  .kpi {{
    flex: 1; border: 1px solid #e3e3ea; border-radius: 6px; padding: 10px 13px;
    background: #fafafc;
  }}
  .kpi .label {{
    font-size: 12px; font-weight: 700; color: #1a1a2e; margin-bottom: 7px;
    border-left: 3px solid #1a1a2e; padding-left: 6px; line-height: 1.2;
    white-space: nowrap; overflow: hidden;
  }}
  .kpi .value {{ font-size: 18px; font-weight: 700; }}
  .kpi .value .qty-inline {{ font-size: 12px; font-weight: 500; color: #888; }}
  .kpi .value.model-name {{ font-size: 15px; letter-spacing: -0.2px; }}
  .kpi .meta {{ font-size: 10px; color: #888; margin-top: 4px; }}
  .kpi .meta.sub-line {{ margin-top: 5px; padding-top: 5px; border-top: 1px dashed #e3e3ea; }}
  .monthly-kpi {{ display: flex; flex-direction: column; }}

  .weekly-trend-box {{ padding-bottom: 7px; }}
  .mini-table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
  .mini-table th {{ text-align: left; font-size: 9px; color: #999; font-weight: 500; padding: 3px 3px; border-bottom: 1px solid #e3e3ea; }}
  .mini-table td {{ font-size: 11px; padding: 4px 3px; border-bottom: 1px solid #f0f0f4; }}
  .mini-table td.name {{ font-weight: 600; }}
  .mini-table td.num {{ text-align: right; }}
  .mini-table tr.current-week td {{ font-weight: 700; color: #1a1a2e; }}
  .mini-table tr:last-child td {{ border-bottom: none; }}

  .badge {{
    font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 3px;
    display: inline-block; min-width: 54px; text-align: center; box-sizing: border-box;
  }}
  .badge.up {{ background: #e6f7ee; color: #0a8a3e; }}
  .badge.down {{ background: #feeaea; color: #d1372f; }}
  .badge.flat {{ background: #eee; color: #888; }}

  .layout-wrap {{ display: block; }}
  .layout-row {{
    width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 10px;
  }}
  .layout-row > tr > td {{ width: 50%; vertical-align: top; padding: 0; }}
  .split-row > tr > td {{ width: auto; }}
  .layout-row > tr > td:first-child {{ padding-right: 9px; }}
  .layout-row > tr > td:last-child {{ padding-left: 9px; }}
  .layout-row .section {{ margin-top: 0; margin-bottom: 0; }}

  .section {{
    border: 1px solid #e3e3ea; border-radius: 6px; padding: 11px 13px; margin-bottom: 10px;
  }}
  .section h2 {{
    font-size: 12px; font-weight: 700; margin-bottom: 7px; color: #1a1a2e;
    border-left: 3px solid #1a1a2e; padding-left: 6px; line-height: 1.2;
    white-space: nowrap; overflow: hidden;
  }}
  .section h2 .h2-sub {{ font-size: 9.5px; font-weight: 400; color: #999; margin-left: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10.5px; }}
  th {{
    text-align: left; font-size: 9.5px; color: #888; font-weight: 500;
    padding: 4px 4px; border-bottom: 1px solid #e3e3ea;
  }}
  td {{ padding: 5px 4px; border-bottom: 1px solid #f0f0f4; }}
  td.rank {{ color: #aaa; font-weight: 700; width: 16px; }}
  td.name {{ font-weight: 600; }}
  td.num {{ text-align: right; }}
  td.sub {{ color: #999; }}
  td.highlight {{ color: #d1372f; font-weight: 700; }}
  td.up-text {{ color: #d1372f; }}
  td.down-text {{ color: #1a6fd1; }}
  td.empty {{ text-align: center; color: #aaa; padding: 10px; }}
  td .dim {{ color: #ccc; }}
  .wd-date-col {{ font-size: 9px; color: #999; }}
  table tr.current-week td {{ font-weight: 700; color: #1a1a2e; background: #f7f8fc; }}

  .footer {{ margin-top: 8px; font-size: 8.5px; color: #aaa; text-align: right; }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div>
      <h1>일일 판매 보고서</h1>
      <div class="sub">주문일자 기준 · {d['date']} ({d['weekday']}요일)</div>
    </div>
    <div class="date-badge">{d['send_date']}</div>
  </div>

  {summary_html}

  <div class="kpi-row">
    <div class="kpi">
      <div class="label">일간 매출 (전일 대비)</div>
      <div class="value">{krw(d['revenue'])}</div>
      <div class="meta">{pct_badge(d['revenue_pct'])} &nbsp;전일 {krw(d['prev_revenue'])}</div>
    </div>
    <div class="kpi">
      <div class="label">일간 판매수량 (전일 대비)</div>
      <div class="value">{d['qty']:,}개</div>
      <div class="meta">{pct_badge(d['qty_pct'])} &nbsp;전일 {d['prev_qty']:,}개</div>
    </div>
    <div class="kpi">
      <div class="label">일간 베스트모델 (판매수량 1위)</div>
      {best_model_html}
    </div>
  </div>

  <div class="kpi-row">
    <div class="kpi weekly-trend-box">
      <div class="label">주간 매출 추이 (최근 3주 · 전주 대비)</div>
      <table class="mini-table">
        <tr><th>기간</th><th style="text-align:right">매출액</th><th style="text-align:right">증감</th></tr>
        {wt_rows}
      </table>
    </div>
    <div class="kpi monthly-kpi">
      <div class="label">{mo['range']} 누적매출</div>
      <div class="value">{krw(mo['revenue'])} <span class="qty-inline">· {mo['qty']:,}개</span></div>
      <div class="meta sub-line">전월({mo['prev_month_full_range']}) 총매출 {krw(mo['prev_month_full_revenue'])}</div>
      <div class="meta">차이 {diff_badge(mo['revenue'] - mo['prev_month_full_revenue'])}</div>
      {target_html}
    </div>
  </div>

  <div class="layout-wrap">
    <table class="layout-row split-row">
      <colgroup><col style="width:66%"><col style="width:34%"></colgroup>
      <tr>
        <td class="section">
          <h2>요일별 매출 비교 <span class="h2-sub">직전 3주 평균 vs 최근 실적</span></h2>
          <table>
            <tr><th>요일</th><th style="text-align:right">3주 평균매출</th><th style="text-align:right">최근매출</th><th style="text-align:right">날짜</th><th style="text-align:right">증감</th></tr>
            {wd_rows}
          </table>
        </td>
        <td class="section">
          <h2>취소 다발 모델 <span class="h2-sub">{data['cancel_range_label']} · TOP3</span></h2>
          <table>
            <tr><th></th><th>모델명</th><th style="text-align:right">취소수량</th><th style="text-align:right">취소금액</th></tr>
            {cancel_rows}
          </table>
        </td>
      </tr>
    </table>
    <table class="layout-row">
      <tr>
        <td class="section">
          <h2>특이 매출수량 - 급증 <span class="h2-sub">직전 7일 평균 대비</span></h2>
          <table>
            <tr><th>모델명</th><th style="text-align:right">당일수량</th><th style="text-align:right">7일평균</th><th style="text-align:right">배율</th></tr>
            {spike_rows}
          </table>
        </td>
        <td class="section">
          <h2>특이 매출수량 - 급감 <span class="h2-sub">직전 7일 평균 대비</span></h2>
          <table>
            <tr><th>모델명</th><th style="text-align:right">당일수량</th><th style="text-align:right">7일평균</th><th style="text-align:right">배율</th></tr>
            {drop_rows}
          </table>
        </td>
      </tr>
    </table>
  </div>

  <div class="footer">&nbsp;</div>

</div>
</body>
</html>"""
    return html

if __name__ == '__main__':
    with open('report_data.json', encoding='utf-8') as f:
        data = json.load(f)
    html = build_html(data)
    with open('report.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("done")
