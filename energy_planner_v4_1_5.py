# =====================================
# 🎉 energy planner project 🎉
# =====================================
#
# energy_planner_v4_1_3.py
# GRU 기반 전력 사용량 예측 모델
# XGBoost Direct Multi-Step Forecast와 비교하기 위한
# Deep Learning Multi-Step Forecast 실험 버전
#
# XGBoost Recursive Forecast의 오차 누적 문제를 개선하고
# 장기 시계열 패턴 학습 및 24시간 동시 예측 성능 향상을 목적으로 개발
#

# [개발 환경 분리 안내]

# [v4_1_3 실행]
# venv312 활성화
# > venv312\Scripts\activate
# > python energy_planner_v4_1_3.py

# -------------------------------------
# Version : v4_1_5
# -------------------------------------
# GRU Direct Multi-Step Forecast
#
# Forecast Horizon
# → Future 24 Hours
#
# Input Sequence
# → Lookback 168 Hours (7 Days)
#
# Feature Set
# → feature_columns.json
# → v2_2_6과 동일 Reduced Feature 사용
#
# Validation
# → Walk-Forward CV (6 Fold)
#
# Model
# → GRU
# → hidden_size = 256
# → num_layers = 3
# → dropout = 0.2
#
# Training
# → Validation Early Stopping 적용
# → patience = 5
# → Epoch 최대 30
#
# Validation Result
# → Train MAE = 0.6839
# → MAE       = 0.7893
# → RMSE      = 1.2158
# → MAPE      = 32.09%
#
# Peak Prediction
# → Peak MAE        = 1.1177
# → Peak Time Error = 5.37 h
#
# 특징
# → Direct Multi-Step Forecast
# → 24시간 미래값 동시 예측
# → Reduced Feature Set 기반
# → Validation Early Stopping 적용
# → Hidden Size 확장 (128 → 256)
# → GRU Layer 증가 (2 → 3)
# → Dropout 0.2 추가
# → 과적합 모니터링 가능
# → v2_2_6(XGBoost) 비교 실험 버전
#
# v4_1_4 비교
# → Train MAE
# v4_1_4 : 0.6567
# v4_1_5 : 0.6839
#
# → MAE
# v4_1_4 : 0.7788
# v4_1_5 : 0.7893
#
# → RMSE
# v4_1_4 : 1.2314
# v4_1_5 : 1.2158
#
# → MAPE
# v4_1_4 : 29.99%
# v4_1_5 : 32.09%
#
# → Peak MAE
# v4_1_4 : 1.1983
# v4_1_5 : 1.1177
#
# → Peak Time Error
# v4_1_4 : 5.62 h
# v4_1_5 : 5.37 h
#
# 해석
# → Dropout 적용으로
# Train MAE가 증가하여
# 과적합이 추가로 완화됨
#
# → RMSE 개선
# 1.2314 → 1.2158
#
# → Peak MAE 개선
# 1.1983 → 1.1177
#
# → Peak Time Error 개선
# 5.62 h → 5.37 h
#
# → 반면 MAE와 MAPE는
# 소폭 악화됨
#
# → Fold 3(2026-01)는 여전히
# 가장 어려운 구간으로 확인됨
#
# → Dropout 적용 효과로
# 예측 안정성은 향상되었으나
# 평균 오차는 소폭 증가
#
# v2_2_6 비교
# → Train MAE
# XGBoost : 0.2311
# GRU     : 0.6839
#
# → MAE
# XGBoost : 0.8153
# GRU     : 0.7893
#
# → RMSE
# XGBoost : 1.1466
# GRU     : 1.2158
#
# → MAPE
# XGBoost : 36.12%
# GRU     : 32.09%
#
# → Peak MAE
# XGBoost : 0.9780
# GRU     : 1.1177
#
# 종합 평가
# → 평균 오차(MAE)는
# 여전히 GRU가 우세
#
# → Peak 예측 성능은
# v4_1_4 대비 개선
#
# → RMSE 역시 개선됨
#
# → 현재 v4_1_4와 함께
# 가장 경쟁력 있는 GRU 모델
#
# → 정확도 중심이라면 v4_1_4
# → 안정성 중심이라면 v4_1_5
#
# 향후 개선 후보
# → Learning Rate Scheduler
# → Bidirectional GRU
# → Attention 기반 모델
# → TFT 비교 실험
# → TimesFM 비교 실험
# -------------------------------------

