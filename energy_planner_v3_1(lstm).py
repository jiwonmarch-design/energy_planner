# =====================================
# 🎉 energy planner project 🎉
# =====================================
# 
# energy_planner_v3_1.py
# LSTM 개선 버전 (Cyclical Feature + Multi-Step Forecast)
# v3 대비 시간 주기성 학습 및 24시간 미래 예측 성능 개선 목적
# 

# [개발 환경 분리 안내]

# [v3 실행]
# venv312 활성화
# > venv312\Scripts\activate
# > python energy_planner_v3.py

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


#%% 💾csv 파일로 저장

df_p15d.to_csv(
    'df_p15d.csv',
    index=False,
    encoding='utf-8-sig'
)

#%% 
# =====================================
# feature engineering
# =====================================

#%% ♻️hour / 시간대
# ts 컬럼에서 시간(hour) 추출 → 0~23 시간대 변수 생성

df_hour['hour'] = df_hour['ts'].dt.hour

# 확인
print(df_hour[['ts', 'hour']].head())

# ♻️hour
df_hour["sin_hour"] = np.sin(
    2 * np.pi * df_hour["hour"] / 24
)

df_hour["cos_hour"] = np.cos(
    2 * np.pi * df_hour["hour"] / 24
)


#%% ♻️weekday / 요일
# ts 컬럼에서 요일(weekday) 추출
# Monday=0, Sunday=6 형태로 생성됨

df_hour['weekday'] = df_hour['ts'].dt.weekday

# 확인
print(df_hour[['ts', 'weekday']].head())

# ♻️weekday
df_hour["sin_week"] = np.sin(
    2 * np.pi * df_hour["weekday"] / 7
)

df_hour["cos_week"] = np.cos(
    2 * np.pi * df_hour["weekday"] / 7
)
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


#%% ♻️month / 계절성
# ts 컬럼에서 월(month) 추출

df_hour['month'] = df_hour['ts'].dt.month

# 확인
print(df_hour[['ts', 'month']].head())

# ♻️
df_hour["sin_month"] = np.sin(
    2*np.pi*df_hour["month"]/12
)

df_hour["cos_month"] = np.cos(
    2*np.pi*df_hour["month"]/12
)

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
    'df_hour_v3_1.csv',
    index=False,
    encoding='utf-8-sig'
)

print("저장 완료 : df_hour_v3_1.csv")


# ♻️ 수정필요 >>> 볼 수 있는 형태로 변수들 저장



#%% ♻️Feature 선택

import json

with open("feature_columns.json", "r") as f:
    FEATURES = json.load(f)

TARGET = 'kwh_1h'

# target + feature 구성
df_model = df_hour[[TARGET] + FEATURES].copy()

print("Feature 개수 :", len(FEATURES))
print(df_model.shape)

#%% 🔥Train / Valid / Test Split (Scaling 전)

n_rows = len(df_model)

train_end_row = int(n_rows * 0.7)
valid_end_row = int(n_rows * 0.85)

df_train = df_model.iloc[:train_end_row]
df_valid = df_model.iloc[
    train_end_row:valid_end_row
]
df_test = df_model.iloc[
    valid_end_row:
]

print(df_train.shape)
print(df_valid.shape)
print(df_test.shape)

#%% 🔥Scaling (Train만 Fit)

scaler = MinMaxScaler()

scaler.fit(df_train)

train_scaled = scaler.transform(
    df_train
)

valid_scaled = scaler.transform(
    df_valid
)

test_scaled = scaler.transform(
    df_test
)
train_scaled = pd.DataFrame(
    train_scaled,
    columns=df_model.columns
)

valid_scaled = pd.DataFrame(
    valid_scaled,
    columns=df_model.columns
)

test_scaled = pd.DataFrame(
    test_scaled,
    columns=df_model.columns
)

scaled_data = pd.concat(
    [
        train_scaled,
        valid_scaled,
        test_scaled
    ],
    axis=0
).reset_index(drop=True)

print(scaled_data.shape)
#%% 🔥Sequence Dataset

LOOKBACK = 168
HORIZON = 24

X = []
y = []

