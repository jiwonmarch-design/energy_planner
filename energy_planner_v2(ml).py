# =====================================
# 🎉 energy planner project 🎉
# =====================================
# 개발 환경
# Python 3.14 (64 bit)
# LightGBM / XGBoost 최종 버전
#
# VS Code 실행 전
# Python: Select Interpreter
# → Python 3.14 (64 bit) 선택

#%% 🔥라이브러리
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import lightgbm as lgb
import xgboost as xgb

import holidays
import optuna
import xgboost
import joblib
import requests

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
#%%
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

# ts 중복 제거 
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


#%% 🔥ts에서 월별 누락된 시간 개수 확인

# 전체 15분 시계열 생성
full_ts = pd.date_range(
    start=df_p15d['ts'].min(),
    end=df_p15d['ts'].max(),
    freq='15min'
)

# 누락된 시간 추출
missing_ts = full_ts.difference(
    df_p15d['ts']
)

print(
    f'전체 누락 시간 개수 : {len(missing_ts)}'
)

# 월별 누락 개수 집계
missing_month = pd.DataFrame({
    'month': missing_ts.to_period('M').astype(str)
})

print("\n월별 누락 시간 개수")
print(
    missing_month['month']
    .value_counts()
    .sort_index()
)

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


#%% ✨kwh_1h 생성

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

# 15분 데이터가 4개 모두 존재하는 시간만 사용
df_hour = df_hour[
    df_hour['cnt'] == 4
]

# (선택) 이후 feature 생성 시 cnt는 필요 없으므로 제거
df_hour = df_hour.drop(columns='cnt')

# 확인
print(df_hour.head())
print(df_hour.shape)





#%% 📈EDA : 15분 간격 ts에서 월별 누락 시간 개수 확인

# 전체 기간(15분 간격) 생성
full_ts = pd.date_range(
    start=df_p15d['ts'].min(),
    end=df_p15d['ts'].max(),
    freq='15min'
)

# 실제 ts와 비교하여 누락된 시간 찾기
missing_ts = full_ts.difference(
    df_p15d['ts']
)

# 결과 출력
print(
    f'누락된 시간 개수 : {len(missing_ts)}'
)

if len(missing_ts) > 0:

    # 월(month) 컬럼 생성
    missing_df = pd.DataFrame({
        'month': missing_ts.to_period('M').astype(str)
    })

    print('\n월별 누락 시간 개수')

    print(
        missing_df['month']
        .value_counts()
        .sort_index()
    )

else:
    print('\n누락된 날짜 및 시간이 없습니다.')



#%% 📈EDA : 1시간 단위 누락 시간 계산

full_hour = pd.date_range(
    start=df_hour['ts'].min(),
    end=df_hour['ts'].max(),
    freq='1h'
)

missing_hour = full_hour.difference(
    df_hour['ts']
)

print(
    f'1시간 단위 누락 개수 : {len(missing_hour)}'
)


#%% 📈EDA : 1시간 간격 누락된 시간대가 많은 달(내림차순) ?
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


#%% 📈EDA : 1월달 누락된 날짜 분포 ? 
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


#%% ♻️csv 파일로 저장

df_p15d.to_csv(
    'df_p15d.csv',
    index=False,
    encoding='utf-8-sig'
)



#%% 
# =====================================
# feature engineering
# =====================================

#%% ✨hour / 시간대
# ts 컬럼에서 시간(hour) 추출 → 0~23 시간대 변수 생성

df_hour['hour'] = df_hour['ts'].dt.hour

# 확인
print(df_hour[['ts', 'hour']].head())


#%% ✨weekday / 요일
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


#%% ✨month / 계절성
# ts 컬럼에서 월(month) 추출

df_hour['month'] = df_hour['ts'].dt.month

# 확인
print(df_hour[['ts', 'month']].head())


#%% ✨day / 월초/월말 패턴
# ts 컬럼에서 일(day) 추출

df_hour['day'] = df_hour['ts'].dt.day

# 확인
print(df_hour[['ts', 'day']].head())


#%% 🔥df_temp csv 불러오기
# df_hour(전력 사용량)과 df_temp(기온 데이터)를 안정적으로 결합하여 
# 온도 Feature를 생성하기 위한 전처리 과정

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


#%% 🔥merge 검증 (핵심)
print("temp 결측 비율:", df_hour['avg_temp'].isna().mean())


#%% 🔥구조확인
print(df_hour.columns)


#%% ✨temp feature

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
# 5. ✨ Temperature Indicator

# 더운 날
df_hour['is_hot'] = (
    df_hour['avg_temp'] >= 28
).astype(int)

# 추운 날
df_hour['is_cold'] = (
    df_hour['avg_temp'] <= 5
).astype(int)

# 강한 추위
df_hour['is_very_cold'] = (
    df_hour['avg_temp'] <= 0
).astype(int)

# 극한 추위 (광주에서는 드문 이벤트)
df_hour['is_extreme_cold'] = (
    df_hour['avg_temp'] <= -3
).astype(int)

