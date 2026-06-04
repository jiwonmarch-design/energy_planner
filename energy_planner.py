# =====================================
# 🎉 energy planner project 🎉
# =====================================


#%% 🔥라이브러리
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import lightgbm as lgb
import xgboost as xgb

import holidays
import optuna
import xgboost

from lightgbm import LGBMRegressor
from xgboost import XGBRegressor, callback
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    mean_absolute_percentage_error
)

from sklearn.metrics import (
    mean_absolute_error
)

# =====================================
# Data Preprocessing (전처리)
# =====================================

#%% 🔥15분 단위 전력 데이터 CSV 파일 불러오기
df_p15d = pd.read_csv('power_15m_data_202605271649.csv')

# meter_id별 데이터 개수 확인
print(df_p15d['meter_id'].value_counts())


#%% 🔥meter_id = 1 이면서 channel_no = 1 인 데이터만 남기기
df_p15d = df_p15d[
    (df_p15d['meter_id'] == 1)
    &
    (df_p15d['channel_no'] == 1)
]

# 확인
print(df_p15d[['meter_id', 'channel_no']].value_counts())


#%% 🔥결측치 확인
print(df_p15d.isnull().sum())


#%% 🔥demand_kw, bill_15m 컬럼 삭제
df_p15d = df_p15d.drop(
    ['demand_kw', 'bill_15m'],
    axis=1,
    errors='ignore'
)


#%% ♻️데이터프레임의 첫 번째 행 출력 (0번째 행)
#print(df_p15d.iloc[0])

#%% ♻️중복된 첫번째 행 삭제
#df_p15d = df_p15d.iloc[1:].reset_index(drop=True)

# ♻️수정>>> 초, 밀리초 제거 > 데이터를 날짜와 시간 순서로 정렬 > 완전히 날짜와 시간 같은 중복된 데이터 확인 > 중복된 데이터 삭제 


#%% 🔥ts 컬럼 초 + 밀리초 제거 → 시:분까지만 남기기

# ts 컬럼 datetime 변환
df_p15d['ts'] = pd.to_datetime(df_p15d['ts'])

# 초 + 밀리초 제거
df_p15d['ts'] = df_p15d['ts'].dt.floor('min')

# ts 기준 시간순 정렬
df_p15d = df_p15d.sort_values('ts')

# ts 중복 제거 (음수 사용량 발생 원인 제거)
df_p15d = (
    df_p15d
    .drop_duplicates(
        subset='ts',
        keep='last'
    )
)

# 인덱스 초기화
df_p15d = df_p15d.reset_index(drop=True)

# 확인
print(df_p15d['ts'].head(10))


# ♻️수정 >>> ts에서 빈 날짜, 빈 시간대 확인 


#%% ✨kwh_15m 생성
# 누적 전력량(kwh_sum) → 15분 사용량

# 시간 간격(분) 계산
df_p15d['time_diff'] = (
    df_p15d['ts']
    .diff()
    .dt.total_seconds()
    / 60
)

# 15분 간격일 때만 사용량 계산
df_p15d['kwh_15m'] = np.where(
    df_p15d['time_diff'] == 15,
    df_p15d['kwh_sum'].diff(),
    np.nan
)

# 계산 불가능 구간 제거
df_p15d = (
    df_p15d
    .dropna(subset=['kwh_15m'])
    .reset_index(drop=True)
)

# 확인
print(
    df_p15d[
        ['ts', 'time_diff', 'kwh_sum', 'kwh_15m']
    ].head()
)



#%% 🔥kwh_15m 기초통계량 확인

print(df_p15d['kwh_15m'].describe())



#%% 🔥kwh_sum Spike(중간 이상치) 후보 추출

# 이전 / 현재 / 다음 누적값
prev = df_p15d['kwh_sum'].shift(1)
curr = df_p15d['kwh_sum']
next_ = df_p15d['kwh_sum'].shift(-1)

# Spike 크기 계산 ? 27 ~ 72kwh spike
df_p15d['spike_up'] = curr - prev
df_p15d['spike_down'] = curr - next_

# 중간값이 증가했다가 바로 감소하는 경우
spike_mask = (
    (curr > prev) &
    (next_ < curr)
)

# 후보 확인
print(f"Spike 후보 개수 : {spike_mask.sum()}")

print(
    df_p15d.loc[
        spike_mask,
        [
            'ts',
            'kwh_sum',
            'spike_up',
            'spike_down'
        ]
    ]
)

# CSV 저장 (EDA 및 육안 검증용)
df_p15d.loc[
    spike_mask,
    [
        'ts',
        'kwh_sum',
        'spike_up',
        'spike_down'
    ]
].to_csv(
    'kwh_sum_spike_candidate.csv',
    index=False,
    encoding='utf-8-sig'
)

print("저장 완료 : kwh_sum_spike_candidate.csv")


#%% 🔥제거될 비정상 데이터 저장 (EDA용)

outlier_df = df_p15d[
    (df_p15d['kwh_15m'] < 0)
    |
    (df_p15d['kwh_15m'] > 20)
]

outlier_df.to_csv(
    'kwh_15m_outlier.csv',
    index=False,
    encoding='utf-8-sig'
)

print(f'저장된 이상치 개수 : {len(outlier_df)}')


#%% 🔥비정상 kwh_15m 제거 (0 ~ 20 범위만 유지)


# 제거 전 개수
before = len(df_p15d)

# 0 <= kwh_15m <= 20 만 유지
df_p15d = (
    df_p15d[
        (df_p15d['kwh_15m'] >= 0)
        &
        (df_p15d['kwh_15m'] <= 20)
    ]
    .reset_index(drop=True)
)

# 제거 후 개수
after = len(df_p15d)

print(f'제거된 행 개수 : {before - after}')
print(f'남은 데이터 개수 : {after}')

# 확인
print('\nkwh_15m 기초통계량')
print(df_p15d['kwh_15m'].describe().round(3))




#%% eda ts에서 빈 날짜, 빈 시간대 확인

# 전체 기간(15분 간격) 생성
full_ts = pd.date_range(
    start=df_p15d['ts'].min(),
    end=df_p15d['ts'].max(),
    freq='15min'
)

# 실제 ts와 비교하여 누락된 시간 찾기
missing_ts = full_ts.difference(df_p15d['ts'])

# 결과 출력
print(f'누락된 시간 개수 : {len(missing_ts)}')

if len(missing_ts) > 0:
    print('\n누락된 날짜 및 시간')
    print(missing_ts)
else:
    print('\n누락된 날짜 및 시간이 없습니다.')



#%% eda 날짜별 누락 개수 확인
missing_df = pd.DataFrame({'missing_ts': missing_ts})
missing_df['date'] = missing_df['missing_ts'].dt.date

print('\n날짜별 누락 개수')
print(
    missing_df['date']
    .value_counts()
    .sort_index()
)

#%% ♻️csv 파일로 저장
df_p15d.to_csv(
    'df_p15d.csv',
    index=False,
    encoding='utf-8-sig'
)








# =====================================
# feature engineering
# =====================================