target_idx = (
    scaled_data.columns
    .get_loc(TARGET)
)

for i in range(
    LOOKBACK,
    len(scaled_data) - HORIZON
):

    X.append(
        scaled_data.iloc[
            i-LOOKBACK:i
        ].values
    )

    y.append(
        scaled_data.iloc[
            i:i+HORIZON,
            target_idx
        ].values
    )

X = np.array(X)
y = np.array(y)

print(X.shape)
print(y.shape)

#%% 🔥Train / Valid / Test

n = len(X)

train_end = int(n * 0.7)
valid_end = int(n * 0.85)

X_train = X[:train_end]
y_train = y[:train_end]

X_valid = X[
    train_end:valid_end
]
y_valid = y[
    train_end:valid_end
]

X_test = X[valid_end:]
y_test = y[valid_end:]

print(X_train.shape)
print(X_valid.shape)
print(X_test.shape)

#%% 🔥Tensor 변환

X_train = torch.tensor(
    X_train,
    dtype=torch.float32
)

y_train = torch.tensor(
    y_train,
    dtype=torch.float32
)

X_valid = torch.tensor(
    X_valid,
    dtype=torch.float32
)

y_valid = torch.tensor(
    y_valid,
    dtype=torch.float32
)

X_test = torch.tensor(
    X_test,
    dtype=torch.float32
)

y_test = torch.tensor(
    y_test,
    dtype=torch.float32
)

print(X_train.shape)
print(y_train.shape)

#%% 🔥DataLoader

from torch.utils.data import (
    TensorDataset,
    DataLoader
)

BATCH_SIZE = 64

train_loader = DataLoader(
    TensorDataset(X_train, y_train),
    batch_size=BATCH_SIZE,
    shuffle=False
)

valid_loader = DataLoader(
    TensorDataset(X_valid, y_valid),
    batch_size=BATCH_SIZE,
    shuffle=False
)

#%% 🔥Device

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)

print(device)

#%% 🔥LSTM Model

class LSTMForecast(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=64,
        num_layers=2,
        horizon=24
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )

        self.fc = nn.Linear(
            hidden_size,
            horizon
        )

    def forward(self, x):

        out, (h, c) = self.lstm(x)

        out = out[:, -1, :]

        out = self.fc(out)

        return out
    
#%% 🔥Model 생성

model = LSTMForecast(
    input_size=X_train.shape[2],
    hidden_size=64,
    num_layers=2,
    horizon=24
)

model = model.to(device)

print(model)

#%% 🔥Loss & Optimizer

criterion = nn.MSELoss()

optimizer = torch.optim.Adam(
    model.parameters(),
    lr=0.001
)
#%% 🚀LSTM Training

EPOCHS = 20

for epoch in range(EPOCHS):

    # -------------------
    # Train
    # -------------------
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

    # -------------------
    # Validation
    # -------------------
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
        f"Epoch [{epoch+1}/{EPOCHS}] "
        f"Train={train_loss:.6f} "
        f"Valid={valid_loss:.6f}"
    )

#%% 🔥Test Prediction

model.eval()

with torch.no_grad():

    y_pred = model(
        X_test.to(device)
    )

y_pred = (
    y_pred
    .cpu()
    .numpy()
)

y_true = (
    y_test
    .cpu()
    .numpy()
)

print(y_pred.shape)
print(y_true.shape)

#%% 🔥MAE 0.120864

mae = mean_absolute_error(
    y_true.flatten(),
    y_pred.flatten()
)

print(f"Test MAE : {mae:.6f}")



#%% 💾Model Save

torch.save(
    model.state_dict(),
    "lstm_v3_1.pth"
)

print("저장 완료")

#%% 🔥LSTM v3.1 Exp1

class LSTMForecastExp1(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=128,
        num_layers=2,
        horizon=24
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=0.2,
            batch_first=True
        )

        self.fc = nn.Linear(
            hidden_size,
            horizon
        )

    def forward(self, x):

        out, _ = self.lstm(x)

        out = out[:, -1, :]

        return self.fc(out)
    
#%% 🔥Exp1 Model

model_exp1 = LSTMForecastExp1(
    input_size=X_train.shape[2]
).to(device)