# 전일 대비 평균기온 변화량
df_hour['temp_diff_prev_day'] = (
    df_hour['avg_temp']
    - df_hour['avg_temp'].shift(24)
)

# 전일 대비 평균기온 5℃ 이상 하락
df_hour['is_temp_drop_5'] = (
    df_hour['temp_diff_prev_day'] <= -5
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



#%% ✨Lag Feature 생성 (kwh_1h 기준)
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


#%% ✨diff_1 (직전 1시간) / ✨diff_24 (1일 전) / ✨diff_168 (1주일 전)
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
    'df_hour_v2.csv',
    index=False,
    encoding='utf-8-sig'
)

print("저장 완료 : df_hour_v2.csv")


# ♻️ 수정필요 >>> 볼 수 있는 형태로 변수들 저장



#%%
# =====================================
# Walk-Forward Valid 만들기
# =====================================

#%% 🔥Walk-Forward 전 필수 점검 / shape (6366, 33)
print(df_hour.shape)

print(df_hour.isnull().sum())


#%% 🔥X / y 분리

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


#%% 📈Fold별 데이터 개수 확인

for i, (
    (train_start, train_end),
    (valid_start, valid_end)
) in enumerate(folds, start=1):

    train_mask = (
        (df_hour['ts'] >= train_start)
        &
        (df_hour['ts'] <= train_end)
    )

    valid_mask = (
        (df_hour['ts'] >= valid_start)
        &
        (df_hour['ts'] <= valid_end)
    )

    print(
        f'Fold {i} | '
        f'Train : {train_mask.sum():5d}개 '
        f'({train_start} ~ {train_end}) | '
        f'Valid : {valid_mask.sum():5d}개 '
        f'({valid_start} ~ {valid_end})'
    )


#%% 🔥Walk-Forward Validation Dataset 생성

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



#%%
# =====================================
# LightGBM Baseline Model
# =====================================


#%% 🔥LightGBM Baseline Training

lgbm_results = []      # Fold별 결과 저장 (list)
lgbm_models = []

print("LightGBM Fold 수 :", len(cv_datasets))

for fold_data in cv_datasets:

    # 1. Fold 데이터 불러오기
    fold_num = fold_data['fold']

    X_train = fold_data['X_train']
    y_train = fold_data['y_train']

    X_valid = fold_data['X_valid']
    y_valid = fold_data['y_valid']

    print(f"\n🚀 LightGBM Fold {fold_num}")

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

    # 모델 저장
    lgbm_models.append(model)

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
    lgbm_results.append({
        'fold': fold_num,
        'MAE': mae,
        'RMSE': rmse,
        'MAPE': mape
    })

    # 7. Fold 결과 출력
    print(f"MAE  : {mae:.4f}")
    print(f"RMSE : {rmse:.4f}")
    print(f"MAPE : {mape:.2f}%")

#%% 📈LightGBM 결과 요약

lgbm_results_df = pd.DataFrame(lgbm_results)

print("\n=== LightGBM Baseline Summary ===")
print(lgbm_results_df)

print("\nAverage")
print(
    lgbm_results_df[
        ['MAE', 'RMSE', 'MAPE']
    ].mean()
)



#%% 📈LightGBM Baseline Summary


# === LightGBM Baseline Summary ===
#    fold       MAE      RMSE      MAPE
# 0     1  0.104201  0.183405  3.974299
# 1     2  0.096800  0.160582  3.637112
# 2     3  0.223453  0.486938  5.306139
# 3     4  0.062250  0.117955  2.108984
# 4     5  0.043063  0.079837  1.565101
# 5     6  0.049141  0.082938  1.970155

# Average
# MAE     0.096485
# RMSE    0.185276
# MAPE    3.093632
# dtype: float64



#%% ♻️Fold별 최소값 확인

#for fold_data in cv_datasets:
#
#    fold_num = fold_data['fold']
#
#    y_valid = fold_data['y_valid']
#
#    print(
#        f"Fold {fold_num} "
#        f"min={y_valid.min():.10f} "
#        f"max={y_valid.max():.4f}"
#    )

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


# -------------------------------------
# LightGBM Baseline 결과 분석 (♻️ 수정 필요)
# -------------------------------------
#
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
# Fold 3 min=0.0000000000 max=188.1000 ♻️
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# -------------------------------------


# %% ♻️Fold 3 이상치 조사
# Fold 3 Validation 구간 최대 사용량 확인

# Fold 3 데이터 추출
#fold3 = cv_datasets[2]

# Validation 원본 데이터
#fold3_df = df_hour.loc[
#    fold3['y_valid'].index
#].copy()
#
# 사용량 내림차순 확인
#print(
#    fold3_df[
#        ['ts', 'kwh_1h']
#    ]
#    .sort_values(
#        'kwh_1h',
#        ascending=False
#    )
#    .head(20)
#)


# %% ♻️데이터 공백 구간(15분 초과 간격) 확인
#df_p15d['time_diff'] = (
#    df_p15d['ts']
#    .diff()
#    .dt.total_seconds()
#    / 60
#)
#
#print(
#    df_p15d[
#        df_p15d['time_diff'] > 15
#    ][
#        ['ts', 'time_diff']
#    ]
#)