# ============================================================

#%% 🔥라이브러리
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


import holidays

import joblib
import requests
import copy


from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    mean_absolute_percentage_error
)

from sklearn.metrics import (
    mean_absolute_error
)

from sklearn.preprocessing import (
    StandardScaler
)

import torch
import torch.nn as nn

from torch.utils.data import (
    Dataset,
    DataLoader
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
            'cooling_degree',
            'heating_degree'
        ]
    ].head()
)

#%% ♻️Cyclical Feature
# 동일 feature set 비교를 위해 보류
#df_hour['hour_sin'] = np.sin(
#    2 * np.pi * df_hour['hour'] / 24
#)

#df_hour['hour_cos'] = np.cos(
#    2 * np.pi * df_hour['hour'] / 24
#)

#df_hour['weekday_sin'] = np.sin(
#    2 * np.pi * df_hour['weekday'] / 7
#)

#df_hour['weekday_cos'] = np.cos(
#    2 * np.pi * df_hour['weekday'] / 7
#)


#%% 💾Feature Engineering 결과 저장 

df_hour.to_csv(
    'df_hour_v4.csv',
    index=False,
    encoding='utf-8-sig'
)
print(df_hour.shape)
print(df_hour.columns)
print("저장 완료 : df_hour_v4.csv")

#%%
# =====================================
# Feature Selection
# =====================================
#%% 🔥FEATURES

import json

with open("feature_columns.json", "r") as f:
    FEATURES = json.load(f)

print(f"Feature 개수: {len(FEATURES)}")

TARGET = 'kwh_1h'

#%% 🔥결측 제거
df_hour = df_hour.dropna().reset_index(drop=True)

print(df_hour.shape)


#%%
# =====================================
# Sequence Dataset 생성
# =====================================

#%% 🔥Sequence 생성 함수
def create_sequence(
    X,
    y,
    lookback=168,
    horizon=24
):

    X_seq = []
    y_seq = []

    for i in range(
        lookback,
        len(X) - horizon
    ):

        X_seq.append(
            X[i-lookback:i]
        )

        y_seq.append(
            y[i:i+horizon, 0]
        )

    return (
        np.array(X_seq),
        np.array(y_seq)
    )

#%% 🔥Dataset Class

class PowerDataset(Dataset):

    def __init__(
        self,
        X,
        y
    ):
        self.X = torch.tensor(
            X,
            dtype=torch.float32
        )

        self.y = torch.tensor(
            y,
            dtype=torch.float32
        )

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):

        return (
            self.X[idx],
            self.y[idx]
        )    

#%% 🔥Device 설정

device = torch.device(
    'cuda'
    if torch.cuda.is_available()
    else 'cpu'
)

print("Device :", device)
#%% 🔥GRU Model

class GRUModel(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=128,
        num_layers=2,
        output_size=24
    ):

        super().__init__()

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=0.2,
            batch_first=True
        )

        self.fc = nn.Linear(
            hidden_size,
            output_size
        )

    def forward(self, x):

        out, hidden = self.gru(x)

        # 마지막 시점 Hidden State 사용
        out = out[:, -1, :]

        out = self.fc(out)

        return out
    
#%%
# =====================================
# Walk-Forward Validation
# =====================================

#%% 🔥Fold 기간

VALID_MONTHS = [
    '2025-11',
    '2025-12',
    '2026-01',
    '2026-02',
    '2026-03',
    '2026-04'
]

#%% 🔥Fold Result 저장용

results = []

fold_predictions = {}

#%% 🚀Walk-Forward Validation