criterion = nn.MSELoss()

optimizer = torch.optim.Adam(
    model_exp1.parameters(),
    lr=0.001
)

print(model_exp1)

#%% 🚀LSTM Training

EPOCHS = 50

for epoch in range(EPOCHS):

    # -------------------
    # Train
    # -------------------
    model_exp1.train()

    train_loss = 0

    for X_batch, y_batch in train_loader:

        X_batch = X_batch.to(device)
        y_batch = y_batch.to(device)

        optimizer.zero_grad()

        pred = model_exp1(X_batch)

        loss = criterion(
            pred,
            y_batch
        )

        loss.backward()

        optimizer.step()

        train_loss += loss.item()

    train_loss /= len(train_loader)

    # -------------------
    # Validation
    # -------------------
    model_exp1.eval()

    valid_loss = 0

    with torch.no_grad():

        for X_batch, y_batch in valid_loader:

            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)

            pred = model_exp1(X_batch)

            loss = criterion(
                pred,
                y_batch
            )

            valid_loss += loss.item()

    valid_loss /= len(valid_loader)

    print(
        f"Epoch [{epoch+1}/{EPOCHS}] "
        f"Train={train_loss:.6f} "
        f"Valid={valid_loss:.6f}"
    )

#%% 🔥Exp1 Test MAE : 0.108585

model_exp1.eval()

with torch.no_grad():

    y_pred = model_exp1(
        X_test.to(device)
    )

y_pred = y_pred.cpu().numpy()

y_true = y_test.cpu().numpy()

mae_exp1 = mean_absolute_error(
    y_true.flatten(),
    y_pred.flatten()
)

print(f"Exp1 MAE : {mae_exp1:.6f}")
#%% 💾Exp1 Save

np.save(
    "exp1_y_true.npy",
    y_true
)

np.save(
    "exp1_y_pred.npy",
    y_pred
)

torch.save(
    model_exp1.state_dict(),
    "lstm_v3_1_exp1.pth"
)
#%% 🔥LSTM v3.1 Exp2

class LSTMForecastExp2(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=256,
        num_layers=2,
        horizon=24
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=0.2,
            batch_first=True
        )

        self.fc = nn.Linear(
            hidden_size,
            horizon
        )

    def forward(self, x):

        out, _ = self.lstm(x)

        out = out[:, -1, :]

        return self.fc(out)
#%% 🔥Exp2 Model

model_exp2 = LSTMForecastExp2(
    input_size=X_train.shape[2]
).to(device)

criterion = nn.MSELoss()

optimizer = torch.optim.Adam(
    model_exp2.parameters(),
    lr=0.001
)

print(model_exp2)


model_exp1.eval()
#%% 🚀LSTM Training

EPOCHS = 50

best_valid = np.inf
patience = 10
counter = 0

for epoch in range(EPOCHS):

    # -------------------
    # Train
    # -------------------
    model_exp2.train()

    train_loss = 0

    for X_batch, y_batch in train_loader:

        X_batch = X_batch.to(device)
        y_batch = y_batch.to(device)

        optimizer.zero_grad()

        pred = model_exp2(X_batch)

        loss = criterion(
            pred,
            y_batch
        )

        loss.backward()

        optimizer.step()

        train_loss += loss.item()

    train_loss /= len(train_loader)

    # -------------------
    # Validation
    # -------------------
    model_exp2.eval()

    valid_loss = 0

    with torch.no_grad():

        for X_batch, y_batch in valid_loader:

            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)

            pred = model_exp2(X_batch)

            loss = criterion(
                pred,
                y_batch
            )

            valid_loss += loss.item()

    valid_loss /= len(valid_loader)

    # -------------------
    # Best Model Save
    # -------------------
    if valid_loss < best_valid:

        best_valid = valid_loss

        torch.save(
            model_exp2.state_dict(),
            "lstm_v3_1_best.pth"
        )

        counter = 0

    else:

        counter += 1

    print(
        f"Epoch [{epoch+1}/{EPOCHS}] "
        f"Train={train_loss:.6f} "
        f"Valid={valid_loss:.6f}"
    )

    # -------------------
    # Early Stopping
    # -------------------
    if counter >= patience:

        print(
            f"Early Stopping "
            f"(Best Valid={best_valid:.6f})"
        )

        break

