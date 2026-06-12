# =====================================
# 🎉 energy planner project 🎉
# =====================================
# 개발 환경
# Python 3.14 (64 bit)
# XGBoost Direct Multi-Step Forecast
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


#%% 💾Feature Engineering 결과 저장 

df_hour.to_csv(
    'df_hour_v2.csv',
    index=False,
    encoding='utf-8-sig'
)

print("저장 완료 : df_hour_v2.csv")


# ♻️ 수정필요 >>> 볼 수 있는 형태로 변수들 저장


#%% ✨Direct Multi-Step Target 생성

# 1시간 후 ~ 24시간 후

for h in range(1, 25):

    df_hour[f"target_h{h}"] = (
        df_hour["kwh_1h"]
        .shift(-h)
    )

print(
    df_hour[
        [
            "kwh_1h",
            "target_h1",
            "target_h24"
        ]
    ].head()
)
#%% 🔥Target NaN 제거

print("제거 전 :", df_hour.shape)

df_hour = df_hour.dropna().reset_index(
    drop=True
)

print("제거 후 :", df_hour.shape)
#%% 🔥컬럼 확인

print(df_hour.columns.tolist())

print(
    f"\nColumn Count : {len(df_hour.columns)}"
)

#%%
# =====================================
# Walk-Forward Valid 만들기
# =====================================

#%% 🔥Walk-Forward 전 필수 점검 / shape (6051, 61)
print(df_hour.shape)

print(df_hour.isnull().sum())


#%% 🔥Feature / Target 분리

TARGET_COLS = [

    f'target_h{i}'
    for i in range(1, 25)

]

X = df_hour.drop(

    columns=[

        'ts',
        'date',
        'kwh_1h'

    ] + TARGET_COLS

)

Y = df_hour[TARGET_COLS]

print("X shape :", X.shape)
print("Y shape :", Y.shape)

print("\nTarget Columns")

print(TARGET_COLS)


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

for fold_num, (

    (train_start, train_end),
    (valid_start, valid_end)

) in enumerate(

    folds,
    start=1

):

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

    X_train = X.loc[train_mask]
    Y_train = Y.loc[train_mask]

    X_valid = X.loc[valid_mask]
    Y_valid = Y.loc[valid_mask]

    cv_datasets.append({

        'fold': fold_num,

        'X_train': X_train,
        'Y_train': Y_train,

        'X_valid': X_valid,
        'Y_valid': Y_valid

    })

    print(
        f'Fold {fold_num} | '
        f'X_train {X_train.shape} | '
        f'Y_train {Y_train.shape} | '
        f'X_valid {X_valid.shape} | '
        f'Y_valid {Y_valid.shape}'
    )
#%%
# =====================================
# XGBoost Direct Multi-Step Optuna
# =====================================

#%% 🔥Reduced Feature 불러오기

import json

with open(
    "feature_columns.json",
    "r"
) as f:

    reduced_features = json.load(f)

print(
    f"Reduced Feature Count : "
    f"{len(reduced_features)}"
)

print(reduced_features[:10])


#%% 🔥Optuna Objective
def objective(trial):

    params = {

        'objective': 'reg:squarederror',

        'n_estimators': trial.suggest_int(
            'n_estimators',
            300,
            1000
        ),

        'learning_rate': trial.suggest_float(
            'learning_rate',
            0.01,
            0.1,
            log=True
        ),

        'max_depth': trial.suggest_int(
            'max_depth',
            3,
            10
        ),

        'min_child_weight': trial.suggest_int(
            'min_child_weight',
            1,
            10
        ),

        'subsample': trial.suggest_float(
            'subsample',
            0.6,
            1.0
        ),

        'colsample_bytree': trial.suggest_float(
            'colsample_bytree',
            0.6,
            1.0
        ),

        'gamma': trial.suggest_float(
            'gamma',
            1e-5,
            1.0,
            log=True
        ),

        'reg_alpha': trial.suggest_float(
            'reg_alpha',
            1e-5,
            10.0,
            log=True
        ),

        'reg_lambda': trial.suggest_float(
            'reg_lambda',
            1e-5,
            10.0,
            log=True
        ),

        'random_state': 42,
        'n_jobs': -1,
        'verbosity': 0
    }

    fold_mae = []

    for fold_data in cv_datasets:

        X_train = (
            fold_data['X_train']
            [reduced_features]
        )

        X_valid = (
            fold_data['X_valid']
            [reduced_features]
        )

        y_train = (
            fold_data['Y_train']
            ['target_h1']
        )

        y_valid = (
            fold_data['Y_valid']
            ['target_h1']
        )

        model = XGBRegressor(
            **params
        )

        model.fit(
            X_train,
            y_train
        )

        pred = model.predict(
            X_valid
        )

        mae = mean_absolute_error(
            y_valid,
            pred
        )

        fold_mae.append(mae)

    return np.mean(
        fold_mae
    )

#%% 🚀 Optuna Study 생성
study = optuna.create_study(
    direction='minimize'
)

study.optimize(
    objective,
    n_trials=30
)


#%% 📈 Best Result

print(
    "Best MAE :",
    study.best_value
)