# -------------------------------------
# 분석 메모
# -------------------------------------
#
# Fold 3에서 kwh_1h 최대값 188.1 확인
#
# Fold 3 최대값(188.1 kWh) 이상치 원인 분석 완료
# 2026-01-29 17:45 이전에 장시간 데이터 공백(time_diff > 15분) 확인
# time_diff == 15 조건으로 kwh_15m 재생성 후 이상치 제거
# Fold 3 최대값 188.1 → 6.9 kWh로 정상화 확인


# -------------------------------------
# LightGBM Baseline 결과 분석 (♻️ 수정 필요)
# -------------------------------------
#
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
# Fold 3 min=-46.8000000000 ♻️ max=6.9000
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# -------------------------------------


# %% ♻️음수 사용량(kwh_15m < 0) 원인 조사
#
# 음수 사용량 발생 건수
print("음수 건수 :", (df_p15d['kwh_15m'] < 0).sum())
#
# 음수 사용량 전체 확인
#print(
#    df_p15d.loc[
#        df_p15d['kwh_15m'] < 0,
#        [
#            'ts',
#            'time_diff',
#            'kwh_sum',
#            'kwh_15m'
#        ]
#    ]
#)


# %% ♻️ts 중복 확인
#
#dup_ts = df_p15d[
#    df_p15d.duplicated(
#        subset='ts',
#        keep=False
#    )
#]
#
#print("중복 행 수 :", len(dup_ts))
#
#print(
#    dup_ts[
#        ['ts', 'kwh_sum']
#    ]
#    .sort_values('ts')
#)

# -------------------------------------
# 분석 메모
# -------------------------------------
#
# 음수 사용량(kwh_15m < 0) 원인 조사
#
# 동일 ts에 서로 다른 kwh_sum 값이 중복 저장되어 있었음
# kwh_sum은 전체 기간 동안 정상 우상향으로 계량기 리셋 아님
# Fold 3 최소값(-46.8 kWh)은 데이터 중복에 의한 이상치로 판단
# ts 중복 제거 후 kwh_15m 및 df_hour 재생성 필요


# =====================================
# LightGBM Baseline 결과 분석 (♻️ 수정 필요)
# =====================================
#
#  fold      MAE     RMSE     MAPE
#     1 0.095296 0.165802 3.610072e+00
#     2 0.088568 0.154397 3.322567e+14 ♻️
#     3 0.196353 0.401435 3.157398e+15 ♻️
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
# Fold 2 min=0.0000000000 ♻️ max=7.3000
# Fold 3 min=0.0000000000 ♻️ max=6.9000
# Fold 4 min=1.0000000000 max=7.1000
# Fold 5 min=0.9000000000 max=6.7000
# Fold 6 min=1.2000000000 max=6.5000
# =====================================


# ♻️ 수정 필요
# 음수 사용량이 아직까지 나오는 부분 해결


# %% ♻️Fold 2, Fold 3의 0 kWh 발생 시점 확인

#for fold_num in [2, 3]:
#
#    fold = cv_datasets[fold_num - 1]
#
#    fold_df = df_hour.loc[
#        fold['y_valid'].index
#    ].copy()
#
#    zero_df = fold_df[
#        fold_df['kwh_1h'] == 0
#    ]
#
#    print("\n" + "=" * 50)
#    print(f"Fold {fold_num}")
#    print("=" * 50)
#    print("0 kWh 건수 :", len(zero_df))
#
#    print(
#        zero_df[
#            ['ts', 'kwh_1h']
#        ]
#        .sort_values('ts')
#    )


# %% ♻️Fold 3의 0 kWh 구간 원본 15분 데이터 확인

#start_ts = '2026-01-09 04:00:00+09:00'
#end_ts   = '2026-01-09 16:00:00+09:00'

#print(
#    df_p15d[
#        (df_p15d['ts'] >= start_ts)
#        &
#        (df_p15d['ts'] <= end_ts)
#    ][
#        ['ts', 'kwh_sum', 'kwh_15m']
#    ]
#)

# =====================================
# 분석 메모
# =====================================
#
# Fold 2·3의 0 kWh 분석
#
# Fold 2(1건), Fold 3(65건)의 0 kWh 발생 원인을 조사함.
# 일부 시간대는 15분 사용량 데이터가 4개 미만인 상태로
# 1시간 사용량(kwh_1h)이 집계됨.
# 정상적으로 15분 데이터 4개가 존재하는 시간대만 사용하도록
# 전처리를 수정함.
# 재검증 결과 Fold 2·3의 0 kWh 문제가 해소되었으며
# MAPE도 정상 수준으로 안정화됨.


# =====================================
# LightGBM Baseline 결과 분석
# =====================================
#
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
# =====================================





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










#%%
# =====================================
# Baseline Model Comparison
# =====================================

#%% 🔥XGBoost Baseline Training

xgb_results = []
xgb_models = []