#%% 🔥Exp2 Test

model_exp2.load_state_dict(
    torch.load(
        "lstm_v3_1_best.pth",
        map_location=device
    )
)

model_exp2.eval()

with torch.no_grad():

    y_pred = model_exp2(
        X_test.to(device)
    )

y_pred = y_pred.cpu().numpy()
y_true = y_test.cpu().numpy()

mae_exp2 = mean_absolute_error(
    y_true.flatten(),
    y_pred.flatten()
)

print(f"Exp2 MAE : {mae_exp2:.6f}")


model_exp2.eval()

with torch.no_grad():

    future_kwh = model_exp2(
        X_test[-1].unsqueeze(0).to(device)
    )

future_kwh = (
    future_kwh
    .cpu()
    .numpy()
    .flatten()
)

# 역정규화
kwh_min = scaler.data_min_[0]
kwh_max = scaler.data_max_[0]

future_kwh_real = (
    future_kwh
    * (kwh_max - kwh_min)
    + kwh_min
)

# 미래 시간 생성
last_ts = df_hour['ts'].iloc[-1]

future_ts = pd.date_range(
    start=last_ts + pd.Timedelta(hours=1),
    periods=24,
    freq='1h'
)

# 표 생성
future_df = pd.DataFrame({
    "datetime": future_ts,
    "predicted_kwh": future_kwh_real
})

print(future_df)

#%% 💾Exp2 Save

np.save(
    "exp2_y_true.npy",
    y_true
)

np.save(
    "exp2_y_pred.npy",
    y_pred
)

torch.save(
    model_exp2.state_dict(),
    "lstm_v3_1_exp2.pth"
)

print("Exp2 저장 완료")


# 모델 구조 생성
model_exp2 = LSTMForecastExp2(
    input_size=X_train.shape[2]
).to(device)

# 저장된 가중치 불러오기
model_exp2.load_state_dict(
    torch.load(
        "lstm_v3_1_exp2.pth",
        map_location=device
    )
)

# 평가 모드
model_exp2.eval()

print("Exp2 모델 불러오기 완료")


# v3.1 결론 :
# Cyclical Feature와 Multi-Step Forecast를 적용한
# LSTM Exp1(MAE 0.10881),
# LSTM Exp2(MAE 0.12577)는
# XGBoost Reduced + Optuna(MAE 0.08645)보다
# 낮은 예측 성능을 보였다.
#
# 다만 LSTM은 24시간을 동시에 예측하는 구조로
# Recursive Forecast 기반 XGBoost보다
# 장기 예측 시 Drift 발생 가능성이 낮을 수 있다.
#
# 따라서 본 프로젝트의 최종 모델은
# XGBoost Reduced + Optuna로 선정하되,
# 향후 장기 예측 안정성 검증을 위해
# LSTM 계열 모델을 추가 연구 대상으로 남긴다.



#%% 📂Exp1 Model Load

# 모델 구조 생성
model_exp1 = LSTMForecastExp1(
    input_size=X_train.shape[2]
).to(device)

# 저장된 가중치 불러오기
model_exp1.load_state_dict(
    torch.load(
        "lstm_v3_1_exp1.pth",
        map_location=device
    )
)

# 평가 모드
model_exp1.eval()

print("Exp1 모델 불러오기 완료")

#%% 📊 Exp1 Prediction Plot

import matplotlib.pyplot as plt
import numpy as np

# 저장된 결과 불러오기
y_true = np.load("exp1_y_true.npy")
y_pred = np.load("exp1_y_pred.npy")

# 첫 번째 샘플의 24시간 예측 결과
plt.figure(figsize=(12, 5))

plt.plot(
    y_true[0],
    label="Actual"
)

plt.plot(
    y_pred[0],
    label="Prediction"
)

plt.title("LSTM v3.1 Exp1 - 24H Forecast")
plt.xlabel("Hour Ahead")
plt.ylabel("Scaled kWh")

plt.legend()
plt.grid(True)

plt.show()
# %%
