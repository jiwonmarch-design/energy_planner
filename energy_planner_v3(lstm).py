# =====================================
# 🎉 energy planner project 🎉
# =====================================
# [개발 환경 분리 안내]
#
# energy_planner_v2.py
#   - Python 3.14
#   - LightGBM / XGBoost 기반 머신러닝 최종 버전
#   - 최종 성능 모델(MAE ≈ 0.08645) 보존 목적
#
# energy_planner_v3.py
#   - Python 3.12 (venv312)
#   - PyTorch 기반 LSTM 개발 버전
#   - 딥러닝 실험 및 성능 비교 목적
#
# 주의사항
# - v2와 v3는 같은 프로젝트 폴더에 존재한다.
# - 폴더가 아니라 실행하는 Python Interpreter가
#   Python 버전을 결정한다.
# - v2는 Python 3.14 환경에서 실행한다.
# - v3는 venv312(Python 3.12) 환경에서 실행한다.
# - v2 코드는 수정하지 않고 최종 결과를 보존한다.
# - v3에서 LSTM, GRU 등 딥러닝 모델을 개발한다.
#
# 실행 예시
#
# [v2 실행]
# Python 3.14
# > python energy_planner_v2.py
#
# [v3 실행]
# venv312 활성화
# > venv312\Scripts\activate
# > python energy_planner_v3.py
#
# 최종 목표
# LightGBM / XGBoost / LSTM / GRU 성능 비교
# ============================================================



#%% 🔥라이브러리

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

import holidays

import torch
import torch.nn as nn

from sklearn.preprocessing import MinMaxScaler

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    mean_absolute_percentage_error
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
    X_train = X_reduced.loc[train_mask]
    y_train = y.loc[train_mask]

    X_valid = X_reduced.loc[valid_mask]
    y_valid = y.loc[valid_mask]

    cv_datasets.append({

        'fold': fold_num,

        'X_train': X_train,
        'y_train': y_train,

        'X_valid': X_valid,
        'y_valid': y_valid

    })

print("생성된 Fold 수 :", len(cv_datasets))

print(X_train.shape)
print(X_valid.shape)

#%%
# =====================================
# LSTM Input Data Preparation
# =====================================


#%% 🔥MinMax Scaling


scaler = MinMaxScaler()

X_train_scaled = scaler.fit_transform(
    X_train
)

X_valid_scaled = scaler.transform(
    X_valid
)

print(X_train_scaled.shape)
print(X_valid_scaled.shape)



#%% 🔥LSTM Sequence 생성 함수

def create_sequences(X, y, seq_len=24):

    X_seq = []
    y_seq = []

    for i in range(seq_len, len(X)):

        X_seq.append(
            X[i-seq_len:i]
        )

        y_seq.append(
            y.iloc[i]
        )

    return (
        np.array(X_seq),
        np.array(y_seq)
    )
#%% 🔥Sequence 생성

X_train_seq, y_train_seq = create_sequences(
    X_train_scaled,
    y_train,
    seq_len=24
)

X_valid_seq, y_valid_seq = create_sequences(
    X_valid_scaled,
    y_valid,
    seq_len=24
)

print(X_train_seq.shape)
print(X_valid_seq.shape)

#%% 🔥LSTM 모델 (PyTorch)

class LSTMModel(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=64,
        num_layers=1
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )

        self.fc1 = nn.Linear(
            hidden_size,
            32
        )

        self.relu = nn.ReLU()

        self.fc2 = nn.Linear(
            32,
            1
        )

    def forward(self, x):

        # x shape
        # (batch, seq_len, feature)

        lstm_out, _ = self.lstm(x)

        # 마지막 시점 출력 사용
        out = lstm_out[:, -1, :]

        out = self.fc1(out)

        out = self.relu(out)

        out = self.fc2(out)

        return out


# 모델 생성
input_size = X_train_seq.shape[2]

model = LSTMModel(
    input_size=input_size,
    hidden_size=64
)

print(model)


#%% 🔥Tensor 변환


X_train_tensor = torch.tensor(
    X_train_seq,
    dtype=torch.float32
)

y_train_tensor = torch.tensor(
    y_train_seq,
    dtype=torch.float32
).reshape(-1, 1)

X_valid_tensor = torch.tensor(
    X_valid_seq,
    dtype=torch.float32
)

y_valid_tensor = torch.tensor(
    y_valid_seq,
    dtype=torch.float32
).reshape(-1, 1)