#%% ✨1시간 사용량 생성 

# ts를 인덱스로 설정
df_hour = (
    df_p15d
    .set_index('ts')
    .resample('1h')
    .agg(
        kwh_1h=('kwh_15m', 'sum'),
        cnt=('kwh_15m', 'count')
    )
    .reset_index()
)

df_hour = df_hour[df_hour['cnt'] == 4]

# 컬럼명 변경
df_hour = df_hour.rename(columns={
    'kwh_15m': 'kwh_1h'
})

# 확인
print(df_hour.head())
print(df_hour.shape)


# 

#%% ♻️ eda df_hour에서 누락된 날짜와 시간대 ?

# 전체 1시간 시계열 생성
full_hour = pd.date_range(
    start=df_hour['ts'].min(),
    end=df_hour['ts'].max(),
    freq='1h'
)

# 누락된 날짜·시간 찾기
missing_hour = full_hour.difference(df_hour['ts'])

# 출력
print(f'누락된 1시간 구간 수 : {len(missing_hour)}')

if len(missing_hour) > 0:
    print('\n[누락된 날짜와 시간]')
    for ts in missing_hour:
        print(ts)
else:
    print('\n누락된 날짜와 시간이 없습니다.')


#%% ♻️eda 누락된 시간대가 많은 달(내림차순) ?
# 누락된 시간대가 많은 달은 예측의 오차 발생 가능
# month
# 2025-09    144
# 2026-01     82
# 2025-10     42

# missing_hour : 누락된 1시간 datetime Index

missing_month = pd.DataFrame({
    'month': missing_hour.to_period('M').astype(str)
})

monthly_missing = (
    missing_month['month']
    .value_counts()          # 월별 누락 시간 개수
    .sort_values(ascending=False)   # 내림차순 정렬
)

print(monthly_missing)


#%% ♻️eda 1월달 누락된 날짜 분포 ? 
# 하순(21~31일)    57
# 상순(1~10일)     16
# 중순(11~20일)     9

# missing_hour : 누락된 1시간 datetime Index

# DataFrame 생성
jan_missing = pd.DataFrame({
    'missing_ts': missing_hour
})

# 1월 데이터만 추출
jan_missing = jan_missing[
    jan_missing['missing_ts'].dt.month == 1
].copy()

# 일(day) 컬럼 생성
jan_missing['day'] = jan_missing['missing_ts'].dt.day

# 날짜별 누락 시간 개수
jan_dist = (
    jan_missing['day']
    .value_counts()
    .sort_index()
)

print("1월 날짜별 누락 시간 개수")
print(jan_dist)


# 상순 / 중순 / 하순 집계
# -------------------------------
jan_missing['period'] = np.where(
    jan_missing['day'] <= 10,
    '상순(1~10일)',
    np.where(
        jan_missing['day'] <= 20,
        '중순(11~20일)',
        '하순(21~31일)'
    )
)

print("\n1월 상·중·하순별 누락 시간 개수")
print(
    jan_missing['period']
    .value_counts()
)



# %% ✨hour / 시간대
# ts 컬럼에서 시간(hour) 추출 → 0~23 시간대 변수 생성

df_hour['hour'] = df_hour['ts'].dt.hour

# 확인
print(df_hour[['ts', 'hour']].head())


# %% ✨weekday / 요일
# ts 컬럼에서 요일(weekday) 추출
# Monday=0, Sunday=6 형태로 생성됨

df_hour['weekday'] = df_hour['ts'].dt.weekday

# 확인
print(df_hour[['ts', 'weekday']].head())


#%% ✨is_weekend / 주말
# weekday를 기준으로 주말 여부 생성
# Saturday(5), Sunday(6) = 1 (주말), 그 외 = 0 (평일)

df_hour['is_weekend'] = (
    df_hour['weekday'].isin([5, 6])
).astype(int)

# 확인
print(
    df_hour[
        ['ts', 'weekday', 'is_weekend']
    ].head()
)


#%% ✨is_holiday / 공휴일
# holidays.KR() : 한국 법정 공휴일 자동 제공

is_holiday = set(holidays.KR().keys())

# 노동절(5월 1일) 추가
labor_day = pd.to_datetime(
    ["2026-05-01"]
).date

# date 컬럼 생성 (없으면 추가)
df_hour['date'] = df_hour['ts'].dt.date

# 공휴일 여부 생성
df_hour['is_holiday'] = (
    df_hour['date'].isin(is_holiday)
    |
    df_hour['date'].isin(labor_day)
).astype(int)

# 확인
print(
    df_hour[
        ['ts', 'is_holiday']
    ].head()
)


# %% ✨month / 계절성
# ts 컬럼에서 월(month) 추출

df_hour['month'] = df_hour['ts'].dt.month

# 확인
print(df_hour[['ts', 'month']].head())


# %% ✨day / 월초/월말 패턴
# ts 컬럼에서 일(day) 추출

df_hour['day'] = df_hour['ts'].dt.day

# 확인
print(df_hour[['ts', 'day']].head())


#%% 🔥df_temp csv 불러오기
df_temp = pd.read_csv("gwangju_temp.csv")

# 전부 NaN 행 제거
df_temp = df_temp.dropna(how='all')

# date 문자열 정리
df_temp['date'] = df_temp['date'].astype(str).str.strip()

# datetime 변환 (안전 처리)
df_temp['date'] = pd.to_datetime(df_temp['date'], errors='coerce')

# NaT 제거
df_temp = df_temp.dropna(subset=['date'])

# 중복 제거 (중요)
df_temp = df_temp.drop_duplicates(subset=['date'])

# 날짜만 남기기 (timezone 제거 + key 통일)
df_temp['date'] = df_temp['date'].dt.floor('D').dt.date


#%% 🔥df_hour date 생성

df_hour['ts'] = pd.to_datetime(df_hour['ts'])

df_hour['date'] = df_hour['ts'].dt.date


#%% 🔥merge (suffix 방지 + 안정화)
df_hour = pd.merge(
    df_hour,
    df_temp,
    on='date',
    how='left'
)


#%% 🔥 merge 검증 (핵심)
print("temp 결측 비율:", df_hour['avg_temp'].isna().mean())


#%% 🔥구조확인
print(df_hour.columns)


#%% 🔥 temp feature (hour version)

# 컬럼명 공백 제거
df_hour.columns = df_hour.columns.str.strip()

# --------------------------
# 1. ✨temp_range
# 일교차 (max - min)
df_hour['temp_range'] = (
    df_hour['daily_max_temp']
    - df_hour['daily_min_temp']
)


# --------------------------
# 2. ✨temp_centered
# 최근 7일 평균 대비 현재 기온 편차
# 7일 = 24 * 7 = 168시간
df_hour['temp_centered'] = (
    df_hour['avg_temp']
    - df_hour['avg_temp']
        .rolling(window=168, min_periods=1)
        .mean()
)


# --------------------------
# 3. ✨temp_ma_24 ✨temp_ma_168
# 1일 / 7일 이동평균
df_hour['temp_ma_24'] = (
    df_hour['avg_temp']
        .rolling(window=24, min_periods=1)
        .mean()
)