for fold, valid_month in enumerate(
    VALID_MONTHS,
    start=1
):

    print(
        f'\n========== Fold {fold} =========='
    )

    print(
        f'Validation : {valid_month}'
    )


    # Train / Valid 분리
    valid_mask = (
        df_hour['ts']
        .dt.to_period('M')
        .astype(str)
        == valid_month
    )

    valid_df = df_hour[
        valid_mask
    ].copy()

    valid_start = valid_df['ts'].min()

    train_df = df_hour[
        df_hour['ts'] < valid_start
    ].copy()

    valid_df_extended = pd.concat(
        [
            train_df.tail(168),
            valid_df
        ]
    ).reset_index(drop=True)

    

    # scaling
    feature_scaler = StandardScaler()
    target_scaler = StandardScaler()

    X_train_scaled = feature_scaler.fit_transform(
        train_df[FEATURES]
    )

    y_train_scaled = target_scaler.fit_transform(
        train_df[[TARGET]]
    )

    X_valid_scaled = feature_scaler.transform(
        valid_df_extended[FEATURES]
    )

    y_valid_scaled = target_scaler.transform(
        valid_df_extended[[TARGET]]
    )

    X_train_seq, y_train_seq = create_sequence(
        X_train_scaled,
        y_train_scaled
    )

    X_valid_seq, y_valid_seq = create_sequence(
        X_valid_scaled,
        y_valid_scaled
    )

    print(X_train_seq.shape)
    print(y_train_seq.shape)

    print(X_valid_seq.shape)
    print(y_valid_seq.shape)

    #🔥Fold Dataset 생성

    train_dataset = PowerDataset(
        X_train_seq,
        y_train_seq
    )

    valid_dataset = PowerDataset(
        X_valid_seq,
        y_valid_seq
    )
    #🔥Fold DataLoader 생성

    train_loader = DataLoader(
        train_dataset,
        batch_size=64,
        shuffle=False
    )

    valid_loader = DataLoader(
        valid_dataset,
        batch_size=64,
        shuffle=False
    )
    #🔥Fold Model 생성

    model = GRUModel(
        input_size=len(FEATURES),
        hidden_size=256,
        num_layers=3,
        output_size=24
    )

    model = model.to(device)
    #🔥Fold Loss / Optimizer

    criterion = nn.L1Loss()

    optimizer = torch.optim.Adam(

        model.parameters(),
        lr=0.001
    )
    
   
    #🚀Fold Training
    
    # Early Stopping (Validation 기준)

    best_valid_loss = np.inf

    best_state = None

    patience = 5
    patience_counter = 0

    EPOCHS = 30

    for epoch in range(EPOCHS):

        model.train()

        train_loss = 0

        for X_batch, y_batch in train_loader:

            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)

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

        print(
            f'Fold {fold} | '
            f'Epoch {epoch+1}/{EPOCHS} | '
            f'Loss {train_loss:.4f}'
        )

        # ------------------
        # Validation Loss
        # ------------------

        model.eval()

        valid_loss = 0

        with torch.no_grad():

            for X_batch, y_batch in valid_loader:

                X_batch = X_batch.to(device)
                y_batch = y_batch.to(device)

                pred = model(X_batch)

                loss = criterion(
                    pred,
                    y_batch
                )

                valid_loss += loss.item()

        valid_loss /= len(valid_loader)

        print(
            f'Valid Loss : '
            f'{valid_loss:.4f}'
        )
        

        # Early Stopping

        if valid_loss < best_valid_loss:

            best_valid_loss = valid_loss

            best_state = copy.deepcopy(
                model.state_dict()
            )

            patience_counter = 0

        else:

            patience_counter += 1

        if patience_counter >= patience:

            print(
                f"Validation Early Stopping "
                f"(Epoch {epoch+1})"
            )

            break


    # Best Epoch 복구

    if best_state is not None:

        model.load_state_dict(
            best_state
        )        


    #🔥Fold Validation

    model.eval()

    preds = []
    trues = []

    #🔥Train MAE 계산용

    train_preds = []
    train_trues = []

    model.eval()

    with torch.no_grad():

        for X_batch, y_batch in train_loader:

            X_batch = X_batch.to(device)

            pred = model(X_batch)

            train_preds.append(
                pred.cpu().numpy()
            )

            train_trues.append(
                y_batch.numpy()
            )

    with torch.no_grad():

        for X_batch, y_batch in valid_loader:

            X_batch = X_batch.to(device)

            pred = model(X_batch)

            preds.append(
                pred.cpu().numpy()
            )

            trues.append(
                y_batch.numpy()
            )

    #🔥Fold Inverse Scaling

    preds = np.concatenate(preds)
    trues = np.concatenate(trues)

    preds_inv = target_scaler.inverse_transform(
        preds.reshape(-1, 1)
    ).reshape(preds.shape)

    trues_inv = target_scaler.inverse_transform(
        trues.reshape(-1, 1)
    ).reshape(trues.shape)

    #🔥Train Inverse Scaling

    train_preds = np.concatenate(
        train_preds
    )

    train_trues = np.concatenate(
        train_trues
    )

    train_preds_inv = (
        target_scaler.inverse_transform(
            train_preds.reshape(-1, 1)
        )
        .reshape(train_preds.shape)
    )

    train_trues_inv = (
        target_scaler.inverse_transform(
            train_trues.reshape(-1, 1)
        )
        .reshape(train_trues.shape)
    )

    #🔥Train MAE

    train_mae = mean_absolute_error(
        train_trues_inv.flatten(),
        train_preds_inv.flatten()
    )

    fold_predictions[valid_month] = {
            'preds': preds_inv.copy(),
            'trues': trues_inv.copy()
        } 

    #🔥Peak Metric

    peak_true = trues_inv.max(axis=1)
    peak_pred = preds_inv.max(axis=1)

    peak_mae = np.mean(
        np.abs(peak_true - peak_pred)
    )

    peak_hour_true = np.argmax(
        trues_inv,
        axis=1
    )

    peak_hour_pred = np.argmax(
        preds_inv,
        axis=1
    )

    peak_time_mae = np.mean(
        np.abs(
            peak_hour_true -
            peak_hour_pred
        )
    )

    #🔥Fold Metric

    mae = mean_absolute_error(
        trues_inv.flatten(),
        preds_inv.flatten()
    )

    rmse = np.sqrt(
        mean_squared_error(
            trues_inv.flatten(),
            preds_inv.flatten()
        )
    )

    mape = (
        mean_absolute_percentage_error(
            trues_inv.flatten(),
            preds_inv.flatten()
        ) * 100
    )

    print(
        f'Fold {fold} '
        f'MAE={mae:.4f} '
        f'RMSE={rmse:.4f} '
        f'MAPE={mape:.2f}%'
    )

    results.append({
        'fold': fold,
        'valid_month': valid_month,

        'train_mae': train_mae,

        'mae': mae,
        'rmse': rmse,
        'mape': mape,

        'peak_mae': peak_mae,
        'peak_time_mae': peak_time_mae
    })