print("XGBoost Fold 수 :", len(cv_datasets))

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

    xgb_results.append({

        'fold': fold_num,
        'MAE': mean_absolute_error(y_valid, pred),
        'RMSE': np.sqrt(
            mean_squared_error(y_valid, pred)
        ),
        'MAPE': (
            mean_absolute_percentage_error(
                y_valid,
                pred
            ) * 100
        )

    })


#%% 📈XGBoost 결과 요약

xgb_results_df = pd.DataFrame(xgb_results)

print("\n=== XGBoost Baseline Summary ===")
print(xgb_results_df)

print("\nAverage")
print(xgb_results_df[['MAE','RMSE','MAPE']].mean())

#%% 📈XGBoost Baseline Summary


# === XGBoost Baseline Summary ===
#    fold       MAE      RMSE      MAPE
# 0     1  0.102725  0.178254  3.911719
# 1     2  0.091399  0.159332  3.331666
# 2     3  0.193160  0.407660  4.963964
# 3     4  0.068256  0.126575  2.235854
# 4     5  0.043228  0.076554  1.541570
# 5     6  0.039174  0.065631  1.479487

# Average
# MAE     0.089657
# RMSE    0.169001
# MAPE    2.910710
# dtype: float64

#%% 📈 Baseline Model Comparison