df_hour['temp_ma_168'] = (
    df_hour['avg_temp']
        .rolling(window=168, min_periods=1)
        .mean()
)


# --------------------------
# 4. ✨temp_diff_24 ✨temp_diff_168
# 1일 전 / 7일 전 대비 기온 변화
df_hour['temp_diff_24'] = (
    df_hour['avg_temp'].diff(24)
)

df_hour['temp_diff_168'] = (
    df_hour['avg_temp'].diff(168)
)


# --------------------------
# 5. ✨is_hot ✨is_cold
# 극한 온도 indicator
df_hour['is_hot'] = (
    df_hour['avg_temp'] >= 28
).astype(int)

df_hour['is_cold'] = (
    df_hour['avg_temp'] <= 5
).astype(int)


# --------------------------
# 6. ✨cooling_degree ✨heating_degree
# 냉방/난방 필요도
df_hour['cooling_degree'] = (
    df_hour['avg_temp'] - 24
).clip(lower=0)

df_hour['heating_degree'] = (
    18 - df_hour['avg_temp']
).clip(lower=0)


# 확인
print(
    df_hour[
        [
            'ts',
            'avg_temp',
            'temp_range',
            'temp_centered',
            'temp_ma_24',
            'temp_ma_168',
            'temp_diff_24',
            'temp_diff_168'
        ]
    ].head()
)



# %% ✨Lag Feature 생성 (kwh_1h 기준)
# --------------------------
# 1시간 단위 예측용 Lag Feature

# 1시간 전
df_hour['lag_1'] = df_hour['kwh_1h'].shift(1)

# 1일 전 같은 시간
df_hour['lag_24'] = df_hour['kwh_1h'].shift(24)

# 1주일 전 같은 시간
df_hour['lag_168'] = df_hour['kwh_1h'].shift(168)

# --------------------------
# 결측 처리
# 가장 긴 lag(168) 기준 제거

df_hour = df_hour.iloc[168:].reset_index(drop=True)

# 확인
print(
    df_hour[
        ['ts', 'kwh_1h', 'lag_1', 'lag_24', 'lag_168']
    ].head()
)


#%% ✨Rolling Feature 생성 (kwh_1h 기준)
# --------------------------
# Rolling Feature 생성

# 최근 3시간 평균
df_hour['rolling_mean_3'] = (
    df_hour['kwh_1h']
    .rolling(window=3)
    .mean()
)

# 최근 6시간 평균
df_hour['rolling_mean_6'] = (
    df_hour['kwh_1h']
    .rolling(window=6)
    .mean()
)

# 최근 24시간 평균
df_hour['rolling_mean_24'] = (
    df_hour['kwh_1h']
    .rolling(window=24)
    .mean()
)

# 최근 24시간 최대값
df_hour['rolling_max_24'] = (
    df_hour['kwh_1h']
    .rolling(window=24)
    .max()
)

# 최근 24시간 최소값
df_hour['rolling_min_24'] = (
    df_hour['kwh_1h']
    .rolling(window=24)
    .min()
)

# --------------------------
# 결측 처리
# 가장 긴 rolling window(24) 기준 제거

df_hour = df_hour.iloc[24:].reset_index(drop=True)

# 확인
print(
    df_hour[
        [
            'ts',
            'kwh_1h',
            'rolling_mean_3',
            'rolling_mean_6',
            'rolling_mean_24'
        ]
    ].head()
)


# %% ✨diff_1 (직전 1시간) / ✨diff_24 (1일 전) / ✨diff_168 (1주일 전)
# --------------------------
# Difference Feature 생성 (kwh_1h 기준)

# 직전 1시간 대비 변화량
df_hour['diff_1'] = df_hour['kwh_1h'].diff(1)

# 1일 전 동일 시간 대비 변화량
df_hour['diff_24'] = df_hour['kwh_1h'].diff(24)

# 1주일 전 동일 시간 대비 변화량
df_hour['diff_168'] = df_hour['kwh_1h'].diff(168)

# --------------------------
# 결측 처리
# 가장 큰 diff 기준(168) 이후 데이터 사용

df_hour = df_hour.iloc[168:].reset_index(drop=True)

# 확인
print(
    df_hour[
        [
            'ts',
            'kwh_1h',
            'diff_1',
            'diff_24',
            'diff_168'
        ]
    ].head()
)


#%% 🔥Feature Engineering 결과 저장 

df_hour.to_csv(
    'df_hour.csv',
    index=False,
    encoding='utf-8-sig'
)

print("저장 완료 : df_hour_after_diff.csv")


# ♻️ 수정필요 >>> 볼 수 있는 형태로 변수들 저장




# ====================================
# Walk-Forward Validation
# ====================================

# %% Walk-Forward 전 필수 점검 / shape (6366, 33)
print(df_hour.shape)

print(df_hour.isnull().sum())


#%% 🔥 X / y 분리

# X : 모델이 학습에 사용할 Feature
# 제외 컬럼
# - ts      : 시계열 인덱스
# - date    : 날짜 key
# - kwh_1h  : 예측 대상(Target)

X = df_hour.drop(
    columns=[
        'ts',
        'date',
        'kwh_1h'
    ]
)

# y : 예측 대상
y = df_hour['kwh_1h']

# 확인
print("X shape :", X.shape)
print("y shape :", y.shape)

print("\n=== X columns ===")
print(X.columns.tolist())

print("\n=== Target ===")
print(y.head())


#%% 🔥 Walk-Forward Validation Fold 정의

# --------------------------
# Train + CV
# 2025-08-20 ~ 2026-04-14
#
# Test
# 2026-04-15 ~ 2026-05-27
# --------------------------

folds = [

    (
        ('2025-08-20', '2025-10-31'),
        ('2025-11-01', '2025-11-30')
    ),

    (
        ('2025-08-20', '2025-11-30'),
        ('2025-12-01', '2025-12-31')
    ),

    (
        ('2025-08-20', '2025-12-31'),
        ('2026-01-01', '2026-01-31')
    ),

    (
        ('2025-08-20', '2026-01-31'),
        ('2026-02-01', '2026-02-28')
    ),

    (
        ('2025-08-20', '2026-02-28'),
        ('2026-03-01', '2026-03-31')
    ),

    (
        ('2025-08-20', '2026-03-31'),
        ('2026-04-01', '2026-04-14')
    )

]


#%% 🔥 Walk-Forward Validation Dataset 생성

cv_datasets = []

for fold_num, (train_period, valid_period) in enumerate(
    folds,
    start=1
):

    train_start, train_end = train_period
    valid_start, valid_end = valid_period

    # Train mask
    train_mask = (
        (df_hour['ts'] >= train_start)
        &
        (df_hour['ts'] <= train_end)
    )

    # Valid mask
    valid_mask = (
        (df_hour['ts'] >= valid_start)
        &
        (df_hour['ts'] <= valid_end)
    )

    # Dataset 생성
    X_train = X.loc[train_mask]
    y_train = y.loc[train_mask]

    X_valid = X.loc[valid_mask]
    y_valid = y.loc[valid_mask]

    cv_datasets.append({

        'fold': fold_num,

        'X_train': X_train,
        'y_train': y_train,

        'X_valid': X_valid,
        'y_valid': y_valid

    })

