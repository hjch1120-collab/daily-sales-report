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
    monthly = {
        'range': f"{month_start.strftime('%m/%d')}~{report_date.strftime('%m/%d')}",
        'revenue': int(this_month_td['매출액'].sum()),
        'qty': int(this_month_td['수량'].sum()),
        'prev_month_full_range': f"{prev_month_start.strftime('%m/%d')}~{prev_month_end.strftime('%m/%d')}",
        'prev_month_full_revenue': int(prev_month_full['매출액'].sum()),
        'target_revenue': target_revenue,
        'target_pct': _pct(this_month_td['매출액'].sum(), target_revenue) if target_revenue else None,
    }

    # ===== 매출수량 섹션 (관리모델 / 신규판매 / 급증·급감 우선순위) =====
    target_wd = report_date.weekday()
    wd_name = WEEKDAY_NAMES[target_wd]

    # 기준선(baseline): 최근 BASELINE_OCCURRENCES회 동일 요일 rolling 평균
    past_same_wd = valid[(valid['주문일자'] < report_date) & (valid['주문일자'].dt.weekday == target_wd)]
    same_wd_dates = sorted(past_same_wd['주문일자'].dt.date.unique(), reverse=True)[:BASELINE_OCCURRENCES]
    n_occ = len(same_wd_dates)
    baseline_window = valid[valid['주문일자'].dt.date.isin(same_wd_dates)]
    baseline_all = (baseline_window.groupby('원품명')['수량'].sum() / n_occ) if n_occ else pd.Series(dtype=float)

    # 8일 추세 (지난주 월~일 + 오늘) - 급증/급감 표용 (그래프1: 기준일 전 7일 + 오늘)
    days8 = pd.date_range(report_date - pd.Timedelta(days=7), report_date, freq='D')
    sub8 = valid[(valid['주문일자'] >= days8[0]) & (valid['주문일자'] <= days8[-1])]
    pivot8 = sub8.pivot_table(index='원품명', columns='주문일자', values='수량', aggfunc='sum', fill_value=0)
    pivot8 = pivot8.reindex(columns=days8, fill_value=0)
    today_qty8 = pivot8.iloc[:, 7] if pivot8.shape[1] == 8 else pd.Series(dtype=float)

    # 90일(3개월) 기준 동일요일 추이 - 급증/급감 표용 (그래프2: 참고용 장기 추세. 판단 기준인 baseline/평균은 여전히 2개월 9회 그대로)
    past_same_wd_90 = valid[(valid['주문일자'] < report_date) & (valid['주문일자'] >= report_date - pd.Timedelta(days=90)) & (valid['주문일자'].dt.weekday == target_wd)]
    long_trend_dates = sorted(past_same_wd_90['주문일자'].dt.date.unique()) + [report_date.date()]
    n_long_pts = len(long_trend_dates)
    sub_long = valid[valid['주문일자'].dt.date.isin(long_trend_dates)]
    pivot_long = sub_long.pivot_table(index='원품명', columns=sub_long['주문일자'].dt.date, values='수량', aggfunc='sum', fill_value=0)
    pivot_long = pivot_long.reindex(columns=long_trend_dates, fill_value=0)

    all_models = pivot8.index.union(baseline_all.index).union(pd.Index(manage_models))
    today_qty_r = today_qty8.reindex(all_models, fill_value=0)
    baseline_r = baseline_all.reindex(all_models, fill_value=0.0)
    pivot8_r = pivot8.reindex(all_models, fill_value=0)
    pivot_long_r = pivot_long.reindex(all_models, fill_value=0)
    diff = today_qty_r - baseline_r

    result = pd.DataFrame({'baseline': baseline_r.round(1), 'today_qty': today_qty_r, 'diff': diff.round(1)})
    for i in range(8):
        result[f'd{i}'] = pivot8_r.iloc[:, i] if pivot8_r.shape[1] == 8 else 0
    for i in range(n_long_pts):
        result[f'lg{i}'] = pivot_long_r.iloc[:, i] if pivot_long_r.shape[1] == n_long_pts else 0

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

    # 급증/급감 우선순위 (baseline > 0인 기존 모델 대상)
    existing = result[result['baseline'] > 0].copy()
    existing['spike_tier'] = existing['diff'].apply(_spike_tier)
    existing['drop_tier'] = existing['diff'].apply(_drop_tier)

    spike_df = existing[existing['spike_tier'].isin([1, 2])].sort_values(['spike_tier', 'diff'], ascending=[True, False]).head(SPIKE_MAX_DISPLAY)
    drop_df = existing[existing['drop_tier'].isin([1, 2])].sort_values(['drop_tier', 'diff'], ascending=[True, True]).head(MAX_TIER_MODELS)

    def _tier_records(df_, tier_col):
        records = []
        for name, r in df_.iterrows():
            records.append({
                '원품명': name,
                'tier': int(r[tier_col]),
                'baseline': float(r['baseline']),
                'today_qty': int(r['today_qty']),
                'diff': float(r['diff']),
                'trend8': [int(r[f'd{i}']) for i in range(8)],
                'trend_long': [int(r[f'lg{i}']) for i in range(n_long_pts)],
            })
        return records

    spikes = _tier_records(spike_df, 'spike_tier')
    drops = _tier_records(drop_df, 'drop_tier')

    # 체크모델: 1순위 = 급감모델 1순위 자동 반영(최대 5개), 2순위 = 직접 입력한 관리모델(최대 5개, 중복 제외).
    # 표시되는 "순위"는 소속 그룹이 아니라 실제 급증/급감 기준(diff)으로 계산한 순위. 기준 미달이면 빈칸.
    # 추세는 90일(3개월) 일단위 - 급증/급감 표의 장기추세(90일) 길이에 맞춤. baseline/평균 계산 기준(2개월 9회)은 변경 없음.
    auto_check_names = list(drop_df[drop_df['drop_tier'] == 1].index)[:5]
    manual_check_names = [m for m in manage_models if m not in auto_check_names][:5]
    check_model_specs = [(n, 1) for n in auto_check_names] + [(n, 2) for n in manual_check_names]
    check_model_names = [n for n, _ in check_model_specs]

    data_min = valid['주문일자'].min()
    window_start90 = max(data_min, report_date - pd.Timedelta(days=89))
    days90 = pd.date_range(window_start90, report_date, freq='D')
    sub90 = valid[(valid['주문일자'] >= days90[0]) & (valid['주문일자'] <= days90[-1])]
    pivot90 = sub90.pivot_table(index='원품명', columns='주문일자', values='수량', aggfunc='sum', fill_value=0)
    pivot90 = pivot90.reindex(index=check_model_names, columns=days90, fill_value=0)

    check_models = []
    for name, _group in check_model_specs:
        base_v = float(baseline_all.get(name, 0.0))
        today_v = int(pivot90.loc[name].iloc[-1]) if name in pivot90.index else 0
        raw_diff = today_v - base_v
        diff_v = round(raw_diff, 1)
        diff_pct = round((raw_diff / base_v * 100), 1) if base_v > 0 else None
        if diff_v > 0:
            rank_tier, rank_type = _spike_tier(diff_v), 'spike'
        elif diff_v < 0:
            rank_tier, rank_type = _drop_tier(diff_v), 'drop'
        else:
            rank_tier, rank_type = None, None
        if rank_tier is None:
            rank_type = None
        check_models.append({
            '원품명': name,
            'rank_tier': rank_tier,
            'rank_type': rank_type,
            'baseline': round(base_v, 1),
            'today_qty': today_v,
            'diff': diff_v,
            'diff_pct': diff_pct,
            'trend60': pivot90.loc[name].astype(int).tolist() if name in pivot90.index else [0] * len(days90),
        })

    result_dict = {
        'daily': daily,
        'weekly_trend': weekly_trend,
        'monthly': monthly,
        'month_label': month_start.strftime('%Y년 %m월'),
        'baseline_wd_name': wd_name,
        'baseline_occurrences': n_occ,
        'long_trend_occurrences': n_long_pts - 1,
        'check_models': check_models,
        'manual_check_models': manual_check_names,  # ★ 표시(다른 섹션 강조)용 - 직접 입력한 모델만
        'new_sale': new_sale,
        'spikes': spikes,
        'drops': drops,
    }
    return result_dict


if __name__ == '__main__':
    # 사용 예시: 매번 채팅에서 지정받은 관리모델 리스트를 manage_models로 전달
    data = build(manage_models=['FRE-465RF', 'FC-49MSW'])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    with open('report_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