comparison_df = pd.DataFrame({

    'Model': [
        'LightGBM Baseline',
        'XGBoost Baseline'
    ],

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

print("\n")
print("=" * 60)
print("Baseline Model Comparison(Fold 평균치)")
print("=" * 60)

print(
    comparison_df.round(6).to_string(index=False)
)

# MAE 기준 최고 성능 모델
best_model = comparison_df.loc[
    comparison_df['MAE'].idxmin(),
    'Model'
]

best_mae = comparison_df.loc[
    comparison_df['MAE'].idxmin(),
    'MAE'
]

print("\nBest Baseline Model")
print(
    f"{best_model} "
    f"(MAE = {best_mae:.6f})"
)

#%% Baseline Model Comparison
# ---------------
#             Model      MAE     RMSE     MAPE
# LightGBM Baseline 0.096485 0.185276 3.093632
#  XGBoost Baseline 0.089657 0.169001 2.910710

# Best Baseline Model
# XGBoost Baseline (MAE = 0.089657)


#%%
# =====================================
# Feature Reduced Model
# =====================================

#%% 🔥 현재 Feature 목록 확인

print("\n")
print("=" * 60)
print("Current Features")
print("=" * 60)

print(list(X.columns))

print("\nTotal Features :", len(X.columns))

#%% 🔥 Feature Importance용 대표 모델 선택 (마지막 fold)

lgbm_model = lgbm_models[-1]
xgb_model = xgb_models[-1]


#%% 🔥 LightGBM Feature Importance

lgbm_importance = pd.DataFrame({

    'feature': X.columns,
    'importance': lgbm_model.feature_importances_

})

# 중요도 내림차순 정렬
lgbm_importance = lgbm_importance.sort_values(
    by='importance',
    ascending=False
)

# --------------------------
# Top 20
# --------------------------
print("\n")
print("=" * 60)
print("LightGBM Top 20 Features")
print("=" * 60)

print(
    lgbm_importance.head(20)
)



#%% 🔥 LightGBM Feature Importance Ranking

lgbm_importance = pd.DataFrame({

    'Rank': range(
        1,
        len(X.columns) + 1
    ),

    'Feature': lgbm_model.feature_name_,

    'Importance':
    lgbm_model.feature_importances_

})

lgbm_importance = lgbm_importance.sort_values(
    by='Importance',
    ascending=False
).reset_index(drop=True)

# Rank 재부여
lgbm_importance['Rank'] = (
    lgbm_importance.index + 1
)

print("\n=== LightGBM Feature Importance Ranking ===")
print(
    lgbm_importance.to_string(
        index=False
    )
)

#%% 🔥 Importance = 0 Feature

zero_importance = lgbm_importance[
    lgbm_importance['Importance'] == 0
]

print("\n=== LightGBM Importance = 0 Features ===")
print(
    zero_importance.to_string(
        index=False
    )
)

print(
    f"\n총 {len(zero_importance)}개의 Feature가 "
    "Importance = 0 입니다."
)

#%% 🔥 XGBoost Feature Importance Ranking

xgb_importance = pd.DataFrame({

    'Feature': X.columns,

    'Importance':
    xgb_model.feature_importances_

})

# 중요도 내림차순 정렬
xgb_importance = xgb_importance.sort_values(
    by='Importance',
    ascending=False
).reset_index(drop=True)

# Rank 부여
xgb_importance.insert(
    0,
    'Rank',
    xgb_importance.index + 1
)

print("\n=== XGBoost Feature Importance Ranking ===")
print(
    xgb_importance.to_string(
        index=False
    )
)


#%% 🔥 XGBoost Importance = 0 Feature

zero_importance = xgb_importance[
    xgb_importance['Importance'] == 0
]

print("\n=== XGBoost Importance = 0 Features ===")
print(
    zero_importance.to_string(
        index=False
    )
)

print(
    f"\n총 {len(zero_importance)}개의 Feature가 "
    "Importance = 0 입니다."
)

#%% 🔥 XGBoost Bottom 10 Features

print("\n=== XGBoost Bottom 10 Features ===")

print(
    xgb_importance.tail(10).to_string(
        index=False
    )
)






#%% 🔥Feature Selection (Importance 기반 제거)

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

#%% 💾feature set 저장
feature_columns = X_reduced.columns.tolist()

import json

with open("feature_columns.json", "w") as f:
    json.dump(feature_columns, f)

#%% 🔥LightGBM Retrain (Reduced Feature)

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



# XGBoost Retrain (Reduced Feature)


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


#%% 🔥 Reduced Model Comparison

lgbm_red_df = pd.DataFrame(lgbm_reduced_results)
xgb_red_df = pd.DataFrame(xgb_reduced_results)


#%% 🔥LightGBM Reduced
# -----------------------------
print("\n")
print("=" * 60)
print("LightGBM Reduced Model")
print("=" * 60)
print("(Feature Reduction 적용 후)\n")

print(
    lgbm_red_df.to_string(
        index=False
    )
)

print("\nAverage Score")
print(
    lgbm_red_df[
        ['MAE', 'RMSE', 'MAPE']
    ].mean()
)


#%% 🔥XGBoost Reduced
# -----------------------------
print("\n")
print("=" * 60)
print("XGBoost Reduced Model")
print("=" * 60)
print("(Feature Reduction 적용 후)\n")

print(
    xgb_red_df.to_string(
        index=False
    )
)

print("\nAverage Score")
print(
    xgb_red_df[
        ['MAE', 'RMSE', 'MAPE']
    ].mean()
)


#%% 🔥최종 비교
# -----------------------------
comparison_df = pd.DataFrame({

    'Model': [
        'LightGBM Reduced',
        'XGBoost Reduced'
    ],

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

print("\n")
print("=" * 60)
print("Feature Reduced Model Comparison")
print("=" * 60)

print(
    comparison_df.to_string(
        index=False
    )
)

best_model = comparison_df.loc[
    comparison_df['MAE'].idxmin(),
    'Model'
]

best_mae = comparison_df['MAE'].min()

print("\nBest Reduced Model")
print(
    f"{best_model} "
    f"(MAE = {best_mae:.6f})"
)

#%% 📈XGBoost Reduced Model Summary

# XGBoost Reduced Model
# -------------------------
# (Feature Reduction 적용 후)
# 
#  fold      MAE     RMSE     MAPE
#     1 0.092734 0.158413 3.710427
#     2 0.083568 0.147096 3.063510
#     3 0.193475 0.413385 4.922202
#     4 0.078458 0.139611 2.543759
#     5 0.044030 0.072421 1.579560
#     6 0.043266 0.071003 1.615747
# 
# Average Score
# MAE     0.089255
# RMSE    0.166988
# MAPE    2.905867
# dtype: float64


# =====================================
# Reduced XGBoost Hyper Parameter Tuning
# =====================================



#%%
# ============================================================
# XGBoost (Reduced Feature) Optuna
# ============================================================
#%% 🚀FEATURES
FEATURES = X_reduced.columns


#%% 🚀Objective Function
# ============================================================
# 🚀 Objective Function
# ============================================================

def objective(trial):

    params = {

        # -------------------------
        # 기본 설정
        # -------------------------
        "objective": "reg:squarederror",
        "eval_metric": "mae",

        # -------------------------
        # Baseline 주변 탐색
        # Baseline :
        # max_depth = 6
        # lr = 0.05
        # subsample = 0.8
        # colsample = 0.8
        # -------------------------

        "max_depth": trial.suggest_int(
            "max_depth",
            4,
            8
        ),

        "min_child_weight": trial.suggest_int(
            "min_child_weight",
            1,
            8
        ),

        "subsample": trial.suggest_float(
            "subsample",
            0.75,
            1.00
        ),

        "colsample_bytree": trial.suggest_float(
            "colsample_bytree",
            0.75,
            1.00
        ),

        "eta": trial.suggest_float(
            "learning_rate",
            0.03,
            0.07
        ),

        "gamma": trial.suggest_float(
            "gamma",
            0.0,
            2.0
        ),

        "alpha": trial.suggest_float(
            "reg_alpha",
            0.0,
            1.0
        ),

        "lambda": trial.suggest_float(
            "reg_lambda",
            1.0,
            5.0
        ),

        "seed": 42,

        "verbosity": 0
    }

    fold_mae = []


    # ========================================================
    # Walk Forward Validation
    # ========================================================

    for fold in cv_datasets:

        X_train = fold['X_train'][FEATURES]
        y_train = fold['y_train']

        X_valid = fold['X_valid'][FEATURES]
        y_valid = fold['y_valid']

        dtrain = xgb.DMatrix(
            X_train,
            label=y_train
        )

        dvalid = xgb.DMatrix(
            X_valid,
            label=y_valid
        )

        model = xgb.train(

            params=params,

            dtrain=dtrain,

            # 충분히 크게 주고
            # Early Stopping이 자동 결정
            num_boost_round=3000,

            evals=[
                (dvalid, "valid")
            ],

            early_stopping_rounds=100,

            verbose_eval=False

        )

        pred = model.predict(dvalid)

        mae = mean_absolute_error(
            y_valid,
            pred
        )

        fold_mae.append(mae)

    return np.mean(fold_mae)


#%% 🚀Optuna Study
# ============================================================
# 🚀 Optuna Study
# ============================================================

study = optuna.create_study(

    direction="minimize",

    sampler=optuna.samplers.TPESampler(
        seed=42
    )

)

study.optimize(

    objective,

    n_trials=150,

    show_progress_bar=True

)


#%% 🚀Best Result
# ============================================================
# 🚀 Best Result
# ============================================================

print("\n")
print("=" * 60)
print("XGBoost Reduced Feature Optuna")
print("=" * 60)

print(
    f"\nBest MAE : "
    f"{study.best_value:.6f}"
)

print("\nBest Params")

for k, v in study.best_params.items():
    print(
        f"{k:20s} : {v}"
    )

#%% 🚀Best Params 저장
# ============================================================
# 이후 Optuna를 다시 돌리지 않고
# 최적 파라미터를 재사용하기 위함
# ============================================================

import json

with open(
    "best_xgb_reduced_params.json",
    "w"
) as f:

    json.dump(
        study.best_params,
        f,
        indent=4
    )

print("\nBest Parameters 저장 완료")
print("파일명 : best_xgb_reduced_params.json")    

#%% 🔥Best Params 불러오기

import json

with open(
    "best_xgb_reduced_params.json",
    "r"
) as f:

    best_params = json.load(f)

print("\nBest Parameters")
print(best_params)


#%% 📈📈📈(채택!!)XGBoost Reduced Feature Optuna Summary
# ============================================================
# XGBoost Reduced Feature Optuna Summary
# ============================================================

# Best MAE : 0.082424

# Best Params
# max_depth            : 6
# min_child_weight     : 7
# subsample            : 0.9301179450250081
# colsample_bytree     : 0.8232531973601875
# learning_rate        : 0.03131927532096039
# gamma                : 0.0005931471574848002
# reg_alpha            : 0.09366448339517872
# reg_lambda           : 2.2164040594401406



#%%
# =====================================
# Reduced LightGBM Hyper Parameter Tuning
# =====================================


#%% 🚀1. Feature 설정 (Reduced Feature 사용)
FEATURES = X_reduced.columns


#%% 🚀2. Optuna + LightGBM Objective 정의 (Walk-Forward CV)

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
    # 평균 MAE 반환
    # ============================================================
    return np.mean(fold_mae)


#%% 🚀4. Optuna Study 실행 (50 trials)

study = optuna.create_study(direction="minimize")

study.optimize(
    objective,
    n_trials=50
)


#%% 🚀5. 최종 결과 출력
print("\nBest MAE:", study.best_value)

print("\nBest Params:")
print(study.best_params)

#%% 🚀6. Best Params 저장
# ============================================================

import json

with open(
    "best_lgbm_reduced_params.json",
    "w"
) as f:

    json.dump(
        study.best_params,
        f,
        indent=4
    )

print("\nBest Parameters 저장 완료")
print(
    "파일명 : "
    "best_lgbm_reduced_params.json"
)

#%% 🔥Best Params 불러오기

import json

with open(
    "best_lgbm_reduced_params.json",
    "r"
) as f:

    best_params = json.load(f)

print("\nBest Parameters")
print(best_params)


#%% 📈 LightGBM Reduced Feature Optuna Summary

# ============================================================
# LightGBM Reduced Feature Optuna Summary
# ============================================================

# Best MAE : 0.085645

# Best Params
# num_leaves          : 76
# max_depth           : 8
# min_data_in_leaf    : 19
# feature_fraction    : 0.8121774778639154
# bagging_fraction    : 0.7488290805954028
# bagging_freq        : 2
# learning_rate       : 0.024749383011002223
# lambda_l1           : 0.2270636670030471
# lambda_l2           : 2.9027933806035042


#%% 

# =====================================
# Final XGBoost Model Training
# =====================================


#%% 🔥 Final XGBoost Model Training
# ============================================================
# Reduced Feature + Optuna Best Parameter
# 전체 데이터로 최종 모델 생성
# ============================================================

FINAL_FEATURES = X_reduced.columns

X_final = X_reduced.copy()
y_final = y.copy()

final_xgb_model = XGBRegressor(

    objective='reg:squarederror',

    n_estimators=1000,
    learning_rate=0.03131927532096039,

    max_depth=6,
    min_child_weight=7,

    subsample=0.9301179450250081,
    colsample_bytree=0.8232531973601875,

    gamma=0.0005931471574848002,
    reg_alpha=0.09366448339517872,
    reg_lambda=2.2164040594401406,

    random_state=42,
    n_jobs=-1
)

final_xgb_model.fit(
    X_final,
    y_final
)

print("\n")
print("=" * 60)
print("Final XGBoost Model Training Complete")
print("=" * 60)
print(f"Feature Count : {len(FINAL_FEATURES)}")
print(f"Training Data : {X_final.shape}")


#%% 🔥 최종 모델 저장 (XGBoost Reduced + Optuna)

# ----------------------------------------
# Optuna 최적 파라미터
# ----------------------------------------
best_params = {

    "objective": "reg:squarederror",

    "max_depth": 6,
    "min_child_weight": 7,

    "subsample": 0.9301179450250081,
    "colsample_bytree": 0.8232531973601875,

    "learning_rate": 0.03131927532096039,

    "gamma": 0.0005931471574848002,
    "reg_alpha": 0.09366448339517872,
    "reg_lambda": 2.2164040594401406,

    "n_estimators": 1000,

    "random_state": 42,
    "n_jobs": -1
}


# ----------------------------------------
# Reduced Feature 전체 데이터 학습
# ----------------------------------------
final_model = XGBRegressor(
    **best_params
)

final_model.fit(
    X_reduced,
    y
)


# ----------------------------------------
# 모델 저장
# ----------------------------------------
joblib.dump(
    final_model,
    "xgb_reduced_optuna.pkl"
)

# ----------------------------------------
# Feature 목록도 함께 저장
# (추후 Recursive Forecast에서 반드시 필요)
# ----------------------------------------
joblib.dump(
    list(X_reduced.columns),
    "xgb_reduced_features.pkl"
)

print("\n")
print("=" * 60)
print("Final Model Save Complete")
print("=" * 60)
print("Model File   : xgb_reduced_optuna.pkl")
print("Feature File : xgb_reduced_features.pkl")




#%% 

# =====================================
# Recursive Forecast Function
# =====================================


#%% 🔥컬럼 확인
print(X_reduced.columns.tolist())



#%% 🔥API
SERVICE_KEY = "3051400f79d73b21ca9410905793c769eef55c17cb2e4e5e4579a4638d923dc1"

def get_forecast_temperature():

    url = (
        "http://apis.data.go.kr/"
        "1360000/"
        "VilageFcstInfoService_2.0/"
        "getVilageFcst"
    )

    params = {

        "serviceKey": SERVICE_KEY,

        "pageNo": "1",

        "numOfRows": "500",

        "dataType": "JSON",

        # 예시
        "base_date": "20260608",
        "base_time": "0500",

        # 광주
        "nx": "58",
        "ny": "74"
    }

    response = requests.get(
        url,
        params=params
    )

    items = response.json()[
        "response"
    ][
        "body"
    ][
        "items"
    ][
        "item"
    ]

    temp_list = []

    for item in items:

        if item["category"] == "TMP":

            dt = pd.to_datetime(

                item["fcstDate"]
                +
                item["fcstTime"],

                format="%Y%m%d%H%M"

            )

            temp_list.append({

                "ts": dt,

                "forecast_temp":
                float(
                    item["fcstValue"]
                )

            })

    return pd.DataFrame(
        temp_list
    )
#%% 🔥API 호출 확인
forecast_temp_df = get_forecast_temperature()

print(
    forecast_temp_df.head()
)



#%% 🔥Recursive Forecast (24시간)

# Final XGBoost Model 전용
# X_reduced.columns 기준


def recursive_forecast_24h(
    model,
    history_df,
    feature_cols,
    forecast_temp_df
):

    future_preds = []

    temp_df = history_df.copy()

    kr_holidays = holidays.KR()

    for step in range(24):

        # ==================================================
        # 다음 시점
        # ==================================================
        next_ts = (
            temp_df.iloc[-1]["ts"]
            + pd.Timedelta(hours=1)
        )

        row = {}

        row["ts"] = next_ts
        row["date"] = next_ts.date()

        # ==================================================
        # Calendar Feature
        # ==================================================
        row["hour"] = next_ts.hour
        row["weekday"] = next_ts.weekday()

        row["is_weekend"] = int(
            row["weekday"] >= 5
        )

        row["is_holiday"] = int(
            row["date"] in kr_holidays
        )

        row["month"] = next_ts.month

        # ==================================================
        # Temperature Feature
        # ==================================================

        forecast_row = forecast_temp_df[
            forecast_temp_df["ts"] == next_ts
        ]

        if not forecast_row.empty:

            avg_temp = (
                forecast_row[
                    "forecast_temp"
                ].values[0]
            )

        else:

            # API 값이 없으면 직전 값 사용
            avg_temp = (
                temp_df["avg_temp"]
                .iloc[-1]
            )

        row["avg_temp"] = avg_temp
        row["daily_min_temp"] = avg_temp

        row["is_hot"] = int(
            avg_temp >= 28
        )

        row["is_cold"] = int(
            avg_temp <= 5
        )

        row["is_very_cold"] = int(
            avg_temp <= 0
        )

        row["is_extreme_cold"] = int(
            avg_temp <= -3
        )

        row["temp_diff_prev_day"] = (
            avg_temp
            - temp_df.iloc[-24]["avg_temp"]
        )

        row["is_temp_drop_5"] = int(
            row["temp_diff_prev_day"] <= -5
        )

        row["cooling_degree"] = max(
            avg_temp - 24,
            0
        )

        row["heating_degree"] = max(
            18 - avg_temp,
            0
        )

        # ==================================================
        # Lag Feature
        # ==================================================
        row["lag_1"] = (
            temp_df.iloc[-1]["kwh_1h"]
        )

        row["lag_24"] = (
            temp_df.iloc[-24]["kwh_1h"]
        )

        row["lag_168"] = (
            temp_df.iloc[-168]["kwh_1h"]
        )

        # ==================================================
        # Rolling Feature
        # ==================================================
        row["rolling_mean_3"] = (
            temp_df["kwh_1h"]
            .tail(3)
            .mean()
        )

        row["rolling_mean_6"] = (
            temp_df["kwh_1h"]
            .tail(6)
            .mean()
        )

        row["rolling_mean_24"] = (
            temp_df["kwh_1h"]
            .tail(24)
            .mean()
        )

        row["rolling_max_24"] = (
            temp_df["kwh_1h"]
            .tail(24)
            .max()
        )

        row["rolling_min_24"] = (
            temp_df["kwh_1h"]
            .tail(24)
            .min()
        )

        # ==================================================
        # Diff Feature
        # ==================================================
        row["diff_1"] = (
            temp_df.iloc[-1]["kwh_1h"]
            - temp_df.iloc[-2]["kwh_1h"]
        )

        row["diff_24"] = (
            temp_df.iloc[-1]["kwh_1h"]
            - temp_df.iloc[-24]["kwh_1h"]
        )

        row["diff_168"] = (
            temp_df.iloc[-1]["kwh_1h"]
            - temp_df.iloc[-168]["kwh_1h"]
        )

        # ==================================================
        # Predict
        # ==================================================
        X_pred = pd.DataFrame(
            [row]
        )[feature_cols]

        pred = model.predict(
            X_pred
        )[0]

        row["kwh_1h"] = pred

        future_preds.append(row)

        # ==================================================
        # 다음 예측을 위해 append
        # ==================================================
        temp_df = pd.concat(
            [
                temp_df,
                pd.DataFrame([row])
            ],
            ignore_index=True
        )

    return pd.DataFrame(
        future_preds
    )


#%% 🔥 실행

future_24h = recursive_forecast_24h(
    model=final_model,
    history_df=df_hour,
    feature_cols=X_reduced.columns,
    forecast_temp_df=forecast_temp_df
)

print(
    future_24h[
        ["ts", "kwh_1h"]
    ]
)


#%% 🔥예측 결과 시각화

plt.figure(figsize=(12,5))

plt.plot(
    future_24h["ts"],
    future_24h["kwh_1h"],
    marker="o"
)

plt.title(
    "Next 24 Hours Power Forecast"
)

plt.xlabel("Time")
plt.ylabel("kWh")

plt.grid(True)

plt.xticks(rotation=45)

plt.tight_layout()

plt.show()


#%% 📈 마지막 24시간 Actual vs Prediction

# 마지막 24시간

X_last = X_reduced.iloc[-24:]
y_last = y.iloc[-24:]

# 예측

y_pred = final_model.predict(X_last)

plt.figure(figsize=(12,5))

plt.plot(
    range(24),
    y_last.values,
    marker='o',
    label='Actual'
)

plt.plot(
    range(24),
    y_pred,
    marker='s',
    label='Prediction'
)

plt.title(
    'Last 24 Hours Actual vs Prediction'
)

plt.xlabel('Hour')
plt.ylabel('kWh')

plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()





#%% 📈v2 한계점 및 개선 필요 사항
# ============================================================
# v2 한계점 및 개선 필요 사항
# ============================================================

# 1.
# 최종 XGBoost 모델은 Walk-Forward Validation에서
# MAE 약 0.082 수준으로 우수한 성능을 확인함

# 2.
# Fold 6 Validation 차트에서는
# Actual과 Prediction이 거의 겹치는 수준으로
# 검증 데이터에 대한 예측 성능이 양호함

# 3.
# 그러나 실제 운영을 가정한
# 24시간 Recursive Forecast 수행 시
# 예측값이 점차 감소하는 현상이 발생함

# 4.
# 원인으로는 lag / rolling / diff Feature가
# 이전 예측값을 다시 입력받는 구조이므로
# 예측 오차가 누적되는 문제가 존재함

# 5.
# 특히 lag_1, rolling_mean, diff 계열 Feature는
# Recursive Forecast 과정에서
# 실제값이 아닌 예측값으로 대체되므로
# 장기 예측 시 오차 전파(Error Propagation)가 발생함

# 6.
# 결과적으로 Validation 성능은 우수하였으나
# 24시간 이상 미래 예측에서는
# 사용량 패턴이 점차 평균값 방향으로 수렴하는 현상을 확인함

# 7.
# 따라서 v3에서는
# Recursive Forecast 의존도를 줄이고
# 미래 24시간을 직접 예측하는
# Multi-Step Forecast 기반 딥러닝 모델(LSTM)을 검토함




# %% 