print("생성된 Fold 수 :", len(cv_datasets))


# =====================================
# LightGBM Baseline Model
# =====================================
#%% 🔥Walk-Forward Validation
cv_results = []

print("생성된 Fold 수 :", len(cv_datasets))

for fold_data in cv_datasets:

    # 1. Fold 데이터 불러오기
    fold_num = fold_data['fold']

    X_train = fold_data['X_train']
    y_train = fold_data['y_train']

    X_valid = fold_data['X_valid']
    y_valid = fold_data['y_valid']

    print(f"\n🚀 Fold {fold_num}")

    # 2. 데이터 검증
    print(
        f"Train={X_train.shape}, "
        f"Valid={X_valid.shape}"
    )

    if len(X_train) == 0 or len(X_valid) == 0:
        print("❌ 데이터 없음")
        continue

    # 3. 모델 학습
    model = LGBMRegressor(
        objective='regression',
        n_estimators=1000,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42
    )

    model.fit(X_train, y_train)

    # 4. 예측
    pred = model.predict(X_valid)


    # 5. 평가 지표 계산
    mae = mean_absolute_error(y_valid, pred)

    rmse = np.sqrt(
        mean_squared_error(y_valid, pred)
    )

    mape = (
        mean_absolute_percentage_error(
            y_valid,
            pred
        ) * 100
    )

    # 6. 결과 저장
    cv_results.append({
        'fold': fold_num,
        'MAE': mae,
        'RMSE': rmse,
        'MAPE': mape
    })

    # 7. Fold 결과 출력
    print(f"MAE  : {mae:.4f}")
    print(f"RMSE : {rmse:.4f}")
    print(f"MAPE : {mape:.2f}%")


#%% ♻️ 결과 요약

cv_results_df = pd.DataFrame(cv_results)

print("\n")
print("=" * 60)
print("Walk-Forward Validation Summary")
print("=" * 60)

# Baseline (직접 작성)
print("Baseline Model : LightGBM")
print()

# Fold별 결과
print(cv_results_df.to_string(index=False))

print("\nAverage Score")

print(
    cv_results_df[
        ['MAE', 'RMSE', 'MAPE']
    ].mean()
)


#%% 🔥Fold별 최소값 확인

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    y_valid = fold_data['y_valid']

    print(
        f"Fold {fold_num} "
        f"min={y_valid.min():.10f} "
        f"max={y_valid.max():.4f}"
    )

# --------------------------
# 분석 메모
# --------------------------
# 1. Fold 2, Fold 3에서 MAPE가 비정상적으로 크게 발생
#    → y_valid 최소값 확인 결과 0 kWh 존재
#    → MAPE 분모가 0이 되어 지표가 폭발한 것으로 판단
#
# 2. Fold 3에서 kwh_1h 최대값 188.1 확인
#    → 다른 Fold 최대값(약 6~12 수준) 대비 매우 큼
#    → 계량기 오류 / 누적치 차분 오류 / 실제 이벤트 여부 검증 필요
#
# 3. 다음 작업
#    (1) Fold 3 이상치(188.1 kWh) 검증
#    (2) Fold 2,3의 0 kWh 발생 원인 확인
# --------------------------




# =====================================
# 데이터 품질 개선
# =====================================
# --------------------------
# LigntGBM Baseline 결과 분석(♻️: 수정필요)
# --------------------------
#  fold      MAE     RMSE         MAPE
#     1 0.214601 0.553940 6.108244e+00
#     2 0.226443 0.827104 5.512481e+14
#     3 0.706892 5.220498 2.999036e+15
#     4 0.327720 0.965823 7.831491e+00
#     5 0.066917 0.187341 2.219669e+00
#     6 0.091723 0.492256 2.787994e+00
#
# Average Score
# MAE     2.723825e-01
# RMSE    1.374494e+00
# MAPE    5.917140e+14
#
# Fold 1 min=0.9000000000 max=7.1000
# Fold 2 min=0.0000000000 max=12.1000
# Fold 3 min=0.0000000000 max=188.1000♻️
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# --------------------------


#%% 🔥 Fold 3 이상치 조사
# Fold 3 Validation 구간 최대 사용량 확인

# Fold 3 데이터 추출
fold3 = cv_datasets[2]

# Validation 원본 데이터
fold3_df = df_hour.loc[
    fold3['y_valid'].index
].copy()

# 사용량 내림차순 확인
print(
    fold3_df[
        ['ts', 'kwh_1h']
    ]
    .sort_values(
        'kwh_1h',
        ascending=False
    )
    .head(20)
)


#%% 🔥 데이터 공백 구간(15분 초과 간격) 확인
df_p15d['time_diff'] = (
    df_p15d['ts']
    .diff()
    .dt.total_seconds()
    / 60
)

print(
    df_p15d[
        df_p15d['time_diff'] > 15
    ][
        ['ts', 'time_diff']
    ]
)

# --------------------------
# 분석 메모
# Fold 3에서 kwh_1h 최대값 188.1 확인
# --------------------------
# Fold 3 최대값(188.1 kWh) 이상치 원인 분석 완료
# 2026-01-29 17:45 이전에 장시간 데이터 공백(time_diff > 15분) 확인
# time_diff == 15 조건으로 kwh_15m 재생성 후 이상치 제거
# Fold 3 최대값 188.1 → 6.9 kWh로 정상화 확인


# --------------------------
# LigntGBM Baseline 결과 분석(♻️: 수정필요)
# --------------------------
#  fold      MAE     RMSE         MAPE
#     1 0.137295 0.297410 4.788370e+00
#     2 0.127951 0.391537 5.300565e+14
#     3 0.273749 1.880313 3.045263e+15
#     4 0.102531 0.227661 3.683834e+00
#     5 0.047377 0.084719 1.891068e+00
#     6 0.046639 0.080832 1.881641e+00
#
# Average Score
# MAE     1.225904e-01
# RMSE    4.937451e-01
# MAPE    5.958866e+14
#
# Fold 1 min=0.9000000000 max=6.5000
# Fold 2 min=0.0000000000 max=7.3000
# Fold 3 min=-46.8000000000♻️ max=6.9000
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# --------------------------


#%% 🔥 음수 사용량(kwh_15m < 0) 원인 조사

# 음수 사용량 발생 건수
print("음수 건수 :", (df_p15d['kwh_15m'] < 0).sum())

# 음수 사용량 전체 확인
print(
    df_p15d.loc[
        df_p15d['kwh_15m'] < 0,
        [
            'ts',
            'time_diff',
            'kwh_sum',
            'kwh_15m'
        ]
    ]
)





#%% 🔥 ts 중복 확인

dup_ts = df_p15d[
    df_p15d.duplicated(
        subset='ts',
        keep=False
    )
]

print("중복 행 수 :", len(dup_ts))

