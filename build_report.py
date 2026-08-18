import pandas as pd
import json

SRC = '/mnt/user-data/uploads/1차가공.csv'

# 월별 목표매출 (YYYY-MM 기준). 새로운 달 목표가 정해지면 여기에 추가.
MONTHLY_TARGETS = {
    '2026-08': 1877763991,
}

# 네-쿠입고: 고객 판매가 아닌 물류센터 입고(재고 이동) 채널. 대량 입고 건이 하루에 몰려 찍히기 때문에
# 판매추이를 왜곡시킴 -> 데이터 로드 단계에서 수량/매출 모두 완전히 제외한다.
STOCK_IN_CHANNELS = {'네이버하우저', '쿠팡로켓그로스'}

# 급증/급감 기준선(baseline) 계산에 사용할 "동일 요일" 개수. 9회 ~= 최근 2개월.
# 요일별 계절성이 있는 상품이라 캘린더 월 경계 대신 "최근 N회 동일 요일" rolling 방식을 사용한다.
BASELINE_OCCURRENCES = 9

# 매출수량 섹션 표시 개수 제한
MAX_TIER_MODELS = 20
SPIKE_MAX_DISPLAY = 5  # 급증모델은 최대 5개만 노출 (3순위 제외, 1~2순위만 대상)

# 급감모델 1~2순위가 하나도 없을 때, 3순위(-1~-1.9) 중 감소폭이 큰 순서로 대신 노출할 개수
DROP_FALLBACK_COUNT = 5

WEEKDAY_NAMES = ['월', '화', '수', '목', '금', '토', '일']


