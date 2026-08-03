import pandas as pd
import json

SRC = '/mnt/user-data/uploads/1차가공.csv'

# 월별 목표매출 (YYYY-MM 기준). 새로운 달 목표가 정해지면 여기에 추가.
MONTHLY_TARGETS = {
    '2026-08': 1877763991,
}

# 네-쿠입고: 고객 판매가 아닌 물류센터 입고(재고 이동) 채널. 대량 입고 건이 하루에 몰려 찍히기 때문에
# 수량 기반 지표(관리모델/급증/급감/베스트모델)에서는 반드시 제외해야 정확한 판매 추이를 볼 수 있음.
STOCK_IN_CHANNELS = {'네이버하우저', '쿠팡로켓그로스'}

# 취소 다발 모델 조회 기간(일). 짧을수록 최신 이슈에 민감하지만 건수가 적어 노이즈가 커지고,
# 길수록 안정적이지만 반응이 느려짐. 7일을 기본값으로 사용(주간 패턴까지 확인 가능한 최소 단위).
CANCEL_LOOKBACK_DAYS = 7

def load(src):
    df = pd.read_csv(src, encoding='utf-8-sig')
    df = df[df['쇼핑몰'].notna()].copy()
    df['수량'] = df['수량'].astype(int)
    df['판매단가'] = df['판매단가'].astype(str).str.replace(',', '').astype(float)
    df['주문일자'] = pd.to_datetime(df['주문일자'])
    df['취소일자'] = pd.to_datetime(df['취소일자'], errors='coerce')
    # 검증 결과: 판매단가 컬럼은 채널/수량 무관하게 "해당 라인의 총 매출액"으로 이미 기록되어 있음
    # (수량>=2 라인 455건 전수 확인: 판매단가를 그대로 쓸 때만 기준단가와 일치, 수량과 곱하면 수배~수십배 과대계상됨)
    # → 매출액 = 판매단가 그대로 사용 (수량을 곱하지 않음)
    df['매출액'] = df['판매단가']
    return df