#%% 💾 Fold Prediction 저장
np.save(
    "fold_predictions.npy",
    fold_predictions,
    allow_pickle=True
)

#%% 💾fold prediction 불러오기

fold_predictions = np.load(
    "fold_predictions.npy",
    allow_pickle=True
).item()

#%% 🔥Fold 결과 정리

results_df = pd.DataFrame(results)

print(results_df)

print("\n===== 평균 성능 =====")

print(
    f"Train MAE : "
    f"{results_df['train_mae'].mean():.4f}"
)

print(
    f"MAE  : "
    f"{results_df['mae'].mean():.4f}"
)

print(
    f"RMSE : "
    f"{results_df['rmse'].mean():.4f}"
)

print(
    f"MAPE : "
    f"{results_df['mape'].mean():.2f}%"
)

print(
    f"Peak MAE : "
    f"{results_df['peak_mae'].mean():.4f}"
)

print(
    f"Peak Time Error : "
    f"{results_df['peak_time_mae'].mean():.2f} h"
)


#%% 📈성능 결과 MAE = 0.7893
#=== GRU Summary ===
#   fold valid_month  train_mae       mae      rmse       mape  peak_mae  \
#0     1     2025-11   0.662980  0.673407  0.969888  29.970545  0.763170   
#1     2     2025-12   0.598688  0.736824  1.151142  36.536086  0.970771   
#2     3     2026-01   0.743641  1.216524  1.825641  47.113127  2.166249   
#3     4     2026-02   0.669407  0.791930  1.239542  28.668076  0.897412   
#4     5     2026-03   0.648940  0.687548  1.096596  24.133113  1.018875   
#5     6     2026-04   0.779874  0.629524  1.012127  26.123789  0.889684   

#   peak_time_mae  
#0       5.465318  
#1       5.336592  
#2       6.257053  
#3       5.379630  
#4       5.513250  
#5       4.288793  