print(
    dup_ts[
        ['ts', 'kwh_sum']
    ]
    .sort_values('ts')
)


# --------------------------
# 분석 메모
# 음수 사용량(kwh_15m < 0) 원인 조사
# --------------------------
# 동일 ts에 서로 다른 kwh_sum 값이 중복 저장되어 있었음
# kwh_sum은 전체 기간 동안 정상 우상향으로 계량기 리셋 아님
# Fold 3 최소값(-46.8 kWh)은 데이터 중복에 의한 이상치로 판단
# ts 중복 제거 후 kwh_15m 및 df_hour 재생성 필요



# ==================================================
# LigntGBM Baseline 결과 분석(♻️: 수정필요)
# ==================================================
#  fold      MAE     RMSE         MAPE
#     1 0.095296 0.165802 3.610072e+00
#     2 0.088568 0.154397 3.322567e+14♻️
#     3 0.196353 0.401435 3.157398e+15♻️
#     4 0.055305 0.091562 2.047781e+00
#     5 0.040926 0.071851 1.559780e+00
#     6 0.044616 0.078194 1.735451e+00
#
# Average Score
# MAE     8.684404e-02
# RMSE    1.605401e-01
# MAPE    5.816092e+14
#
# Fold 1 min=0.9000000000 max=6.5000
# Fold 2 min=0.0000000000♻️ max=7.3000
# Fold 3 min=0.0000000000♻️ max=6.9000
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# ============================================================




# ♻️수정필요 >>> 음수 사용량이 아직까지 나오는 부분 해결




#%% 🔥 Fold 2, Fold 3의 0 kWh 발생 시점 확인

for fold_num in [2, 3]:

    fold = cv_datasets[fold_num - 1]

    fold_df = df_hour.loc[
        fold['y_valid'].index
    ].copy()

    zero_df = fold_df[
        fold_df['kwh_1h'] == 0
    ]

    print("\n" + "=" * 50)
    print(f"Fold {fold_num}")
    print("=" * 50)
    print("0 kWh 건수 :", len(zero_df))

    print(
        zero_df[
            ['ts', 'kwh_1h']
        ]
        .sort_values('ts')
    )

#%% 🔥 Fold 3의 0 kWh 구간 원본 15분 데이터 확인

start_ts = '2026-01-09 04:00:00+09:00'
end_ts   = '2026-01-09 16:00:00+09:00'

print(
    df_p15d[
        (df_p15d['ts'] >= start_ts)
        &
        (df_p15d['ts'] <= end_ts)
    ][
        ['ts', 'kwh_sum', 'kwh_15m']
    ]
)

# ==================================================
# 분석 메모
# Fold 2·3의 0 kWh 분석
# ==================================================
# Fold 2(1건), Fold 3(65건)의 0 kWh 발생 원인을 조사함.
# 일부 시간대는 15분 사용량 데이터가 4개 미만인 상태로 1시간 사용량(kwh_1h)이 집계
# 정상적으로 15분 데이터 4개가 존재하는 시간대만 사용하도록 전처리를 수정
# 재검증 결과 Fold 2·3의 0 kWh 문제가 해소되었으며 MAPE도 정상 수준으로 안정화


# ============================================================
# LigntGBM Baseline 결과 분석
# ============================================================
#  fold      MAE     RMSE     MAPE
#     1 0.104201 0.183405 3.974299
#     2 0.096800 0.160582 3.637112
#     3 0.223453 0.486938 5.306139
#     4 0.061830 0.117460 2.099196
#     5 0.043157 0.080009 1.563095
#     6 0.049141 0.082938 1.970155
#
# Average Score
# MAE     0.096430
# RMSE    0.185222
# MAPE    3.091666
# dtype: float64
#
# Fold 1 min=0.9000000000 max=6.5000
# Fold 2 min=1.0000000000 max=7.3000
# Fold 3 min=1.0000000000 max=6.9000
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000






# ♻️ 수정 >>> 중복된 검증 과정, 위에서 이미 해결된 것들은 '주석' 처리


# ============================================================
# Walk-Forward Validation Summary
# ============================================================
#  fold      MAE     RMSE     MAPE
#     1 0.106506 0.186180 4.086201
#     2 0.099970 0.169492 3.674308
#     3 0.224844 0.490714 5.355929
#     4 0.063080 0.124320 2.112341
#     5 0.043944 0.081108 1.612410
#     6 0.047613 0.080228 1.884227

# Average Score
# MAE     0.097660
# RMSE    0.188674
# MAPE    3.120902
# dtype: float64











# =====================================
# ((Baseline Model Comparison))
# =====================================
# 1. LightGBM Baseline (모델 객체 저장)
# ============================================================

#%% 🔥 LightGBM Baseline Training

lgbm_cv_results = []
lgbm_models = []   # fold별 모델 저장

print("LightGBM Fold 수:", len(cv_datasets))

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    X_train = fold_data['X_train']
    y_train = fold_data['y_train']

    X_valid = fold_data['X_valid']
    y_valid = fold_data['y_valid']

    print(f"\n🚀 LightGBM Fold {fold_num}")

    model = LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        random_state=42
    )

    model.fit(X_train, y_train)

    pred = model.predict(X_valid)

    lgbm_models.append(model)

    lgbm_cv_results.append({

        'fold': fold_num,
        'MAE': mean_absolute_error(y_valid, pred),
        'RMSE': np.sqrt(mean_squared_error(y_valid, pred)),
        'MAPE': mean_absolute_percentage_error(y_valid, pred) * 100
    })


#%% 🔥 LightGBM 결과 요약

lgbm_results_df = pd.DataFrame(lgbm_cv_results)

print("\n=== LightGBM Summary ===")
print(lgbm_results_df)

print("\nAverage")
print(lgbm_results_df[['MAE','RMSE','MAPE']].mean())


# ============================================================
# 2. XGBoost Baseline (모델 객체 저장)
# ============================================================

#%% 🔥 XGBoost Baseline Training

xgb_cv_results = []
xgb_models = []   # fold별 모델 저장

print("XGBoost Fold 수:", len(cv_datasets))

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    X_train = fold_data['X_train']
    y_train = fold_data['y_train']

    X_valid = fold_data['X_valid']
    y_valid = fold_data['y_valid']

    print(f"\n🚀 XGBoost Fold {fold_num}")

    model = XGBRegressor(
        objective='reg:squarederror',
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1
    )

    model.fit(X_train, y_train)

    pred = model.predict(X_valid)

    xgb_models.append(model)

    xgb_cv_results.append({

        'fold': fold_num,
        'MAE': mean_absolute_error(y_valid, pred),
        'RMSE': np.sqrt(mean_squared_error(y_valid, pred)),
        'MAPE': mean_absolute_percentage_error(y_valid, pred) * 100
    })


#%% 🔥 XGBoost 결과 요약

xgb_results_df = pd.DataFrame(xgb_cv_results)

print("\n=== XGBoost Summary ===")
print(xgb_results_df)

print("\nAverage")
print(xgb_results_df[['MAE','RMSE','MAPE']].mean())