def build(src=SRC, report_date=None, send_date=None):
    df = load(src)
    valid = df[df['취소일자'].isna()].copy()      # 순매출(취소 제외) 계산용
    cancel = df[(df['취소일자'].notna()) & (df['수량'] > 0)].copy()  # 취소 원주문

    if report_date is None:
        report_date = valid['주문일자'].max()
    else:
        report_date = pd.Timestamp(report_date)
    prev_day = report_date - pd.Timedelta(days=1)

    # 보고일자(오른쪽 상단 배지): 실제 보고서를 발송/열람하는 날짜. 기본값은 데이터 기준일(report_date)의 다음 날.
    if send_date is None:
        send_date = report_date + pd.Timedelta(days=1)
    else:
        send_date = pd.Timestamp(send_date)

    today = valid[valid['주문일자'] == report_date]
    yday = valid[valid['주문일자'] == prev_day]
    today_qty_src = today[~today['쇼핑몰'].isin(STOCK_IN_CHANNELS)]  # 수량 기반 지표용(입고 채널 제외)

    def pct(cur, prev):
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 1)

    # 1. 일간 매출
    daily = {
        'date': report_date.strftime('%Y-%m-%d'),
        'weekday': ['월','화','수','목','금','토','일'][report_date.weekday()],
        'send_date': send_date.strftime('%Y-%m-%d'),
        'send_weekday': ['월','화','수','목','금','토','일'][send_date.weekday()],
        'prev_date': prev_day.strftime('%Y-%m-%d'),
        'revenue': int(today['매출액'].sum()),
        'prev_revenue': int(yday['매출액'].sum()),
        'revenue_pct': pct(today['매출액'].sum(), yday['매출액'].sum()),
        'qty': int(today['수량'].sum()),
        'prev_qty': int(yday['수량'].sum()),
        'qty_pct': pct(today['수량'].sum(), yday['수량'].sum()),
        'orders': int(len(today)),
        'prev_orders': int(len(yday)),
    }

    # 1-1. 당일 베스트모델 (판매수량 기준 1위, 입고 채널 제외)
    today_model_qty = today_qty_src.groupby('원품명').agg(수량=('수량', 'sum'), 매출액=('매출액', 'sum')).sort_values('수량', ascending=False)
    if len(today_model_qty):
        best_model = {
            '원품명': today_model_qty.index[0],
            '수량': int(today_model_qty.iloc[0]['수량']),
            '매출액': float(today_model_qty.iloc[0]['매출액']),
        }
    else:
        best_model = None
    daily['best_model'] = best_model

    # 2. 주간 매출 (월~기준일 vs 전주 동기간)
    monday = report_date - pd.Timedelta(days=report_date.weekday())
    prev_monday = monday - pd.Timedelta(days=7)
    prev_same = report_date - pd.Timedelta(days=7)
    this_week = valid[(valid['주문일자'] >= monday) & (valid['주문일자'] <= report_date)]
    prev_week = valid[(valid['주문일자'] >= prev_monday) & (valid['주문일자'] <= prev_same)]
    weekly = {
        'range': f"{monday.strftime('%m/%d')}~{report_date.strftime('%m/%d')}",
        'prev_range': f"{prev_monday.strftime('%m/%d')}~{prev_same.strftime('%m/%d')}",
        'revenue': int(this_week['매출액'].sum()),
        'prev_revenue': int(prev_week['매출액'].sum()),
        'revenue_pct': pct(this_week['매출액'].sum(), prev_week['매출액'].sum()),
        'qty': int(this_week['수량'].sum()),
        'prev_qty': int(prev_week['수량'].sum()),
        'qty_pct': pct(this_week['수량'].sum(), prev_week['수량'].sum()),
    }

    # 2-0. 주간 매출 추이 (최근 3주, 전주 대비 증감률 포함)
    # 가장 최근 주(이번 주)는 월요일~기준일까지의 부분 주간, 이전 2개 주는 월~일 풀 주간
    # 첫 표시주(가장 과거)의 증감률 계산을 위해 그 전주(k=3)도 함께 계산하되 표에는 표시하지 않음
    weekly_trend = []
    prev_rev_for_trend = None
    for k in (3, 2, 1, 0):
        wk_start = monday - pd.Timedelta(days=7 * k)
        wk_end = report_date if k == 0 else (wk_start + pd.Timedelta(days=6))
        wk_df = valid[(valid['주문일자'] >= wk_start) & (valid['주문일자'] <= wk_end)]
        wk_revenue = int(wk_df['매출액'].sum())
        entry = {
            'range': f"{wk_start.strftime('%m/%d')}~{wk_end.strftime('%m/%d')}",
            'revenue': wk_revenue,
            'qty': int(wk_df['수량'].sum()),
            'revenue_pct': pct(wk_revenue, prev_rev_for_trend) if prev_rev_for_trend is not None else None,
            'is_current': k == 0,
        }
        if k != 3:  # k=3주는 비교 기준값으로만 사용, 표에는 표시하지 않음
            weekly_trend.append(entry)
        prev_rev_for_trend = wk_revenue

    # 2-1. 월간 매출 (이번달 1일~기준일 vs 전월 동기간)
    month_start_tmp = report_date.replace(day=1)
    prev_month_end = month_start_tmp - pd.Timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    prev_month_same_day = min(report_date.day, prev_month_end.day)
    prev_month_upto = prev_month_start.replace(day=prev_month_same_day)
    this_month_td = valid[(valid['주문일자'] >= month_start_tmp) & (valid['주문일자'] <= report_date)]
    prev_month_td = valid[(valid['주문일자'] >= prev_month_start) & (valid['주문일자'] <= prev_month_upto)]
    prev_month_full = valid[(valid['주문일자'] >= prev_month_start) & (valid['주문일자'] <= prev_month_end)]  # 전월 전체(1일~말일) 누적
    prev_month_full_revenue = prev_month_full['매출액'].sum()
    monthly = {
        'range': f"{month_start_tmp.strftime('%m/%d')}~{report_date.strftime('%m/%d')}",
        'prev_range': f"{prev_month_start.strftime('%m/%d')}~{prev_month_upto.strftime('%m/%d')}",
        'revenue': int(this_month_td['매출액'].sum()),
        'prev_revenue': int(prev_month_td['매출액'].sum()),
        'revenue_pct': pct(this_month_td['매출액'].sum(), prev_month_td['매출액'].sum()),
        'qty': int(this_month_td['수량'].sum()),
        'prev_qty': int(prev_month_td['수량'].sum()),
        'qty_pct': pct(this_month_td['수량'].sum(), prev_month_td['수량'].sum()),
        # 전월 전체(1일~말일) 누적 총 매출/수량
        'prev_month_full_range': f"{prev_month_start.strftime('%m/%d')}~{prev_month_end.strftime('%m/%d')}",
        'prev_month_full_revenue': int(prev_month_full_revenue),
        'prev_month_full_qty': int(prev_month_full['수량'].sum()),
        # 당월 일단위 누적 매출이 전월 총매출 대비 몇 %까지 채워졌는지(진행률)
        'pace_pct': pct(this_month_td['매출액'].sum(), prev_month_full_revenue),
    }
    # 목표매출 대비 진행률 (설정된 달만)
    target_key = month_start_tmp.strftime('%Y-%m')
    target_revenue = MONTHLY_TARGETS.get(target_key)
    monthly['target_revenue'] = target_revenue
    monthly['target_pct'] = pct(this_month_td['매출액'].sum(), target_revenue) if target_revenue else None

    # 4. 직전 7일 평균 계산 (관리모델/특이매출수량 공용, 입고 채널 제외 - 대량 입고 건이 평균을 왜곡시킴)
    week_before = valid[(valid['주문일자'] >= report_date - pd.Timedelta(days=7)) & (valid['주문일자'] < report_date)]
    week_before = week_before[~week_before['쇼핑몰'].isin(STOCK_IN_CHANNELS)]
    avg7 = week_before.groupby('원품명')['수량'].sum() / 7.0
    today_qty_all = today_qty_src.groupby('원품명')['수량'].sum()

    # 3. 관리모델 TOP5 (기준일 판매수량 상위 5개, 직전 7일 평균 대비 표기)
    top_models = today_qty_all.sort_values(ascending=False).head(5)
    manage_models = []
    for name, qty in top_models.items():
        a7 = avg7.get(name, 0.0)
        ratio = (qty / a7) if a7 > 0 else None
        manage_models.append({
            '원품명': name,
            'today_qty': int(qty),
            'avg7': round(a7, 1),
            'ratio': round(ratio, 1) if ratio is not None else None,
        })

    # 4-1. 특이 매출수량 - 급증 TOP8 (직전 7일 평균보다 +1개 이상이면 포착 · 매우 민감한 기준)
    cmp_df = pd.DataFrame({'today_qty': today_qty_all, 'avg7': avg7}).fillna(0)

    surge_df = cmp_df.copy()
    surge_df['diff'] = surge_df['today_qty'] - surge_df['avg7']
    surge_df['ratio'] = surge_df.apply(lambda r: (r['today_qty']/r['avg7']) if r['avg7']>0 else 999, axis=1)
    surge_df = surge_df[surge_df['diff'] >= 1]
    surge_df = surge_df.sort_values(['diff', 'today_qty'], ascending=False).head(8).reset_index()
    spikes = []
    for _, r in surge_df.iterrows():
        spikes.append({
            '원품명': r['원품명'],
            'today_qty': int(r['today_qty']),
            'avg7': round(r['avg7'], 1),
            'ratio': round(r['ratio'], 1) if r['avg7'] > 0 else None,
        })

    # 급감: 직전 7일 평균이 1개 이상인 모델 중, 오늘 수량이 평균보다 1개 이상 감소 (급증과 대칭 기준)
    drop_df = cmp_df[cmp_df['avg7'] >= 1].copy()
    drop_df['diff'] = drop_df['today_qty'] - drop_df['avg7']
    drop_df['ratio'] = drop_df['today_qty'] / drop_df['avg7']
    drop_df = drop_df[drop_df['diff'] <= -1]
    drop_df = drop_df.sort_values(['ratio', 'avg7'], ascending=[True, False]).head(8).reset_index()
    drops = []
    for _, r in drop_df.iterrows():
        drops.append({
            '원품명': r['원품명'],
            'today_qty': int(r['today_qty']),
            'avg7': round(r['avg7'], 1),
            'ratio': round(r['ratio'], 1),
        })

    # 5. 누적 판매현황 - 주간 TOP5, 월간 TOP5 (매출액 기준)
    week_top = (this_week.groupby('원품명')['매출액'].sum().sort_values(ascending=False).head(5).reset_index()).to_dict('records')
    month_start = report_date.replace(day=1)
    this_month = valid[(valid['주문일자'] >= month_start) & (valid['주문일자'] <= report_date)]
    month_top = (this_month.groupby('원품명')['매출액'].sum().sort_values(ascending=False).head(5).reset_index()).to_dict('records')

    # 6. 채널별 실적 (고정 5개 그룹, 지정된 순서, 전일대비)
    CHANNEL_GROUP_MAP = {
        '스마트스토어': '스마트스토어',
        '쿠팡': '쿠팡',
        'Cafe24(신) 유튜브쇼핑': '자사몰',
        '11번가': '기타채널',
        'ESM지마켓': '기타채널',
        'ESM옥션': '기타채널',
        '오늘의집': '기타채널',
        '롯데온': '기타채널',
        '토스쇼핑': '기타채널',
        '배민상회': '기타채널',
        '네이버하우저': '네-쿠입고',
        '쿠팡로켓그로스': '네-쿠입고',
    }
    GROUP_ORDER = ['스마트스토어', '쿠팡', '자사몰', '기타채널', '네-쿠입고']

    def bucket(ch):
        return CHANNEL_GROUP_MAP.get(ch, '기타채널')  # 매핑에 없는 신규 채널은 기타채널로 편입

    today_b = today.copy()
    today_b['채널그룹'] = today_b['쇼핑몰'].apply(bucket)
    yday_b = yday.copy()
    yday_b['채널그룹'] = yday_b['쇼핑몰'].apply(bucket)

    ch_today = today_b.groupby('채널그룹')['매출액'].sum()
    ch_yday = yday_b.groupby('채널그룹')['매출액'].sum()
    channels = []
    for ch in GROUP_ORDER:
        rev = ch_today.get(ch, 0)
        prev = ch_yday.get(ch, 0)
        channels.append({'채널': ch, '매출액': int(rev), '전일매출': int(prev), 'pct': pct(rev, prev)})

    # 7. 취소 다발 모델 TOP3 (직전 N일, 취소일자 기준 - 월 경계 무관하게 최근 이슈 파악용)
    cancel_from = report_date - pd.Timedelta(days=CANCEL_LOOKBACK_DAYS - 1)
    cancel_recent = cancel[(cancel['취소일자'] >= cancel_from) & (cancel['취소일자'] <= report_date)]
    cancel_top = (cancel_recent.groupby('원품명').agg(취소수량=('수량','sum'), 취소금액=('매출액','sum'))
                  .sort_values('취소수량', ascending=False).head(3).reset_index()).to_dict('records')
    cancel_range_label = f"직전 {CANCEL_LOOKBACK_DAYS}일 ({cancel_from.strftime('%m/%d')}~{report_date.strftime('%m/%d')})"

    # 7-1. 요일별 평균 매출 (직전 3주 vs 최근실적, 자기참조 방지)
    # 각 요일마다 "가장 최근에 그 요일이었던 날"을 최근실적으로 잡고,
    # 평균매출(baseline)은 그 최근실적 날짜를 제외한 "그 이전 3주 동일요일" 매출 평균으로 계산한다.
    # (기준일 요일도 포함 전 요일이 동일 규칙: 최근값 자신은 평균에 포함시키지 않음)
    wd_names = ['월','화','수','목','금','토','일']

    weekday_summary = []
    for i, name in enumerate(wd_names):
        days_back = (report_date.weekday() - i) % 7  # 가장 최근 해당 요일까지 며칠 전인지 (0~6)
        recent_date = report_date - pd.Timedelta(days=days_back)
        recent_rev = int(valid[valid['주문일자'] == recent_date]['매출액'].sum())

        baseline_dates = [recent_date - pd.Timedelta(days=7 * k) for k in (1, 2, 3)]
        baseline_revs = [valid[valid['주문일자'] == bd]['매출액'].sum() for bd in baseline_dates]
        avg_rev = sum(baseline_revs) / 3.0

        weekday_summary.append({
            '요일': name,
            '평균매출': int(round(avg_rev)),
            '최근날짜': recent_date.strftime('%m/%d'),
            '최근매출': recent_rev,
            '최근pct': pct(recent_rev, avg_rev),
            'is_today': (i == report_date.weekday()),
        })

    # 데이터 완결성 체크 (직전 7일 평균 채널수 대비 오늘 채널수가 크게 적으면 경고)
    last7 = valid[(valid['주문일자'] >= report_date - pd.Timedelta(days=7)) & (valid['주문일자'] < report_date)]
    avg_channels = last7.groupby(last7['주문일자'].dt.date)['쇼핑몰'].nunique().mean()
    today_channels = today['쇼핑몰'].nunique()
    incomplete_warning = today_channels < avg_channels * 0.6

    # 8. 한줄 요약 (경고 문구를 대체하는 자동 인사이트 한 줄)
    def dir_word(p):
        if p is None:
            return '변동 없음'
        return f"{'+' if p > 0 else ''}{p}%"

    if incomplete_warning:
        summary = (f"{daily['date']} 데이터가 평소보다 적어(채널 {today_channels}개 / 최근 7일 평균 {round(avg_channels,1)}개) "
                    f"마감 전 데이터일 수 있습니다.")
    else:
        parts = [f"{daily['date']} 매출은 전일 대비 {dir_word(daily['revenue_pct'])}, "
                 f"주간 누적은 전주 대비 {dir_word(weekly['revenue_pct'])}입니다."]
        if spikes:
            top_spike = spikes[0]
            if top_spike['ratio'] is not None:
                parts.append(f"{top_spike['원품명']}이(가) 평소보다 {top_spike['ratio']}배 급증했습니다.")
            else:
                parts.append(f"{top_spike['원품명']}이(가) 신규로 급증 판매되었습니다.")
        elif drops:
            top_drop = drops[0]
            parts.append(f"{top_drop['원품명']} 판매가 평소보다 크게 줄었습니다.")
        elif best_model:
            parts.append(f"베스트모델은 {best_model['원품명']}입니다.")
        summary = ' '.join(parts)

    result = {
        'incomplete_warning': bool(incomplete_warning),
        'today_channels': int(today_channels),
        'avg_channels': round(avg_channels, 1),
        'summary': summary,
        'daily': daily,

        'weekly': weekly,
        'weekly_trend': weekly_trend,
        'monthly': monthly,
        'manage_models': manage_models,
        'spikes': spikes,
        'drops': drops,
        'week_top': week_top,
        'month_top': month_top,
        'channels': channels,
        'cancel_top': cancel_top,
        'cancel_range_label': cancel_range_label,
        'weekday_summary': weekday_summary,
        'month_label': month_start.strftime('%Y년 %m월'),
    }
    return result

if __name__ == '__main__':
    data = build()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    with open('report_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