print(X_train_tensor.shape)
print(y_train_tensor.shape)

#%% 🔥DataLoader 생성


from torch.utils.data import (
    TensorDataset,
    DataLoader
)

train_dataset = TensorDataset(
    X_train_tensor,
    y_train_tensor
)

valid_dataset = TensorDataset(
    X_valid_tensor,
    y_valid_tensor
)

train_loader = DataLoader(
    train_dataset,
    batch_size=32,
    shuffle=True
)

valid_loader = DataLoader(
    valid_dataset,
    batch_size=32,
    shuffle=False
)

print("Train Batch 수 :", len(train_loader))
print("Valid Batch 수 :", len(valid_loader))
#%% 🔥Loss / Optimizer

criterion = nn.L1Loss()

optimizer = torch.optim.Adam(
    model.parameters(),
    lr=0.001
)

print(criterion)
print(optimizer)





#%%
# =====================================
# LSTM Training
# =====================================

#%% 🔥Training Loop

epochs = 50

train_losses = []
valid_maes = []
#%% 🔥Epoch Training

for epoch in range(epochs):

    # --------------------------
    # Train
    # --------------------------
    model.train()

    train_loss = 0

    for X_batch, y_batch in train_loader:

        optimizer.zero_grad()

        pred = model(X_batch)

        loss = criterion(
            pred,
            y_batch
        )

        loss.backward()

        optimizer.step()

        train_loss += loss.item()

    train_loss /= len(train_loader)

    train_losses.append(train_loss)

    # --------------------------
    # Validation
    # --------------------------
    model.eval()

    with torch.no_grad():

        pred_valid = model(
            X_valid_tensor
        )

    pred_np = (
        pred_valid
        .numpy()
        .flatten()
    )

    valid_mae = mean_absolute_error(
        y_valid_seq,
        pred_np
    )

    valid_maes.append(valid_mae)

    print(
        f"Epoch [{epoch+1}/{epochs}] "
        f"| Train MAE: {train_loss:.4f} "
        f"| Valid MAE: {valid_mae:.4f}"
    )

#%% 📈 Learning Curve

plt.figure(figsize=(10, 5))

plt.plot(
    train_losses,
    label='Train MAE'
)

plt.plot(
    valid_maes,
    label='Valid MAE'
)

plt.xlabel('Epoch')
plt.ylabel('MAE')

plt.title(
    'LSTM Learning Curve'
)

plt.legend()

plt.grid()

plt.show()

#%% 🔥Best Epoch

best_epoch = np.argmin(valid_maes) + 1

best_mae = min(valid_maes)

print(
    f"Best Epoch : {best_epoch}"
)

print(
    f"Best Validation MAE : {best_mae:.4f}"
)
#%% 🔥LSTM 모델 저장

torch.save(
    model.state_dict(),
    "lstm_fold6.pt"
)

print("모델 저장 완료")

#%% 📈LSTM 실험 결과 고찰
#
# [실험 목적]
#
# Drift 문제 해결 가능성을 검토하기 위해
# 시계열 패턴 학습에 강점을 가진
# LSTM 모델을 구축하여 성능을 비교하였다.
#
#
# [실험 결과]
#
# LightGBM MAE ≈ 0.086
# LSTM MAE ≈ 0.363 (Best Epoch = 23)
#
#
# [해석]
#
# LSTM은 정상적으로 학습되었으나
# Validation 성능은 LightGBM보다 크게 낮았다.
#
# 이는 현재 데이터에서
# Lag / Rolling / Diff 기반 Feature Engineering이
# 매우 효과적으로 작동하고 있음을 의미한다.
#
#
# [시사점]
#
# Drift의 원인이
# 모델 구조의 한계 때문일 가능성은 낮다.
#
# 오히려 결측치, 계절 변화,
# 기상 변수 부족 등의 영향이
# 더 클 가능성이 있다.
#
#
# [향후 개선 방향]
#
# 1. 전체 Fold 기반 LSTM 평가
# 2. GRU 모델 비교
# 3. Trend / Seasonality Feature 추가
# 4. 기상 예보 데이터 활용
#
#
# [결론]
#
# LSTM 실험은 실패가 아니라
# Drift 원인을 좁혀나가는 검증 과정이다.
#
# 현재까지는 Feature Engineering 기반
# LightGBM이 가장 우수한 모델로 확인되었다.
#
# ============================================================