# === Model Comparison ===
#       Model       MAE      RMSE      MAPE
# 0  LightGBM  0.096974  0.185960  3.132412
# 1   XGBoost  0.094370  0.172908  3.138497


# =====================================
# ((Feature Reduced Model Comparison))
# =====================================
# 3. Feature Importance (모델 선택)
# ============================================================

#%% 🔥 Feature Importance용 대표 모델 선택 (마지막 fold)

lgbm_model = lgbm_models[-1]
xgb_model = xgb_models[-1]


# ============================================================
# 4. LightGBM Feature Importance
# ============================================================

#%% 🔥 LightGBM Feature Importance

lgbm_importance = pd.DataFrame({

    'feature': X.columns,
    'importance': lgbm_model.feature_importances_
})

lgbm_importance = lgbm_importance.sort_values(
    by='importance',
    ascending=False
)

print("\n=== LightGBM Top 20 ===")
print(lgbm_importance.head(20))


#%% 🔥 LightGBM Importance 시각화

plt.figure(figsize=(10,6))

plt.barh(
    lgbm_importance['feature'][:20][::-1],
    lgbm_importance['importance'][:20][::-1]
)

plt.title("LightGBM Feature Importance")
plt.show()


# ============================================================
# 5. XGBoost Feature Importance
# ============================================================

#%% 🔥 XGBoost Feature Importance

xgb_importance = pd.DataFrame({

    'feature': X.columns,
    'importance': xgb_model.feature_importances_
})

xgb_importance = xgb_importance.sort_values(
    by='importance',
    ascending=False
)

print("\n=== XGBoost Top 20 ===")
print(xgb_importance.head(20))


#%% 🔥 XGBoost Importance 시각화

plt.figure(figsize=(10,6))

plt.barh(
    xgb_importance['feature'][:20][::-1],
    xgb_importance['importance'][:20][::-1]
)

plt.title("XGBoost Feature Importance")
plt.show()


# ============================================================
# 6. 통합 Feature Importance
# ============================================================

#%% 🔥 Feature Importance Merge

merged = pd.merge(
    lgbm_importance,
    xgb_importance,
    on='feature',
    suffixes=('_lgbm', '_xgb')
)

merged['avg_importance'] = (
    merged['importance_lgbm'] +
    merged['importance_xgb']
) / 2

merged = merged.sort_values(
    by='avg_importance',
    ascending=False
)

print("\n=== Combined Top 20 ===")
print(merged.head(20))


# ============================================================
# 7. 모델 비교
# ============================================================

#%% 🔥 Model Comparison

compare_df = pd.DataFrame({

    'Model': ['LightGBM', 'XGBoost'],

    'MAE': [
        lgbm_results_df['MAE'].mean(),
        xgb_results_df['MAE'].mean()
    ],

    'RMSE': [
        lgbm_results_df['RMSE'].mean(),
        xgb_results_df['RMSE'].mean()
    ],

    'MAPE': [
        lgbm_results_df['MAPE'].mean(),
        xgb_results_df['MAPE'].mean()
    ]
})

print("\n=== Model Comparison ===")
print(compare_df)

# === Model Comparison ===
#       Model       MAE      RMSE      MAPE
# 0  LightGBM  0.096974  0.185960  3.132412
# 1   XGBoost  0.094370  0.172908  3.138497

#%% ============================================================
# Feature Selection (Importance 기반 제거)
# ============================================================

drop_features = [

    'daily_max_temp',
    'temp_range',
    'temp_ma_168',
    'temp_ma_24',
    'temp_diff_168',
    'temp_diff_24',
    'temp_centered',
    'day'
]

# Feature 제거
X_reduced = X.drop(columns=drop_features)

print("기존 Feature 개수:", X.shape[1])
print("축소 후 Feature 개수:", X_reduced.shape[1])
print("\n제거된 Feature:", drop_features)


#%% ============================================================
# LightGBM Retrain (Reduced Feature)
# ============================================================

lgbm_reduced_results = []

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    # reduced feature 적용 (중요)
    X_train = fold_data['X_train'][X_reduced.columns]
    X_valid = fold_data['X_valid'][X_reduced.columns]

    y_train = fold_data['y_train']
    y_valid = fold_data['y_valid']

    model = LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        random_state=42
    )

    model.fit(X_train, y_train)

    pred = model.predict(X_valid)

    lgbm_reduced_results.append({

        'fold': fold_num,
        'MAE': mean_absolute_error(y_valid, pred),
        'RMSE': np.sqrt(mean_squared_error(y_valid, pred)),
        'MAPE': mean_absolute_percentage_error(y_valid, pred) * 100
    })

print("LightGBM Reduced 완료")


#%% ============================================================
# XGBoost Retrain (Reduced Feature)
# ============================================================

xgb_reduced_results = []

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    # reduced feature 적용
    X_train = fold_data['X_train'][X_reduced.columns]
    X_valid = fold_data['X_valid'][X_reduced.columns]

    y_train = fold_data['y_train']
    y_valid = fold_data['y_valid']

    model = XGBRegressor(

        objective='reg:squarederror',

        n_estimators=1000,
        learning_rate=0.05,

        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,

        random_state=42,
        n_jobs=-1
    )

    model.fit(X_train, y_train)

    pred = model.predict(X_valid)

    xgb_reduced_results.append({

        'fold': fold_num,
        'MAE': mean_absolute_error(y_valid, pred),
        'RMSE': np.sqrt(mean_squared_error(y_valid, pred)),
        'MAPE': mean_absolute_percentage_error(y_valid, pred) * 100
    })

print("XGBoost Reduced 완료")


#%% ============================================================
# Reduced Model Comparison
# ============================================================

lgbm_red_df = pd.DataFrame(lgbm_reduced_results)
xgb_red_df = pd.DataFrame(xgb_reduced_results)

compare_reduced = pd.DataFrame({

    'Model': ['LightGBM (Reduced)', 'XGBoost (Reduced)'],

    'MAE': [
        lgbm_red_df['MAE'].mean(),
        xgb_red_df['MAE'].mean()
    ],

    'RMSE': [
        lgbm_red_df['RMSE'].mean(),
        xgb_red_df['RMSE'].mean()
    ],

    'MAPE': [
        lgbm_red_df['MAPE'].mean(),
        xgb_red_df['MAPE'].mean()
    ]
})

print("\n=== Feature Reduced Model Comparison ===")
print(compare_reduced)


# === Feature Reduced Model Comparison ===
#                 Model       MAE      RMSE      MAPE
# 0  LightGBM (Reduced)  0.094109  0.183183  3.010055
# 1   XGBoost (Reduced)  0.082278✅  0.157294  2.653010

# Best Model: XGBoost (Feature Reduced Version)



# =====================================
#((Reduced XGBoost Hyper Parameter Tuning))
# =====================================
#%% ============================================================
# 🚀 1. Feature 선택 (Reduced Feature Set 사용)
# ============================================================

FEATURES = X_reduced.columns


#%% ============================================================
# 🚀 2. Optuna Objective 함수 정의
# ============================================================