#===== 평균 성능 =====
#Train MAE : 0.6839
#MAE  : 0.7893
#RMSE : 1.2158
#MAPE : 32.09%
#Peak MAE : 1.1177
#Peak Time Error : 5.37 h

#%% 🚀Final Training (전체 데이터 학습)

feature_scaler = StandardScaler()
target_scaler = StandardScaler()

X_scaled = feature_scaler.fit_transform(
    df_hour[FEATURES]
)

y_scaled = target_scaler.fit_transform(
    df_hour[[TARGET]]
)

# 🔥Sequence 생성

X_seq, y_seq = create_sequence(
    X_scaled,
    y_scaled,
    lookback=168,
    horizon=24
)

print(X_seq.shape)
print(y_seq.shape)

# 🔥Dataset

train_dataset = PowerDataset(
    X_seq,
    y_seq
)

train_loader = DataLoader(
    train_dataset,
    batch_size=64,
    shuffle=False
)

# 🔥최종 모델 생성

final_model = GRUModel(
    input_size=len(FEATURES),
    hidden_size=256,
    num_layers=3,
    output_size=24
).to(device)

criterion = nn.L1Loss()

optimizer = torch.optim.Adam(
    final_model.parameters(),
    lr=0.001
)

# 🔥학습

best_loss = np.inf

patience = 5
patience_counter = 0

EPOCHS = 30

for epoch in range(EPOCHS):

    final_model.train()

    train_loss = 0

    for X_batch, y_batch in train_loader:

        X_batch = X_batch.to(device)
        y_batch = y_batch.to(device)

        optimizer.zero_grad()

        pred = final_model(X_batch)

        loss = criterion(
            pred,
            y_batch
        )

        loss.backward()

        optimizer.step()

        train_loss += loss.item()

    train_loss /= len(train_loader)

    print(
        f'Final Training | '
        f'Epoch {epoch+1}/{EPOCHS} | '
        f'Loss {train_loss:.4f}'
    )

    if train_loss < best_loss:

        best_loss = train_loss
        patience_counter = 0

    else:

        patience_counter += 1

    if patience_counter >= patience:

        print(
            f"Final Early Stopping "
            f"(Epoch {epoch+1})"
        )

        break

print("최종 학습 완료")
#%% 💾모델 저장

torch.save(
    final_model.state_dict(),
    "gru_v4_final.pth"
)

joblib.dump(
    feature_scaler,
    "gru_v4_feature_scaler.pkl"
)

joblib.dump(
    target_scaler,
    "gru_v4_target_scaler.pkl"
)

print("모델 저장 완료")


#%% 📈 Fold 6 Actual vs Prediction

if fold == 6:

    plt.figure(figsize=(12, 5))

    plt.plot(
        trues_inv[0],
        marker='o',
        label='Actual'
    )

    plt.plot(
        preds_inv[0],
        marker='s',
        label='Prediction'
    )

    plt.title(
        '24 Hour Forecast (Fold 6)'
    )

    plt.xlabel('Forecast Horizon')

    plt.ylabel('kWh')

    plt.legend()

    plt.grid(True)

    plt.show()

#%% 📈 Final Model - 마지막 24시간 Actual vs Prediction

final_model.eval()

with torch.no_grad():

    # 가장 마지막 Sequence
    X_last = X_seq[-1]

    X_last = torch.tensor(
        X_last,
        dtype=torch.float32
    ).unsqueeze(0).to(device)

    pred_scaled = final_model(X_last)

# 역정규화
pred_24h = target_scaler.inverse_transform(
    pred_scaled.cpu().numpy().reshape(-1, 1)
).flatten()

# 실제 마지막 24시간
actual_24h = target_scaler.inverse_transform(
    y_seq[-1].reshape(-1, 1)
).flatten()

# 그래프
plt.figure(figsize=(12, 5))

plt.plot(
    range(1, 25),
    actual_24h,
    marker='o',
    label='Actual'
)

plt.plot(
    range(1, 25),
    pred_24h,
    marker='s',
    label='Prediction'
)

plt.xticks(range(1, 25))

plt.xlabel('Forecast Horizon (Hour)')
plt.ylabel('kWh')

plt.title(
    'Final Model - Last 24 Hours Forecast'
)

plt.legend()
plt.grid(True)

plt.show()
# %%