print(
    "\nBest Parameters"
)

print(
    study.best_params
)

#%% 📈성능 결과
# =====================================
# Direct Multi-Step (H1) Optuna 결과
# =====================================
#
# 목적:
# 기존 XGBoost 파라미터가 Recursive Forecast 기반에서
# 도출된 값이므로, Direct Multi-Step 환경에 맞는
# 최적 파라미터를 탐색하기 위해 Optuna 수행
#
# 설정:
# - Target : target_h1 (1시간 후 예측)
# - Validation : Walk-Forward CV (6 Fold)
# - Metric : MAE
# - Trial : 30
#
# 결과:
# Best MAE = 0.40248
#
# Best Parameters
# n_estimators      = 598
# learning_rate     = 0.014686
# max_depth         = 7
# min_child_weight  = 9
# subsample         = 0.9202
# colsample_bytree  = 0.6523
# gamma             = 0.000214
# reg_alpha         = 0.000022
# reg_lambda        = 0.2524

#%% 💾 Best Params 저장

import json

with open(
    "best_xgb_direct_h1_params.json",
    "w"
) as f:

    json.dump(
        study.best_params,
        f,
        indent=4
    )

print(
    "저장 완료 : best_xgb_direct_h1_params.json"
)
#%% 🚀 XGBoost Direct Multi-Step Validation
# (H1 Optuna Params)

direct_results = []

for fold_data in cv_datasets:

    fold_num = fold_data['fold']

    X_train = (
        fold_data['X_train']
        [reduced_features]
    )
    Y_train = fold_data['Y_train']

    X_valid = (
        fold_data['X_valid']
        [reduced_features]
    )
    Y_valid = fold_data['Y_valid']

    horizon_mae = []
    horizon_rmse = []
    horizon_mape = []

    pred_matrix = []

    # ---------------------------------
    # H1 ~ H24
    # ---------------------------------

    for h in range(1, 25):

        target_col = f'target_h{h}'

        y_train = Y_train[target_col]
        y_valid = Y_valid[target_col]

        model = XGBRegressor(

            objective='reg:squarederror',

            n_estimators=598,

            learning_rate=0.014686336978859488,

            max_depth=7,
            min_child_weight=9,

            subsample=0.9202001813191045,
            colsample_bytree=0.6523365353150619,

            gamma=0.00021407784245415902,
            reg_alpha=2.173741284481131e-05,
            reg_lambda=0.252406980643,

            random_state=42,
            n_jobs=-1
        )

        model.fit(
            X_train,
            y_train
        )

        pred = model.predict(
            X_valid
        )

        pred_matrix.append(pred)



        mae = mean_absolute_error(
            y_valid,
            pred
        )

        rmse = np.sqrt(
            mean_squared_error(
                y_valid,
                pred
            )
        )

        mape = (
            mean_absolute_percentage_error(
                y_valid,
                pred
            ) * 100
        )

        horizon_mae.append(mae)
        horizon_rmse.append(rmse)
        horizon_mape.append(mape)

    pred_matrix = np.array(
            pred_matrix
        ).T        

    true_matrix = Y_valid.values

    peak_true = np.max(
        true_matrix,
        axis=1
    )

    peak_pred = np.max(
        pred_matrix,
        axis=1
    )

    peak_mae = np.mean(
        np.abs(
            peak_true -
            peak_pred
        )
    )

    peak_hour_true = np.argmax(
        true_matrix,
        axis=1
    )

    peak_hour_pred = np.argmax(
        pred_matrix,
        axis=1
    )

    peak_time_error = np.mean(
        np.abs(
            peak_hour_true -
            peak_hour_pred
        )
    )

    direct_results.append({

        'fold': fold_num,

        'MAE': np.mean(horizon_mae),
        'RMSE': np.mean(horizon_rmse),
        'MAPE': np.mean(horizon_mape),

        'Peak_MAE': peak_mae,
        'Peak_Time_Error': peak_time_error

    })

results_df = pd.DataFrame(
    direct_results
)

print(results_df)

print("\n===== CV Mean =====")

print(
    results_df[
        [
            'MAE',
            'RMSE',
            'MAPE',
            'Peak_MAE',
            'Peak_Time_Error'
        ]
    ].mean()
)

#%% 📈성능평가
# =====================================
# Direct Multi-Step Validation
# H1 Optuna Parameter 적용 결과
# =====================================
#   fold       MAE      RMSE       MAPE  Peak_MAE  Peak_Time_Error
#0     1  0.697593  0.938355  34.077351  0.901552         4.847042
#1     2  0.567919  0.823703  24.734092  0.789615         4.270195
#2     3  1.234638  1.708697  55.543423  1.578527         7.843505
#3     4  1.036002  1.371316  43.592206  1.305189         5.608629
#4     5  0.763123  1.012938  32.812555  0.927015         4.712899
#5     6  0.690974  0.956986  32.397880  0.749551         3.795527

#===== CV Mean =====
#MAE                 0.831708
#RMSE                1.135333
#MAPE               37.192918
#Peak_MAE            1.041908
#Peak_Time_Error     5.179633
#dtype: float64