def objective(trial):

    # ============================================================
    # 🔧 2-1. Hyperparameter Search Space 정의
    # ============================================================

    params = {

        "objective": "reg:squarederror",   # 회귀 문제 설정
        "eval_metric": "mae",              # 평가 기준 (MAE)

        # Tree complexity (모델 깊이)
        "max_depth": trial.suggest_int("max_depth", 2, 6),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 15),

        # Row / Feature sampling (overfitting control)
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),

        # Learning rate (학습 속도)
        "eta": trial.suggest_float("learning_rate", 0.01, 0.08),

        # Regularization (복잡도 제한)
        "gamma": trial.suggest_float("gamma", 0, 5),
        "alpha": trial.suggest_float("reg_alpha", 0, 3),
        "lambda": trial.suggest_float("reg_lambda", 0, 6),

        "seed": 42
    }

    fold_mae = []


    # ============================================================
    # 🚀 3. Walk-Forward Cross Validation
    # ============================================================
    # - 시간 순서를 유지한 시계열 검증 방식
    # - 과거 → 미래 구조 유지 (data leakage 방지)
    # ============================================================

    for fold in cv_datasets:

        # -------------------------------
        # 3-1. Train / Validation split
        # -------------------------------
        X_train = fold['X_train'][FEATURES]
        y_train = fold['y_train']

        X_valid = fold['X_valid'][FEATURES]
        y_valid = fold['y_valid']

        # -------------------------------
        # 3-2. XGBoost 전용 데이터 구조 변환
        # -------------------------------
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dvalid = xgb.DMatrix(X_valid, label=y_valid)

        # -------------------------------
        # 3-3. 모델 학습 (Early Stopping 적용)
        # -------------------------------
        # - validation MAE 개선 없으면 50 rounds 후 자동 종료
        # - best iteration 기준 모델 자동 선택
        # -------------------------------

        model = xgb.train(

            params=params,
            dtrain=dtrain,

            num_boost_round=5000,          # 최대 iteration

            evals=[(dvalid, "valid")],     # validation set 지정

            early_stopping_rounds=50,      # 성능 개선 없으면 종료
            verbose_eval=False             # 로그 출력 제거
        )

        # -------------------------------
        # 3-4. Validation prediction
        # -------------------------------
        pred = model.predict(dvalid)

        # -------------------------------
        # 3-5. Fold MAE 계산
        # -------------------------------
        mae = mean_absolute_error(y_valid, pred)
        fold_mae.append(mae)

    # ============================================================
    # 🚀 4. 전체 Fold 평균 성능 반환
    # ============================================================

    return np.mean(fold_mae)


#%% ============================================================
# 🚀 5. Optuna Study 실행
# ============================================================
# - 50번의 trial 수행 (hyperparameter 탐색)
# ============================================================

study = optuna.create_study(direction="minimize")

study.optimize(
    objective,
    n_trials=50
)


#%% ============================================================
# 🚀 6. 최적 결과 출력
# ============================================================

print("\nBest MAE:", study.best_value)
print("\nBest Params:")
print(study.best_params)


# ============================================================
# # XGBoost (Reduced Feature) Optuna 최종 결과
# ============================================================
#
# # Best MAE (Walk-Forward CV 평균)
# Best MAE: 0.10116068785999129✅
#
# ============================================================
# # Best Parameters
# ============================================================
#
# Best Params = {
#     # tree depth (model complexity)
#     "max_depth": 4,
#
#     # leaf stability
#     "min_child_weight": 5,
#
#     # row sampling
#     "subsample": 0.7470782577876993,
#
#     # feature sampling
#     "colsample_bytree": 0.9948124488867198,
#
#     # learning rate
#     "learning_rate": 0.0619510976123152,
#
#     # split regularization
#     "gamma": 0.01856654855064753,
#
#     # L1 regularization
#     "reg_alpha": 0.7104496718998039,
#
#     # L2 regularization
#     "reg_lambda": 0.30980551941042905
# }



# =====================================
# ((Reduced LightGBM Hyper Parameter Tuning))
# =====================================


#%% 🚀 1. Feature 설정 (Reduced Feature 사용)
FEATURES = X_reduced.columns


#%% 🚀 2. Optuna + LightGBM Objective 정의 (Walk-Forward CV)

def objective(trial):

    # ============================================================
    # 🔧 Hyperparameter Search Space
    # ============================================================
    params = {

        "objective": "regression",
        "metric": "mae",
        "verbosity": -1,

        # tree complexity
        "num_leaves": trial.suggest_int("num_leaves", 16, 128),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 10, 100),

        # sampling
        "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 1, 5),

        # learning rate
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.08),

        # regularization
        "lambda_l1": trial.suggest_float("lambda_l1", 0, 3),
        "lambda_l2": trial.suggest_float("lambda_l2", 0, 6),

        "random_state": 42
    }

    fold_mae = []

    # ============================================================
    # 🚀 3. Walk-Forward Validation Loop
    # ============================================================
    for fold in cv_datasets:

        # -----------------------
        # Train / Valid split
        # -----------------------
        X_train = fold["X_train"][FEATURES]
        y_train = fold["y_train"]

        X_valid = fold["X_valid"][FEATURES]
        y_valid = fold["y_valid"]

        # -----------------------
        # Model 생성
        # -----------------------
        model = lgb.LGBMRegressor(
            **params,
            n_estimators=5000   # 충분히 크게 설정 (early stopping으로 제어)
        )

        # -----------------------
        # Early Stopping 학습
        # -----------------------
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_valid, y_valid)],
            eval_metric="mae",
            callbacks=[
                lgb.early_stopping(stopping_rounds=50, verbose=False)
            ]
        )

        # -----------------------
        # Prediction + MAE 계산
        # -----------------------
        pred = model.predict(X_valid)
        mae = mean_absolute_error(y_valid, pred)

        fold_mae.append(mae)

    # ============================================================
    # 🚀 평균 MAE 반환
    # ============================================================
    return np.mean(fold_mae)


#%% 🚀 4. Optuna Study 실행 (50 trials)

study = optuna.create_study(direction="minimize")

study.optimize(
    objective,
    n_trials=50
)


#%% 🚀 5. 최종 결과 출력
print("\nBest MAE:", study.best_value)

print("\nBest Params:")
print(study.best_params)


# ============================================================
# LightGBM (Reduced Feature) Optuna 최종 결과
# ============================================================

# Best MAE
# 0.0864553730162728✅

# ============================================================
# Best Params (요약)
# ============================================================

# Tree
# num_leaves       : 108
# max_depth        : 9
# min_data_in_leaf : 26

# Sampling
# feature_fraction : 0.7769
# bagging_fraction : 0.8760
# bagging_freq     : 2

# Learning
# learning_rate    : 0.0141

# Regularization
# lambda_l1        : 0.1454
# lambda_l2        : 4.4090

# ============================================================
# 결론
# ============================================================

# Best Model: LightGBM (Reduced + Optuna)
# MAE: 0.08645
# Result: Best generalization performance




