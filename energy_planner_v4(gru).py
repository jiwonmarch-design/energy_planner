# =====================================
# 🎉 energy planner project 🎉
# =====================================
#
# energy_planner_v4.py
# GRU 기반 전력 사용량 예측 모델
# XGBoost Recursive Forecast의 오차 누적 문제를 개선하고
# 장기 시계열 패턴 학습 및 Multi-Step Forecast 성능 향상을 목적으로 개발
#

# [개발 환경 분리 안내]

# [v4 실행]
# venv312 활성화
# > venv312\Scripts\activate
# > python energy_planner_v4.py

# ============================================================

#%% 🔥라이브러리
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


import holidays

import joblib
import requests


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

#%% Cyclical Feature

df_hour['hour_sin'] = np.sin(
    2 * np.pi * df_hour['hour'] / 24
)

df_hour['hour_cos'] = np.cos(
    2 * np.pi * df_hour['hour'] / 24
)

df_hour['weekday_sin'] = np.sin(
    2 * np.pi * df_hour['weekday'] / 7
)

df_hour['weekday_cos'] = np.cos(
    2 * np.pi * df_hour['weekday'] / 7
)


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
FEATURES = [

    # 시간
    'hour_sin',
    'hour_cos',

    # 요일
    'weekday_sin',
    'weekday_cos',

    'is_weekend',
    'is_holiday',

    # 온도
    'avg_temp',
    'daily_max_temp',
    'daily_min_temp',
    'temp_range',

    'cooling_degree',
    'heating_degree',

    # Lag
    'lag_1',
    'lag_24',
    'lag_168',

    # Rolling
    'rolling_mean_3',
    'rolling_mean_6',
    'rolling_mean_24',
    'rolling_max_24',
    'rolling_min_24',

    # Diff
    'diff_1',
    'diff_24',
    'diff_168'

]

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
        hidden_size=64,
        num_layers=2,
        output_size=24
    ):

        super().__init__()

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
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

    valid_df_extended = pd.concat(
    [
        train_df.tail(168),
        valid_df
    ]
).reset_index(drop=True)

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
        shuffle=True
    )

    valid_loader = DataLoader(
        valid_dataset,
        batch_size=64,
        shuffle=False
    )
    #🔥Fold Model 생성

    model = GRUModel(
        input_size=len(FEATURES),
        hidden_size=64,
        num_layers=2,
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

    #🔥Fold Validation

    model.eval()

    preds = []
    trues = []

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

        'mae': mae,

        'rmse': rmse,

        'mape': mape

    })

#%%



