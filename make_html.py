import json


def krw(n):
    n = int(round(n))
    return f"{n:,}원"


def pct_badge(p):
    if p is None:
        return '<span class="badge flat">-</span>'
    cls = 'up' if p > 0 else ('down' if p < 0 else 'flat')
    sign = '+' if p > 0 else ''
    arrow = '▲' if p > 0 else ('▼' if p < 0 else '·')
    return f'<span class="badge {cls}">{arrow} {sign}{p}%</span>'


def sparkline_svg(values, color):
    """급증/급감 표용 짧은 스파크라인 (8일)"""
    w, h, pad = 60, 18, 2
    n = len(values)
    maxv = max(values) if max(values) > 0 else 1
    step = (w - 2 * pad) / (n - 1)
    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = h - pad - (v / maxv) * (h - 2 * pad)
        pts.append((x, y))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    last_x, last_y = pts[-1]
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.3" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity="0.85"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2" fill="{color}"/></svg>')


def sparkline_svg_long(values, baseline, color, w=200, h=26, pad=2):
    """체크모델용 장기 추세 + 기준평균 점선. width=100%로 렌더링되어 컨테이너(셀) 폭에 맞춰 늘어남."""
    n = len(values)
    maxv = max(max(values), baseline) if max(max(values), baseline) > 0 else 1
    step = (w - 2 * pad) / (n - 1)
    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = h - pad - (v / maxv) * (h - 2 * pad)
        pts.append((x, y))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    last_x, last_y = pts[-1]
    area = f"{pad},{h - pad} " + path + f" {last_x:.1f},{h - pad}"
    base_y = h - pad - (baseline / maxv) * (h - 2 * pad)
    return (f'<svg width="100%" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="display:block">'
            f'<polygon points="{area}" fill="{color}" opacity="0.08"/>'
            f'<line x1="{pad}" y1="{base_y:.1f}" x2="{w - pad}" y2="{base_y:.1f}" '
            f'stroke="#999" stroke-width="0.8" stroke-dasharray="2.5,1.8"/>'
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.1" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity="0.85" vector-effect="non-scaling-stroke"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="1.8" fill="{color}"/></svg>')



def build_html(data, zoom=0.92):
    d = data['daily']
    wt = data['weekly_trend']
    mo = data['monthly']
    report_month_num = int(d['date'].split('-')[1])
    check_models = data.get('check_models', [])
    new_sale = data.get('new_sale', {'silent_60': [], 'gap_30': []})
    spikes = data.get('spikes', [])
    drops = data.get('drops', [])
    drops_is_fallback = data.get('drops_is_fallback', False)
    long_decline_models = data.get('long_decline_models', [])
    wd_name = data.get('baseline_wd_name', '')
    occurrences = data.get('baseline_occurrences', 0)
    long_occ = data.get('long_trend_occurrences', 0)
    manage_names = set(data.get('manual_check_models', []))

    bm = d.get('best_model')
    if bm:
        best_model_html = (f'<div class="value model-name">{bm["원품명"]}</div>'
                            f'<div class="meta">{bm["수량"]:,}개 · {krw(bm["매출액"])}</div>')
    else:
        best_model_html = '<div class="value model-name">-</div><div class="meta">기준일 판매 데이터 없음</div>'

    wt_rows = ""
    for w_ in wt:
        cls = ' class="current-week"' if w_.get('is_current') else ''
        wt_rows += (f'<tr{cls}><td class="name">{w_["range"]}{" (이번주)" if w_.get("is_current") else ""}</td>'
                    f'<td class="num">{krw(w_["revenue"])}</td><td class="num">{pct_badge(w_["revenue_pct"])}</td></tr>')
    if not wt:
        wt_rows = '<tr><td colspan="3" class="empty">데이터 없음</td></tr>'

    proj_html = ""
    if mo.get('projected_revenue'):
        proj_html = (
            f'<div class="meta sub-line">예상 {report_month_num}월 총매출 <b>{krw(mo["projected_revenue"])}</b>'
            f'<div class="meta-note">(과거 {mo["projection_months"]}개월 평균 진행률 {mo["projection_ratio"]}% 보정)</div></div>'
        )

    if mo.get('target_revenue'):
        if mo.get('projected_target_pct') is not None:
            pct_val = mo['projected_target_pct']
            badge = f'<span class="badge {"up" if pct_val >= 100 else "down"}">{"▲" if pct_val >= 100 else "▼"} {pct_val}%</span>'
            target_html = f'{proj_html}<div class="meta sub-line">목표매출 {krw(mo["target_revenue"])} · 예상 달성률 {badge}</div>'
        else:
            target_html = f'{proj_html}<div class="meta sub-line">목표매출 {krw(mo["target_revenue"])} 대비 {pct_badge(mo["target_pct"])}</div>'
    else:
        target_html = proj_html

    def name_cell(name):
        star = '<span class="mstar">★</span>' if name in manage_names else ''
        return f'{star}{name}'

    # 체크모델 (1순위: 급감 1순위 자동 반영 / 2순위: 직접 입력한 관리모델)
    # 순위 뱃지는 소속 그룹이 아니라 실제 급증/급감 기준(diff)으로 계산된 순위. 기준 미달이면 빈칸.
    check_rows = ""
    for m in check_models:
        spark = sparkline_svg_long(m['trend60'], m['baseline'], '#7c3aed')
        diff_v = m['diff']
        sign = '+' if diff_v > 0 else ''
        dcls = 'up-text' if diff_v > 0 else ('down-text' if diff_v < 0 else '')
        star = '★ ' if m['원품명'] in manage_names else ''
        if m.get('rank_tier'):
            tier_cls = 'up-text' if m['rank_type'] == 'spike' else 'down-text'
            tier_badge = f'<span class="tier-badge {tier_cls}">{m["rank_tier"]}순위</span>'
        else:
            tier_badge = ''
        check_rows += (f'<tr><td class="name">{star}{m["원품명"]}</td><td class="tier-cell">{tier_badge}</td>'
                        f'<td class="spark-cell-long">{spark}</td>'
                        f'<td class="num base">{m["baseline"]}</td><td class="num today">{m["today_qty"]}</td>'
                        f'<td class="num diff {dcls}">{sign}{diff_v}</td></tr>')
    if not check_models:
        check_rows = '<tr><td colspan="6" class="empty">체크모델 없음</td></tr>'

    silent_60 = new_sale.get('silent_60', [])
    gap_30 = new_sale.get('gap_30', [])
    new_sale_total = len(silent_60) + len(gap_30)
    new_sale_chips = ("".join(f'<span class="chip chip-new">{name_cell(n)}</span>' for n in silent_60) +
                       "".join(f'<span class="chip chip-gap">{name_cell(n)}</span>' for n in gap_30))
    if not new_sale_chips:
        new_sale_chips = '<span class="empty">신규 판매 모델 없음</span>'

    def build_tier_rows(records, color, cls):
        rows = ""
        highlight_color = '#7c3aed'  # 직전7일: 평균/기준일/증감과 같은 축이라 구분되는 강조색 사용
        for r in records:
            source = r.get('source', '직전7일')
            month_is_primary = (source == '1개월')

            spark_3mo_sd = sparkline_svg(r['trend_3mo_sameday'], color)
            spark_3mo = sparkline_svg(r['trend_3mo'], color)
            spark_month = sparkline_svg(r['trend_month'], highlight_color if month_is_primary else color)
            spark_lastweek = sparkline_svg(r['trend_last_week'], color)
            spark_week = sparkline_svg(r['trend_week'], color if month_is_primary else highlight_color)
            sign = '+' if r['diff'] > 0 else ''
            consistency = r.get('trend_consistency')
            if consistency == 'down':
                consist_badge = '<span class="consist-badge consist-down">하락↓</span>'
            elif consistency == 'up':
                consist_badge = '<span class="consist-badge consist-up">상승↑</span>'
            else:
                consist_badge = ''
            source_tag = '<span class="source-tag">1개월기준</span>' if month_is_primary else ''

            month_cell_cls = 'spark-cell spark-cell-highlight' if month_is_primary else 'spark-cell'
            month_cell_label = f'<b>기준평균 {r["baseline"]}</b>' if month_is_primary else f'일평균 {r["avg_month"]}'
            week_cell_cls = 'spark-cell' if month_is_primary else 'spark-cell spark-cell-highlight'
            week_cell_label = f'일평균 {r["avg_week"]}' if month_is_primary else f'<b>기준평균 {r["baseline"]}</b>'

            rows += (f'<tr><td class="name">{name_cell(r["원품명"])}{consist_badge}{source_tag}</td>'
                      f'<td class="tier-cell"><span class="tier-badge {cls}">{r["tier"]}순위</span></td>'
                      f'<td class="spark-cell">{spark_3mo_sd}<div class="spark-avg">평균 {r["avg_3mo_sameday"]}</div></td>'
                      f'<td class="spark-cell">{spark_3mo}<div class="spark-avg">일평균 {r["avg_3mo"]}</div></td>'
                      f'<td class="{month_cell_cls}">{spark_month}<div class="spark-avg">{month_cell_label}</div></td>'
                      f'<td class="spark-cell">{spark_lastweek}<div class="spark-avg">일평균 {r["avg_last_week"]}</div></td>'
                      f'<td class="{week_cell_cls}">{spark_week}<div class="spark-avg">{week_cell_label}</div></td>'
                      f'<td class="num today">{r["today_qty"]}</td><td class="num diff {cls}">{sign}{r["diff"]}</td></tr>')
        return rows or '<tr><td colspan="9" class="empty">해당 없음</td></tr>'



    spike_rows = build_tier_rows(spikes, '#d1372f', 'up-text')
    drop_rows = build_tier_rows(drops, '#1a6fd1', 'down-text')

    long_decline_rows = ""
    for m in long_decline_models:
        long_decline_rows += (
            f'<tr><td class="name">{name_cell(m["원품명"])}</td>'
            f'<td class="num">{m["avg_3mo"]}</td><td class="num">{m["avg_2mo"]}</td><td class="num">{m["avg_month"]}</td>'
            f'<td class="num">{m["today_qty"]}</td>'
            f'<td class="num down-text">-{m["drop1_pct"]}%→-{m["drop2_pct"]}%</td></tr>'
        )
    long_decline_rows = long_decline_rows or '<tr><td colspan="6" class="empty">해당 없음</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', sans-serif;
    width: 210mm; color: #1a1a2e; background: #ffffff; zoom: {zoom};
  }}
  .page {{ width: 210mm; height: 297mm; padding: 10mm 12mm; display: flex; flex-direction: column; }}

  .header {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid #1a1a2e; padding-bottom: 8px; margin-bottom: 10px; }}
  .header h1 {{ font-size: 20px; letter-spacing: -0.3px; }}
  .header .sub {{ font-size: 11px; color: #666; margin-top: 3px; }}
  .header .date-badge {{ background: #1a1a2e; color: #fff; font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 4px; }}

  .kpi-row {{ display: flex; gap: 10px; margin-bottom: 10px; }}
  .kpi {{ flex: 1; border: 1px solid #e3e3ea; border-radius: 6px; padding: 9px 12px; background: #fafafc; }}
  .kpi .label {{ font-size: 11.5px; font-weight: 700; color: #1a1a2e; margin-bottom: 6px; border-left: 3px solid #1a1a2e; padding-left: 6px; white-space: nowrap; }}
  .kpi .value {{ font-size: 17px; font-weight: 700; }}
  .kpi .value .qty-inline {{ font-size: 11px; font-weight: 500; color: #888; }}
  .kpi .value.model-name {{ font-size: 14px; }}
  .kpi .meta {{ font-size: 9.5px; color: #888; margin-top: 3px; }}
  .kpi .meta.sub-line {{ margin-top: 4px; padding-top: 4px; border-top: 1px dashed #e3e3ea; }}
  .meta-note {{ font-size: 8px; color: #888; margin-top: 2px; font-weight: 400; }}
  .kpi.kpi-blue {{ border-left: 3px solid #2563eb; background: #eff6ff; }}
  .kpi.kpi-blue .label {{ border-left-color: #2563eb; }}
  .kpi.kpi-green {{ border-left: 3px solid #059669; background: #ecfdf5; }}
  .kpi.kpi-green .label {{ border-left-color: #059669; }}
  .kpi.kpi-amber {{ border-left: 3px solid #d97706; background: #fffbeb; }}
  .kpi.kpi-amber .label {{ border-left-color: #d97706; }}
  .kpi.kpi-indigo {{ border-left: 3px solid #4f46e5; background: #eef2ff; }}
  .kpi.kpi-indigo .label {{ border-left-color: #4f46e5; }}
  .kpi.kpi-purple {{ border-left: 3px solid #7c3aed; background: #f5f3ff; }}
  .kpi.kpi-purple .label {{ border-left-color: #7c3aed; }}
  .monthly-kpi {{ display: flex; flex-direction: column; }}

  .mini-table {{ width: 100%; border-collapse: collapse; margin-top: 3px; }}
  .mini-table th {{ text-align: left; font-size: 8.5px; color: #999; font-weight: 500; padding: 2px 3px; border-bottom: 1px solid #e3e3ea; }}
  .mini-table td {{ font-size: 10px; padding: 3px 3px; border-bottom: 1px solid #f0f0f4; }}
  .mini-table td.name {{ font-weight: 600; }}
  .mini-table td.num {{ text-align: right; }}
  .mini-table tr.current-week td {{ font-weight: 700; }}
  .mini-table tr:last-child td {{ border-bottom: none; }}

  .badge {{ font-size: 9.5px; font-weight: 700; padding: 1px 6px; border-radius: 3px; display: inline-block; min-width: 48px; text-align: center; box-sizing: border-box; }}
  .badge.up {{ background: #e6f7ee; color: #0a8a3e; }}
  .badge.down {{ background: #feeaea; color: #d1372f; }}
  .badge.flat {{ background: #eee; color: #888; }}

  .section {{ border: 1px solid #e3e3ea; border-radius: 6px; padding: 6px 11px; margin-bottom: 5px; }}
  .section.manage {{ border: 1.5px solid #c4b5fd; background: #faf9ff; }}
  .section h2 {{ font-size: 11px; font-weight: 700; margin-bottom: 5px; border-left: 3px solid #1a1a2e; padding-left: 6px; }}
  .section.manage h2 {{ border-left-color: #7c3aed; }}
  .section h2 .sub {{ font-size: 8.5px; font-weight: 400; color: #999; margin-left: 4px; }}
  .section h2 .cnt {{ font-size: 9px; font-weight: 700; color: #33389b; background: #eef2ff; padding: 1px 6px; border-radius: 8px; margin-left: 5px; }}

  table.data {{ width: 100%; border-collapse: collapse; font-size: 9.5px; table-layout: fixed; }}
  table.data th {{ text-align: left; font-size: 8px; color: #888; font-weight: 500; padding: 2px 3px; border-bottom: 1px solid #e3e3ea; }}
  table.data td {{ padding: 2px 3px; border-bottom: 1px solid #f0f0f4; vertical-align: middle; }}
  table.data td.name {{ font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  table.data td.num {{ text-align: right; }}
  table.data td.base {{ color: #999; }}
  table.data td.today {{ font-weight: 600; }}
  table.data td.diff {{ font-weight: 700; }}
  table.data td.diffpct {{ font-weight: 700; font-size: 9px; }}
  table.data td.tier-cell, table.data td.spark-cell, table.data td.spark-cell-long {{ text-align: center; }}
  table.data svg {{ display: block; margin: 0 auto; }}
  .spark-avg {{ font-size: 7px; color: #999; margin-top: 1px; }}
  .spark-cell-highlight {{ background: #f5f2ff; border-radius: 4px; }}
  .consist-badge {{ font-size: 7px; font-weight: 700; padding: 0px 4px; border-radius: 6px; margin-left: 3px; display: inline-block; vertical-align: middle; }}
  .consist-badge.consist-down {{ background: #eaf1fe; color: #1a6fd1; }}
  .consist-badge.consist-up {{ background: #feeaea; color: #d1372f; }}
  .source-tag {{ font-size: 7px; font-weight: 700; padding: 0px 4px; border-radius: 6px; margin-left: 3px; display: inline-block; vertical-align: middle; background: #fef3c7; color: #92400e; }}
  .up-text {{ color: #d1372f; }}
  .down-text {{ color: #1a6fd1; }}
  table.data tr:last-child td {{ border-bottom: none; }}
  table.data td.empty {{ text-align: center; color: #aaa; padding: 8px; }}

  .tier-badge {{ font-size: 8px; font-weight: 700; padding: 1px 5px; border-radius: 8px; display: inline-block; }}
  .tier-badge.up-text {{ background: #feeaea; color: #d1372f; }}
  .tier-badge.down-text {{ background: #eaf1fe; color: #1a6fd1; }}

  .chip-wrap {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .chip {{ background: #fff; border: 1px solid #e3e3ea; font-size: 9.5px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }}
  .chip.chip-new {{ background: #f3e8ff; border-color: #c4b5fd; color: #6d28d9; }}
  .chip.chip-gap {{ background: #f4f4f8; border-color: #e3e3ea; color: #1a1a2e; }}
  .mstar {{ color: #7c3aed; margin-right: 2px; }}
  .legend {{ font-size: 8px; color: #999; display: flex; gap: 10px; margin-top: 5px; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 3px; }}
  .dot {{ width: 6px; height: 6px; border-radius: 50%; display: inline-block; }}
  .dot-new {{ background: #8b5cf6; }}
  .dot-gap {{ background: #aaa; }}

  .footer {{ margin-top: auto; font-size: 8px; color: #aaa; text-align: right; }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div>
      <h1>포쿨_온라인팀_일일보고서</h1>
      <div class="sub">주문일자 기준 · {d['date']} ({d['weekday']}요일)</div>
    </div>
    <div class="date-badge">{d['send_date']}</div>
  </div>

  <div class="kpi-row">
    <div class="kpi kpi-blue">
      <div class="label">일간 매출 (전일 대비)</div>
      <div class="value">{krw(d['revenue'])}</div>
      <div class="meta">{pct_badge(d['revenue_pct'])} &nbsp;전일 {krw(d['prev_revenue'])}</div>
      <div class="meta sub-line">{pct_badge(d['prev_sameweekday_revenue_pct'])} &nbsp;전주 {d['prev_sameweekday_weekday']}요일 {krw(d['prev_sameweekday_revenue'])}</div>
    </div>
    <div class="kpi kpi-green">
      <div class="label">일간 판매수량 (전일 대비)</div>
      <div class="value">{d['qty']:,}개</div>
      <div class="meta">{pct_badge(d['qty_pct'])} &nbsp;전일 {d['prev_qty']:,}개</div>
      <div class="meta sub-line">{pct_badge(d['prev_sameweekday_qty_pct'])} &nbsp;전주 {d['prev_sameweekday_weekday']}요일 {d['prev_sameweekday_qty']:,}개</div>
    </div>
    <div class="kpi kpi-amber">
      <div class="label">일간 베스트모델</div>
      {best_model_html}
    </div>
  </div>

  <div class="kpi-row">
    <div class="kpi kpi-indigo">
      <div class="label">주간 매출 추이 (최근 3주)</div>
      <table class="mini-table"><tr><th>기간</th><th style="text-align:right">매출액</th><th style="text-align:right">증감</th></tr>{wt_rows}</table>
    </div>
    <div class="kpi monthly-kpi kpi-purple">
      <div class="label">{mo['range']} 누적매출</div>
      <div class="value">{krw(mo['revenue'])} <span class="qty-inline">· {mo['qty']:,}개</span></div>
      <div class="meta sub-line">전월({mo['prev_month_full_range']}) 총매출 {krw(mo['prev_month_full_revenue'])}</div>
      {target_html}
    </div>
  </div>

  <div class="section manage">
    <h2>★ 체크모델<span class="sub">모델 구성: 급감1순위 자동 + 직접입력 · 순위=실제 급증/급감 기준 · 추세 90일(3개월,일단위)·기준평균은 직전7일 일평균</span><span class="cnt">{len(check_models)}건</span></h2>
    <table class="data">
      <colgroup><col style="width:16%"><col style="width:8%"><col style="width:40%"><col style="width:12%"><col style="width:12%"><col style="width:12%"></colgroup>
      <tr><th>모델명</th><th style="text-align:center">순위</th><th style="text-align:center">추세(3개월)+기준선</th><th style="text-align:right">기준평균</th><th style="text-align:right">기준일</th><th style="text-align:right">증감</th></tr>
      {check_rows}
    </table>
  </div>

  <div class="section">
    <h2>급증 모델 (우선순위)<span class="sub">직전 {occurrences}일 일평균 대비 · 추세=2개월(동일요일)/3개월(90일,연속)/1개월(30일)/지난주(월~일)/직전7일(강조·평균기준과 동일)</span><span class="cnt">{len(spikes)}건</span></h2>
    <table class="data">
      <colgroup><col style="width:21%"><col style="width:6%"><col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:11%"><col style="width:14%"><col style="width:8%"><col style="width:9%"></colgroup>
      <tr><th>모델명</th><th style="text-align:center">순위</th><th style="text-align:center">2개월(동일요일)</th><th style="text-align:center">3개월</th><th style="text-align:center">1개월</th><th style="text-align:center">지난주(월~일)</th><th style="text-align:center">직전7일(=기준평균)</th><th style="text-align:right">기준일</th><th style="text-align:right">증감</th></tr>
      {spike_rows}
    </table>
  </div>

  <div class="section">
    <h2>급감 모델 (우선순위)<span class="sub">직전 {occurrences}일 일평균 대비 · 추세=2개월(동일요일)/3개월(90일,연속)/1개월(30일)/지난주(월~일)/직전7일(강조·평균기준과 동일){' · 1~2순위 없어 근접 3순위 5건 표시' if drops_is_fallback else ''}</span><span class="cnt">{len(drops)}건</span></h2>
    <table class="data">
      <colgroup><col style="width:21%"><col style="width:6%"><col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:11%"><col style="width:14%"><col style="width:8%"><col style="width:9%"></colgroup>
      <tr><th>모델명</th><th style="text-align:center">순위</th><th style="text-align:center">2개월(동일요일)</th><th style="text-align:center">3개월</th><th style="text-align:center">1개월</th><th style="text-align:center">지난주(월~일)</th><th style="text-align:center">직전7일(=기준평균)</th><th style="text-align:right">기준일</th><th style="text-align:right">증감</th></tr>
      {drop_rows}
    </table>
  </div>

  <div class="section" style="border-color:#fbbf24; background:#fffdf5;">
    <h2 style="border-left-color:#d97706;">🔻 장기 하락세 모델<span class="sub">3개월→2개월→1개월 일평균 15%+연속 하락 · 오늘의 급감모델(직전7일 기준)과는 별개 지표</span><span class="cnt">{len(long_decline_models)}건</span></h2>
    <table class="data">
      <colgroup><col style="width:22%"><col style="width:16%"><col style="width:16%"><col style="width:16%"><col style="width:15%"><col style="width:15%"></colgroup>
      <tr><th>모델명</th><th style="text-align:right">3개월 일평균</th><th style="text-align:right">2개월 일평균</th><th style="text-align:right">1개월 일평균</th><th style="text-align:right">기준일</th><th style="text-align:right">단계별 하락률</th></tr>
      {long_decline_rows}
    </table>
  </div>

  <div class="section">
    <h2>신규 판매 모델<span class="sub">공백 기간 후 기준일 판매 발생</span><span class="cnt">{new_sale_total}건</span></h2>
    <div class="chip-wrap">{new_sale_chips}</div>
    <div class="legend">
      <span><span class="dot dot-new"></span>60일 침묵 모델 (최근 60일 무판매)</span>
      <span><span class="dot dot-gap"></span>1개월 공백 재판매 (최근 30일 무판매, 31~60일엔 판매 有)</span>
    </div>
  </div>

  <div class="footer" style="text-align:left;">{'예상 달성률 = 예상 총매출 ÷ 목표매출. 예상 총매출은 과거 ' + str(mo['projection_months']) + '개월 평균 진행률로 보정한 값입니다.' if mo.get('projected_revenue') else '&nbsp;'}</div>

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