# =====================================
# Fold 3 Error Analysis (EDA)
# =====================================
# Model : XGBoost Reduced Version
# 목적:
# Fold 3 MAE가 높은 원인 파악
# ============================================================


# %%============================================================
# STEP 1
# Fold 3 Dataset 추출
# ============================================================

print("=" * 60)
print("STEP 1. Fold 3 데이터 추출")
print("=" * 60)

fold3 = cv_datasets[2]

X_train = fold3['X_train'][X_reduced.columns]
y_train = fold3['y_train']

X_valid = fold3['X_valid'][X_reduced.columns]
y_valid = fold3['y_valid']

print("Train Shape :", X_train.shape)
print("Valid Shape :", X_valid.shape)


# %%============================================================
# STEP 2
# XGBoost Reduced Version 학습
# ============================================================

print("\n" + "=" * 60)
print("STEP 2. XGBoost Reduced Model 학습")
print("=" * 60)

model = XGBRegressor(

    objective='reg:squarederror',

    n_estimators=1000,
    learning_rate=0.05,

    max_depth=6,
    subsample=0.8,
    colsample_bytree=0.8,

    random_state=42,
    n_jobs=-1
)

model.fit(X_train, y_train)

pred = model.predict(X_valid)

mae = mean_absolute_error(y_valid, pred)

print(f"Fold 3 MAE : {mae:.6f}")


# %%============================================================
# STEP 3
# Prediction DataFrame 생성
# ============================================================

print("\n" + "=" * 60)
print("STEP 3. Prediction DataFrame 생성")
print("=" * 60)

fold3_result = df_hour.loc[
    y_valid.index
].copy()

fold3_result['actual'] = y_valid.values
fold3_result['pred'] = pred

fold3_result['abs_error'] = np.abs(
    fold3_result['actual']
    - fold3_result['pred']
)

print(
    fold3_result[
        ['ts','actual','pred','abs_error']
    ].head()
)


# %%============================================================
# STEP 4
# Actual vs Prediction
# ============================================================

print("\n" + "=" * 60)
print("STEP 4. Actual vs Prediction 시각화")
print("=" * 60)

plt.figure(figsize=(18,6))

plt.plot(
    fold3_result['ts'],
    fold3_result['actual'],
    label='Actual'
)

plt.plot(
    fold3_result['ts'],
    fold3_result['pred'],
    label='Prediction'
)

plt.title(
    "Fold 3 (XGBoost Reduced)\nActual vs Prediction"
)

plt.xlabel("Time")
plt.ylabel("kWh")

plt.legend()
plt.grid(True)

plt.show()


# %%============================================================
# STEP 5
# 절대오차 TOP20
# ============================================================

print("\n" + "=" * 60)
print("STEP 5. 절대오차 TOP 20 추출")
print("=" * 60)

top20_error = (

    fold3_result

    .sort_values(
        'abs_error',
        ascending=False
    )

    .head(20)
)

print(

    top20_error[
        [
            'ts',
            'actual',
            'pred',
            'abs_error'
        ]
    ]

)


# %%============================================================
# STEP 6
# 오차 집중 날짜
# ============================================================

print("\n" + "=" * 60)
print("STEP 6. 오차 집중 날짜 확인")
print("=" * 60)

top20_error['date'] = (
    pd.to_datetime(
        top20_error['ts']
    ).dt.date
)

print(
    top20_error['date']
    .value_counts()
)


# %%============================================================
# STEP 7
# 오차 발생일 특성 확인
# ============================================================

print("\n" + "=" * 60)
print("STEP 7. 오차 발생일 특성 확인")
print("=" * 60)

error_dates = (
    top20_error['date']
    .unique()
)

error_day_info = (

    df_hour[
        df_hour['date'].isin(error_dates)
    ]

    [
        [
            'date',
            'avg_temp',
            'weekday',
            'is_weekend',
            'is_holiday'
        ]
    ]

    .drop_duplicates()
)

print(error_day_info)


# %%============================================================
# STEP 8
# Worst Day 확대 분석
# ============================================================

print("\n" + "=" * 60)
print("STEP 8. Worst Day 확대 분석")
print("=" * 60)

worst_day = top20_error.iloc[0]['date']

print("Worst Day :", worst_day)

worst_df = fold3_result[
    fold3_result['date']
    == worst_day
]

plt.figure(figsize=(15,5))

plt.plot(
    worst_df['ts'],
    worst_df['actual'],
    marker='o',
    label='Actual'
)

plt.plot(
    worst_df['ts'],
    worst_df['pred'],
    marker='o',
    label='Prediction'
)

plt.title(
    f"Worst Error Day : {worst_day}"
)

plt.grid(True)
plt.legend()

plt.show()


# %%============================================================
# STEP 9
# 시간대별 MAE
# ============================================================

print("\n" + "=" * 60)
print("STEP 9. Fold 3 시간대별 MAE")
print("=" * 60)

hourly_df = pd.DataFrame({

    'ts': df_hour.loc[
        y_valid.index,
        'ts'
    ].values,

    'actual': y_valid.values,
    'pred': pred
})

hourly_df['abs_error'] = (
    hourly_df['actual']
    - hourly_df['pred']
).abs()

hourly_df['hour'] = (
    pd.to_datetime(
        hourly_df['ts']
    ).dt.hour
)

hourly_mae = (

    hourly_df

    .groupby('hour')['abs_error']

    .mean()

    .reset_index()

)

print(hourly_mae)

print("\nTOP 10 Hourly MAE")

print(

    hourly_mae

    .sort_values(
        'abs_error',
        ascending=False
    )

    .head(10)

)


# %%============================================================
# STEP 10
# 시간대별 MAE 시각화
# ============================================================

print("\n" + "=" * 60)
print("STEP 10. 시간대별 MAE 시각화")
print("=" * 60)

plt.figure(figsize=(10,5))

plt.bar(
    hourly_mae['hour'],
    hourly_mae['abs_error']
)

plt.title(
    "Fold 3 Hourly MAE (XGBoost Reduced)"
)

plt.xlabel("Hour")
plt.ylabel("MAE")

plt.grid(True)

plt.show()


print("\nEDA 완료")


# Fold 3 오차는 두 가지 생활 패턴 변화에서 발생한 것으로 추정

# 1) 새벽(00~05시)
# 일반적인 야간 대기전력 수준보다 실제 사용량이 높게 유지됨
# 동절기 난방기·순환펌프·동파방지 설비 등이 야간에도 계속 동작한 것으로 추정
# 모델은 평상시 야간 패턴을 주로 학습하여 새벽 사용량을 지속적으로 낮게 예측함

# 2) 오전(09~11시)
# 출근 직후 난방 재가동과 업무용 설비 사용이 동시에 증가함
# 특히 한파 기간에는 실내온도 회복을 위한 난방 부하가 평소보다 크게 발생함
# 모델은 평상시 출근 패턴은 학습했지만 한파 시 급증하는 오전 부하는 충분히 학습하지 못함

# 결과적으로 Fold 3 MAE 증가는
# '야간 난방 유지 부하 증가'와 '한파 아침 난방 집중 가동'이 동시에 반영된 결과로 판단됨