def _read_csv_any_encoding(src):
    """CSV 인코딩이 utf-8-sig가 아닐 수도 있으므로(엑셀에서 바로 저장한 CSV 등) 순서대로 시도한다."""
    last_err = None
    for enc in ('utf-8-sig', 'cp949', 'euc-kr', 'utf-8'):
        try:
            return pd.read_csv(src, encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise last_err


def load(src):
    df = _read_csv_any_encoding(src)
    df = df[df['쇼핑몰'].notna()].copy()
    df = df[~df['쇼핑몰'].isin(STOCK_IN_CHANNELS)].copy()  # 입고 채널 완전 제외 (수량+매출 모두)
    df['수량'] = df['수량'].astype(int)
    df['판매단가'] = df['판매단가'].astype(str).str.replace(',', '').astype(float)
    df['주문일자'] = pd.to_datetime(df['주문일자'])
    df['취소일자'] = pd.to_datetime(df['취소일자'], errors='coerce')
    # 판매단가 컬럼은 채널/수량 무관하게 "해당 라인의 총 매출액"으로 이미 기록되어 있음 -> 그대로 사용
    df['매출액'] = df['판매단가']
    return df


def _pct(cur, prev):
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def _spike_tier(diff):
    if diff >= 3:
        return 1
    if diff >= 2:
        return 2
    if diff >= 1:
        return 3
    return None


def _drop_tier(diff):
    if diff <= -3:
        return 1
    if diff <= -2:
        return 2
    if diff <= -1:
        return 3
    return None


def build(src=SRC, report_date=None, send_date=None, manage_models=None):
    """
    manage_models: 매번 채팅에서 지정하는 관리모델 리스트 (예: ['FRE-465RF', 'FC-49MSW']).
                   순위 기준과 무관하게 항상 별도 섹션에 고정 표시된다.
    """
    manage_models = manage_models or []
    df = load(src)
    valid = df[df['취소일자'].isna()].copy()

    if report_date is None:
        report_date = valid['주문일자'].max()
    else:
        report_date = pd.Timestamp(report_date)
    prev_day = report_date - pd.Timedelta(days=1)

    if send_date is None:
        send_date = report_date + pd.Timedelta(days=1)
    else:
        send_date = pd.Timestamp(send_date)

    today = valid[valid['주문일자'] == report_date]
    yday = valid[valid['주문일자'] == prev_day]
    prev_sameweekday = report_date - pd.Timedelta(days=7)
    pweek = valid[valid['주문일자'] == prev_sameweekday]

    # 1. 일간 매출 / 판매수량 / 베스트모델
    daily = {
        'date': report_date.strftime('%Y-%m-%d'),
        'weekday': WEEKDAY_NAMES[report_date.weekday()],
        'send_date': send_date.strftime('%Y-%m-%d'),
        'prev_date': prev_day.strftime('%Y-%m-%d'),
        'revenue': int(today['매출액'].sum()),
        'prev_revenue': int(yday['매출액'].sum()),
        'revenue_pct': _pct(today['매출액'].sum(), yday['매출액'].sum()),
        'qty': int(today['수량'].sum()),
        'prev_qty': int(yday['수량'].sum()),
        'qty_pct': _pct(today['수량'].sum(), yday['수량'].sum()),
        'prev_sameweekday_date': prev_sameweekday.strftime('%Y-%m-%d'),
        'prev_sameweekday_weekday': WEEKDAY_NAMES[prev_sameweekday.weekday()],
        'prev_sameweekday_revenue': int(pweek['매출액'].sum()),
        'prev_sameweekday_revenue_pct': _pct(today['매출액'].sum(), pweek['매출액'].sum()),
        'prev_sameweekday_qty': int(pweek['수량'].sum()),
        'prev_sameweekday_qty_pct': _pct(today['수량'].sum(), pweek['수량'].sum()),
    }
    today_model_qty = today.groupby('원품명').agg(수량=('수량', 'sum'), 매출액=('매출액', 'sum')).sort_values('수량', ascending=False)
    if len(today_model_qty):
        daily['best_model'] = {
            '원품명': today_model_qty.index[0],
            '수량': int(today_model_qty.iloc[0]['수량']),
            '매출액': float(today_model_qty.iloc[0]['매출액']),
        }
    else:
        daily['best_model'] = None

    # 2. 주간 매출 추이 (최근 3주, 전주 대비)
    monday = report_date - pd.Timedelta(days=report_date.weekday())
    weekly_trend = []
    prev_rev = None
    for k in (3, 2, 1, 0):
        wk_start = monday - pd.Timedelta(days=7 * k)
        wk_end = report_date if k == 0 else (wk_start + pd.Timedelta(days=6))
        wk_df = valid[(valid['주문일자'] >= wk_start) & (valid['주문일자'] <= wk_end)]
        wk_revenue = int(wk_df['매출액'].sum())
        entry = {
            'range': f"{wk_start.strftime('%m/%d')}~{wk_end.strftime('%m/%d')}",
            'revenue': wk_revenue,
            'revenue_pct': _pct(wk_revenue, prev_rev) if prev_rev is not None else None,
            'is_current': k == 0,
        }
        if k != 3:
            weekly_trend.append(entry)
        prev_rev = wk_revenue

    # 3. 월 누적매출
    month_start = report_date.replace(day=1)
    prev_month_end = month_start - pd.Timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    this_month_td = valid[(valid['주문일자'] >= month_start) & (valid['주문일자'] <= report_date)]
    prev_month_full = valid[(valid['주문일자'] >= prev_month_start) & (valid['주문일자'] <= prev_month_end)]
    target_key = month_start.strftime('%Y-%m')
    target_revenue = MONTHLY_TARGETS.get(target_key)

    # 예상 이번달 총매출: 이번달 자체의 "지금까지 일평균 매출 × 이번달 전체 일수"로 단순 추정.
    # (과거 달들의 진행률을 끌어와 보정하는 방식은 성수기/비수기 편차가 큰 업종 특성상 오히려 왜곡을 만들 수 있어 배제)
    days_elapsed = (report_date - month_start).days + 1
    next_month_start = (month_start + pd.Timedelta(days=32)).replace(day=1)
    days_in_month = (next_month_start - month_start).days
    daily_avg_this_month = this_month_td['매출액'].sum() / days_elapsed if days_elapsed > 0 else 0
    projected_revenue = int(daily_avg_this_month * days_in_month) if daily_avg_this_month > 0 else None

    monthly = {
        'range': f"{month_start.strftime('%m/%d')}~{report_date.strftime('%m/%d')}",
        'revenue': int(this_month_td['매출액'].sum()),
        'qty': int(this_month_td['수량'].sum()),
        'prev_month_full_range': f"{prev_month_start.strftime('%m/%d')}~{prev_month_end.strftime('%m/%d')}",
        'prev_month_full_revenue': int(prev_month_full['매출액'].sum()),
        'target_revenue': target_revenue,
        'target_pct': _pct(this_month_td['매출액'].sum(), target_revenue) if target_revenue else None,
        'projected_revenue': projected_revenue,
        'projection_days_elapsed': days_elapsed,
        'projection_days_in_month': days_in_month,
        'projected_target_pct': round(projected_revenue / target_revenue * 100, 1) if (projected_revenue and target_revenue) else None,
    }

    # ===== 매출수량 섹션 (관리모델 / 신규판매 / 급증·급감 우선순위) =====
    target_wd = report_date.weekday()
    wd_name = WEEKDAY_NAMES[target_wd]

    # 급증/급감 표용 추세 3종 (모두 연속 일자 기준, 동일요일 필터 없음)
    #  - 직전7일: 기준일 전 7일 + 오늘 (8개 포인트)
    #  - 1개월: 기준일 전 29일 + 오늘 (30개 포인트)
    #  - 3개월: 기준일 전 89일 + 오늘 (90개 포인트)
    def _continuous_pivot(days_back):
        data_min_d = valid['주문일자'].min()
        start = max(data_min_d, report_date - pd.Timedelta(days=days_back))
        date_idx = pd.date_range(start, report_date, freq='D')
        sub = valid[(valid['주문일자'] >= date_idx[0]) & (valid['주문일자'] <= date_idx[-1])]
        pv = sub.pivot_table(index='원품명', columns='주문일자', values='수량', aggfunc='sum', fill_value=0)
        pv = pv.reindex(columns=date_idx, fill_value=0)
        return pv, date_idx

    pivot_week, days_week = _continuous_pivot(7)
    pivot_month, days_month = _continuous_pivot(29)
    pivot_2mo, days_2mo = _continuous_pivot(59)
    pivot_3mo, days_3mo = _continuous_pivot(89)

    # 전월(캘린더 월) 모델별 일평균 - 3개월 추세 첫 숫자 색상 비교 기준용
    prev_cal_month_df = valid[(valid['주문일자'] >= prev_month_start) & (valid['주문일자'] <= prev_month_end)]
    prev_cal_month_days = (prev_month_end - prev_month_start).days + 1
    avg_prev_cal_month_all = prev_cal_month_df.groupby('원품명')['수량'].sum() / prev_cal_month_days

    # 기준선(baseline): 직전7일(오늘 제외) 연속 일평균
    prevweek_cols = days_week[:-1]  # 오늘을 뺀 7일
    baseline_all = pivot_week[prevweek_cols].mean(axis=1)
    n_occ = len(prevweek_cols)  # 표시용(7일)

    # 보조 기준선: 1개월(오늘 제외 29일) 연속 일평균. 급증/급감 판정에 OR조건으로 함께 사용.
    prevmonth_cols = days_month[:-1]  # 오늘을 뺀 29일
    baseline_month_all = pivot_month[prevmonth_cols].mean(axis=1)

    # 2개월(동일요일) 추세: 참고용 그래프. 최근 BASELINE_OCCURRENCES회(9회≈2개월) 동일 요일 + 오늘.
    # (기준선이 직전7일로 바뀌면서, 이 그래프는 더 이상 기준선과 같은 축이 아니라 순수 참고용 비교 자료다.)
    past_same_wd = valid[(valid['주문일자'] < report_date) & (valid['주문일자'].dt.weekday == target_wd)]
    same_wd_dates = sorted(past_same_wd['주문일자'].dt.date.unique(), reverse=True)[:BASELINE_OCCURRENCES]
    days_3mo_sameday = sorted(same_wd_dates) + [report_date.date()]
    sub_sameday = valid[valid['주문일자'].dt.date.isin(days_3mo_sameday)]
    pivot_3mo_sameday = sub_sameday.pivot_table(index='원품명', columns=sub_sameday['주문일자'].dt.date, values='수량', aggfunc='sum', fill_value=0)
    pivot_3mo_sameday = pivot_3mo_sameday.reindex(columns=days_3mo_sameday, fill_value=0)

    # 지난주(월~일) 캘린더 주 - 참고용 숫자 컬럼 하나(그래프 없음).
    # "주간 매출 추이" KPI의 지난주와 동일한 개념(월~일 캘린더 주)이며, 급증/급감 표의 "직전7일"(오늘 기준 거꾸로 7일)과는 다른 기간이다.
    this_week_monday = report_date - pd.Timedelta(days=report_date.weekday())
    last_week_start = this_week_monday - pd.Timedelta(days=7)
    last_week_end = this_week_monday - pd.Timedelta(days=1)
    days_last_week = pd.date_range(last_week_start, last_week_end, freq='D')
    sub_last_week = valid[(valid['주문일자'] >= days_last_week[0]) & (valid['주문일자'] <= days_last_week[-1])]
    pivot_last_week = sub_last_week.pivot_table(index='원품명', columns='주문일자', values='수량', aggfunc='sum', fill_value=0)
    pivot_last_week = pivot_last_week.reindex(columns=days_last_week, fill_value=0)

    today_qty_series = today.groupby('원품명')['수량'].sum() if len(today) else pd.Series(dtype=float)

    all_models = pivot_week.index.union(baseline_all.index).union(pd.Index(manage_models))
    today_qty_r = today_qty_series.reindex(all_models, fill_value=0)
    baseline_r = baseline_all.reindex(all_models, fill_value=0.0)
    pivot_week_r = pivot_week.reindex(index=all_models, fill_value=0)
    pivot_month_r = pivot_month.reindex(index=all_models, fill_value=0)
    pivot_2mo_r = pivot_2mo.reindex(index=all_models, fill_value=0)
    pivot_3mo_r = pivot_3mo.reindex(index=all_models, fill_value=0)
    pivot_3mo_sameday_r = pivot_3mo_sameday.reindex(index=all_models, fill_value=0)
    pivot_last_week_r = pivot_last_week.reindex(index=all_models, fill_value=0)
    diff = today_qty_r - baseline_r
    baseline_month_r = baseline_month_all.reindex(all_models, fill_value=0.0)
    diff_month = today_qty_r - baseline_month_r

    result = pd.DataFrame({
        'baseline': baseline_r.round(1), 'today_qty': today_qty_r, 'diff': diff.round(1),
        'baseline_month': baseline_month_r.round(1), 'diff_month': diff_month.round(1),
    })

    # 장기 하락세 모델: 오늘 하루의 이상 신호(급감모델)와는 별개로, 수개월째 서서히 판매가 줄어드는 상품을 감지.
    # 조건: (1) 3개월 일평균 최소 1개/일 이상 (노이즈 컷) (2) 3개월→2개월, 2개월→1개월 각 단계 15%+ 하락
    #       (3) 오늘 판매량이 1개월 평균 이하(아직 회복 안 된 상태)
    LONG_DECLINE_MIN_VOLUME = 1.0
    LONG_DECLINE_MIN_DROP_PCT = 0.15
    long_models_pool = pivot_3mo.index.union(pivot_2mo.index).union(pivot_month.index)
    avg_3mo_all = pivot_3mo.reindex(index=long_models_pool, fill_value=0).mean(axis=1)
    avg_2mo_all = pivot_2mo.reindex(index=long_models_pool, fill_value=0).mean(axis=1)
    pivot_month_long = pivot_month.reindex(index=long_models_pool, fill_value=0)
    avg_month_all = pivot_month_long.mean(axis=1)
    today_from_month = pivot_month_long.iloc[:, -1]

    long_decline_records = []
    for name in long_models_pool:
        a3v = float(avg_3mo_all.get(name, 0.0))
        a2v = float(avg_2mo_all.get(name, 0.0))
        a1v = float(avg_month_all.get(name, 0.0))
        tv = float(today_from_month.get(name, 0.0))
        if a3v < LONG_DECLINE_MIN_VOLUME or a2v <= 0:
            continue
        drop1 = (a3v - a2v) / a3v
        drop2 = (a2v - a1v) / a2v if a2v > 0 else 0
        if drop1 >= LONG_DECLINE_MIN_DROP_PCT and drop2 >= LONG_DECLINE_MIN_DROP_PCT and tv <= a1v:
            long_decline_records.append({
                '원품명': name,
                'avg_3mo': round(a3v, 2),
                'avg_2mo': round(a2v, 2),
                'avg_month': round(a1v, 2),
                'today_qty': int(round(tv)),
                'drop1_pct': round(drop1 * 100, 1),
                'drop2_pct': round(drop2 * 100, 1),
            })
    long_decline_models = sorted(long_decline_records, key=lambda r: r['avg_month'])

    # 신규 판매 모델 (기준일 판매 발생 모델 중 공백 기간으로 2단계 분류)
    #  - 60일 침묵 모델: 최근 60일간 판매 0건 (신상품일 수도, 오래 방치된 모델일 수도 있음)
    #  - 1개월 공백 재판매: 최근 30일간 판매 0건이나 31~60일 사이엔 판매 이력 有
    win30_start = report_date - pd.Timedelta(days=30)
    win60_start = report_date - pd.Timedelta(days=60)
    base_models = today[today['수량'] > 0]['원품명'].unique() if len(today) else []
    sold_30 = set(valid[(valid['주문일자'] >= win30_start) & (valid['주문일자'] < report_date)]['원품명'].unique())
    sold_60 = set(valid[(valid['주문일자'] >= win60_start) & (valid['주문일자'] < report_date)]['원품명'].unique())
    silent_60 = sorted(set(base_models) - sold_60)
    gap_30 = sorted((set(base_models) - sold_30) - set(silent_60))
    new_sale = {'silent_60': silent_60, 'gap_30': gap_30}

    # 급증/급감 우선순위: 현재는 직전7일 단독 기준으로 판정한다.
    # (OR조건: 직전7일 vs 1개월 중 더 심각한 쪽을 채택하는 방식도 코드로 남겨뒀으나,
    #  데이터가 더 쌓인 뒤(4개월 이상) 재검토하기로 하고 지금은 USE_OR_CONDITION=False로 비활성화)
    USE_OR_CONDITION = False
    existing = result[(result['baseline'] > 0) | (result['baseline_month'] > 0)].copy() if USE_OR_CONDITION else result[result['baseline'] > 0].copy()

    def _pick_tier_source(row, tier_func):
        t_week = tier_func(row['diff'])
        if not USE_OR_CONDITION:
            return pd.Series({'tier': t_week, 'source': '직전7일', 'used_baseline': row['baseline'], 'used_diff': row['diff']})
        t_month = tier_func(row['diff_month'])
        rank_week = t_week if t_week is not None else 99
        rank_month = t_month if t_month is not None else 99
        if rank_week <= rank_month:
            return pd.Series({'tier': t_week, 'source': '직전7일', 'used_baseline': row['baseline'], 'used_diff': row['diff']})
        return pd.Series({'tier': t_month, 'source': '1개월', 'used_baseline': row['baseline_month'], 'used_diff': row['diff_month']})

    spike_pick = existing.apply(lambda r: _pick_tier_source(r, _spike_tier), axis=1)
    drop_pick = existing.apply(lambda r: _pick_tier_source(r, _drop_tier), axis=1)
    existing['spike_tier'] = spike_pick['tier']
    existing['spike_source'] = spike_pick['source']
    existing['spike_baseline'] = spike_pick['used_baseline']
    existing['spike_diff'] = spike_pick['used_diff']
    existing['drop_tier'] = drop_pick['tier']
    existing['drop_source'] = drop_pick['source']
    existing['drop_baseline'] = drop_pick['used_baseline']
    existing['drop_diff'] = drop_pick['used_diff']

    spike_df = existing[existing['spike_tier'].isin([1, 2])].sort_values(['spike_tier', 'spike_diff'], ascending=[True, False]).head(SPIKE_MAX_DISPLAY)
    drop_df = existing[existing['drop_tier'].isin([1, 2])].sort_values(['drop_tier', 'drop_diff'], ascending=[True, True]).head(MAX_TIER_MODELS)

    # 급감 1~2순위가 하나도 없는 날: 3순위(-1~-1.9) 중 감소폭이 큰 순서로 최대 DROP_FALLBACK_COUNT개 대체 노출.
    # (완전히 급감 없음으로 비워두기보다, 상대적으로 가장 근접한 모델을 참고용으로 보여주기 위함)
    drops_is_fallback = False
    if len(drop_df) == 0:
        fallback_df = existing[existing['drop_tier'] == 3].sort_values('drop_diff', ascending=True).head(DROP_FALLBACK_COUNT)
        if len(fallback_df):
            drop_df = fallback_df
            drops_is_fallback = True

    def _tier_records(df_, tier_col, source_col, baseline_col, diff_col):
        records = []
        for name, r in df_.iterrows():
            trend_week = pivot_week_r.loc[name].astype(int).tolist() if name in pivot_week_r.index else [0] * len(days_week)
            trend_month = pivot_month_r.loc[name].astype(int).tolist() if name in pivot_month_r.index else [0] * len(days_month)
            trend_3mo = pivot_3mo_r.loc[name].astype(int).tolist() if name in pivot_3mo_r.index else [0] * len(days_3mo)
            trend_3mo_sameday = pivot_3mo_sameday_r.loc[name].astype(int).tolist() if name in pivot_3mo_sameday_r.index else [0] * len(days_3mo_sameday)
            trend_2mo = pivot_2mo_r.loc[name].astype(int).tolist() if name in pivot_2mo_r.index else [0] * len(days_2mo)
            last_week_vals = [int(v) for v in (pivot_last_week_r.loc[name].tolist() if name in pivot_last_week_r.index else [0] * len(days_last_week))]
            records.append({
                '원품명': name,
                'tier': int(r[tier_col]),
                'source': r[source_col],
                'baseline': float(r[baseline_col]),
                'today_qty': int(r['today_qty']),
                'diff': float(r[diff_col]),
                'trend_week': trend_week,
                'trend_month': trend_month,
                'trend_3mo': trend_3mo,
                'trend_3mo_sameday': trend_3mo_sameday,
                'trend_last_week': last_week_vals,
                'trend_2mo': trend_2mo,
                'avg_week': round(sum(trend_week[:-1]) / len(trend_week[:-1]), 1) if len(trend_week) > 1 else 0.0,
                'avg_month': round(sum(trend_month) / len(trend_month), 1) if trend_month else 0.0,
                'avg_2mo': round(sum(trend_2mo) / len(trend_2mo), 1) if trend_2mo else 0.0,
                'avg_3mo': round(sum(trend_3mo) / len(trend_3mo), 1) if trend_3mo else 0.0,
                'avg_3mo_sameday': round(sum(trend_3mo_sameday[:-1]) / len(trend_3mo_sameday[:-1]), 1) if len(trend_3mo_sameday) > 1 else 0.0,
                'avg_last_week': round(sum(last_week_vals) / len(last_week_vals), 1) if last_week_vals else 0.0,
                'avg_prev_cal_month': round(float(avg_prev_cal_month_all.get(name, 0.0)), 1),
            })
        # 3개월->2개월->1개월 일평균(모두 기준일 포함)이 한 방향으로 계속 움직이는지(지속 하락/상승) 보조 신호.
        # 판정(순위)에는 영향 없음 - "최근 몇 달간 흐름이 심상치 않을 수 있다"는 참고용 배지일 뿐.
        for rec in records:
            a3, a2, a1 = rec['avg_3mo'], rec['avg_2mo'], rec['avg_month']
            if a3 > a2 > a1:
                rec['trend_consistency'] = 'down'
            elif a3 < a2 < a1:
                rec['trend_consistency'] = 'up'
            else:
                rec['trend_consistency'] = None
        return records

    spikes = _tier_records(spike_df, 'spike_tier', 'spike_source', 'spike_baseline', 'spike_diff')
    drops = _tier_records(drop_df, 'drop_tier', 'drop_source', 'drop_baseline', 'drop_diff')

    # ★ 체크모델: 직접 입력한 모델만 (순위 조건과 무관하게 항상 고정 표시)
    check_models = []
    for name in manage_models[:5]:
        base_v = float(baseline_r.get(name, 0.0))
        today_v = int(today_qty_r.get(name, 0))
        diff_v = round(today_v - base_v, 1)
        trend_week_c = pivot_week_r.loc[name].astype(int).tolist() if name in pivot_week_r.index else [0] * len(days_week)
        trend_month_c = pivot_month_r.loc[name].astype(int).tolist() if name in pivot_month_r.index else [0] * len(days_month)
        trend_3mo_c = pivot_3mo_r.loc[name].astype(int).tolist() if name in pivot_3mo_r.index else [0] * len(days_3mo)
        trend_3mo_sameday_c = pivot_3mo_sameday_r.loc[name].astype(int).tolist() if name in pivot_3mo_sameday_r.index else [0] * len(days_3mo_sameday)
        avg_3mo_c = round(sum(trend_3mo_c) / len(trend_3mo_c), 1) if trend_3mo_c else 0.0
        avg_2mo_c = round(sum(trend_month_c) / len(trend_month_c), 1) if trend_month_c else 0.0  # placeholder, overwritten below
        trend_2mo_c = pivot_2mo_r.loc[name].astype(int).tolist() if name in pivot_2mo_r.index else [0] * len(days_2mo)
        avg_2mo_c = round(sum(trend_2mo_c) / len(trend_2mo_c), 1) if trend_2mo_c else 0.0
        avg_month_c = round(sum(trend_month_c) / len(trend_month_c), 1) if trend_month_c else 0.0
        tier_v = _spike_tier(diff_v) if diff_v > 0 else (_drop_tier(diff_v) if diff_v < 0 else None)
        check_models.append({
            '원품명': name,
            'baseline': round(base_v, 1),
            'today_qty': today_v,
            'diff': diff_v,
            'tier': tier_v,
            'tier_type': 'spike' if diff_v > 0 else ('drop' if diff_v < 0 else None),
            'trend_3mo': trend_3mo_c,
            'avg_3mo': avg_3mo_c,
            'avg_2mo': avg_2mo_c,
            'avg_month': avg_month_c,
            'avg_prev_cal_month': round(float(avg_prev_cal_month_all.get(name, 0.0)), 1),
        })

    # ★ 표시(신규 판매 모델 등 다른 섹션 강조)용 - 직접 입력한 관리모델 목록만 유지.
    manual_check_names = manage_models[:5]

    result_dict = {
        'daily': daily,
        'weekly_trend': weekly_trend,
        'monthly': monthly,
        'month_label': month_start.strftime('%Y년 %m월'),
        'baseline_wd_name': wd_name,
        'baseline_occurrences': n_occ,
        'manual_check_models': manual_check_names,  # ★ 표시(다른 섹션 강조)용 - 직접 입력한 모델만
        'check_models': check_models,
        'new_sale': new_sale,
        'spikes': spikes,
        'drops': drops,
        'drops_is_fallback': drops_is_fallback,
        'long_decline_models': long_decline_models,
    }
    return result_dict


def build_weekly(src=SRC, report_date=None, manage_models=None):
    """
    주간 대시보드용 (1차 버전 — 추후 다듬을 예정).
    급증/급감 판정 기준: "이번주(월~기준일) 일평균" vs "직전 4주(28일, 이번주 제외) 일평균"
    → 일일보고서의 "직전7일 대비" 개념을 주 단위로 확장한 것. 개수 차이(diff) 기준은 동일하게 재사용.
    """
    manage_models = manage_models or []
    df = load(src)
    valid = df[df['취소일자'].isna()].copy()

    if report_date is None:
        report_date = valid['주문일자'].max()
    else:
        report_date = pd.Timestamp(report_date)

    this_week_monday = report_date - pd.Timedelta(days=report_date.weekday())
    days_elapsed_this_week = (report_date - this_week_monday).days + 1

    prev_week_start = this_week_monday - pd.Timedelta(days=7)
    prev_week_end = this_week_monday - pd.Timedelta(days=1)

    this_week_df = valid[(valid['주문일자'] >= this_week_monday) & (valid['주문일자'] <= report_date)]
    prev_week_df = valid[(valid['주문일자'] >= prev_week_start) & (valid['주문일자'] <= prev_week_end)]

    weekly = {
        'range': f"{this_week_monday.strftime('%m/%d')}~{report_date.strftime('%m/%d')}",
        'days_elapsed': days_elapsed_this_week,
        'revenue': int(this_week_df['매출액'].sum()),
        'prev_week_revenue': int(prev_week_df['매출액'].sum()),
        'revenue_pct': _pct(this_week_df['매출액'].sum(), prev_week_df['매출액'].sum()),
        'qty': int(this_week_df['수량'].sum()),
        'prev_week_qty': int(prev_week_df['수량'].sum()),
        'qty_pct': _pct(this_week_df['수량'].sum(), prev_week_df['수량'].sum()),
    }
    week_model_qty = this_week_df.groupby('원품명').agg(수량=('수량', 'sum'), 매출액=('매출액', 'sum')).sort_values('수량', ascending=False)
    if len(week_model_qty):
        weekly['best_model'] = {
            '원품명': week_model_qty.index[0],
            '수량': int(week_model_qty.iloc[0]['수량']),
            '매출액': float(week_model_qty.iloc[0]['매출액']),
        }
    else:
        weekly['best_model'] = None

    # 기준선(baseline): 직전 4주(28일, 이번주 제외) 연속 일평균
    baseline_start = this_week_monday - pd.Timedelta(days=28)
    baseline_end = this_week_monday - pd.Timedelta(days=1)
    baseline_df = valid[(valid['주문일자'] >= baseline_start) & (valid['주문일자'] <= baseline_end)]
    baseline_all = baseline_df.groupby('원품명')['수량'].sum() / 28

    this_week_avg_all = this_week_df.groupby('원품명')['수량'].sum() / days_elapsed_this_week if days_elapsed_this_week else pd.Series(dtype=float)

    all_models = baseline_all.index.union(this_week_avg_all.index).union(pd.Index(manage_models))
    baseline_r = baseline_all.reindex(all_models, fill_value=0.0).round(1)
    this_week_r = this_week_avg_all.reindex(all_models, fill_value=0.0).round(1)
    diff = (this_week_r - baseline_r).round(1)

    result = pd.DataFrame({'baseline': baseline_r, 'this_week_avg': this_week_r, 'diff': diff})
    existing = result[result['baseline'] > 0].copy()
    existing['spike_tier'] = existing['diff'].apply(_spike_tier)
    existing['drop_tier'] = existing['diff'].apply(_drop_tier)

    spike_df = existing[existing['spike_tier'].isin([1, 2])].sort_values(['spike_tier', 'diff'], ascending=[True, False]).head(SPIKE_MAX_DISPLAY)
    drop_df = existing[existing['drop_tier'].isin([1, 2])].sort_values(['drop_tier', 'diff'], ascending=[True, True]).head(MAX_TIER_MODELS)

    drops_is_fallback = False
    if len(drop_df) == 0:
        fallback_df = existing[existing['drop_tier'] == 3].sort_values('diff', ascending=True).head(DROP_FALLBACK_COUNT)
        if len(fallback_df):
            drop_df = fallback_df
            drops_is_fallback = True

    def _simple_records(df_, tier_col):
        records = []
        for name, r in df_.iterrows():
            records.append({
                '원품명': name,
                'tier': int(r[tier_col]),
                'baseline': float(r['baseline']),
                'this_week_avg': float(r['this_week_avg']),
                'diff': float(r['diff']),
            })
        return records

    spikes = _simple_records(spike_df, 'spike_tier')
    drops = _simple_records(drop_df, 'drop_tier')

    return {
        'weekly': weekly,
        'spikes': spikes,
        'drops': drops,
        'drops_is_fallback': drops_is_fallback,
        'baseline_range': f"{baseline_start.strftime('%m/%d')}~{baseline_end.strftime('%m/%d')}",
    }


if __name__ == '__main__':
    # 사용 예시: 매번 채팅에서 지정받은 관리모델 리스트를 manage_models로 전달
    data = build(manage_models=['FRE-465RF', 'FC-49MSW'])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    with open('report_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
