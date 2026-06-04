# %% library 

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from scipy.stats import norm
from sklearn.preprocessing import StandardScaler
from scipy import stats
import warnings
warnings.filterwarnings('ignore')




# ==================((power_15m_data))===========================

#%%
df_p15d = pd.read_csv('power_15m_data_202605271649.csv')


print(df_p15d['meter_id'].value_counts())


# %% meter_id = 1 이면서 channel_no = 1 인 데이터만 남기기
df_p15d = df_p15d[(df_p15d['meter_id'] == 1) & (df_p15d['channel_no'] == 1)]

# 확인
print(df_p15d[['meter_id', 'channel_no']].value_counts())




#%% 결측치
df_p15d.isnull().sum()

#%% 중복된 첫번째 행 삭제 
df_p15d = df_p15d.iloc[1:]

df_p15d = df_p15d.iloc[1:].reset_index(drop=True)


#%% 초 + 밀리초 제거 → 시:분까지만 남기기
# ts 컬럼 datetime 변환
df_p15d['ts'] = pd.to_datetime(df_p15d['ts'])

# 초 + 밀리초 제거 → 시:분까지만 남기기
df_p15d['ts'] = df_p15d['ts'].dt.floor('min')

# 확인
print(df_p15d['ts'].head())





#%%
df_p15d.to_csv('df_p15d.csv', index=False, encoding='utf-8-sig')



#%% 총기간 ? 2025-08-20 ~ 2026-05-27 
df_p15d['ts'].min(), df_p15d['ts'].max()




#%%
# 상관계수 계산
corr_matrix = df_p15d.corr(numeric_only=True)

# heatmap 출력
plt.figure(figsize=(12, 10))
sns.heatmap(
    corr_matrix,
    annot=True,        # 상관계수 표시
    cmap='coolwarm',   # 색상 테마
    fmt=".2f",         # 소수점 자리수
    linewidths=0.5
)

plt.title('df_p15d_Correlation Heatmap')
plt.show()





#%% current_power_kw
# ts 기준 정렬 (중요)
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['current_power_kw']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Current Power (kW)')
plt.title('Current Power over Time (ts)')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()


#%% kwh_this_month
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['kwh_this_month']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Electricity Usage (kWh)')
plt.title('Monthly Electricity Usage Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()



#%% kwh_last_month
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['kwh_last_month']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Last Month Electricity Usage (kWh)')
plt.title('Last Month Electricity Usage Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()


#%% kwh_sum
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['kwh_sum']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Total Electricity Usage (kWh)')
plt.title('Total Electricity Usage Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()

#%% daily_kwh
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['daily_kwh']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Daily Electricity Usage (kWh)')
plt.title('Daily Electricity Usage Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()


#%%
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['bill_15m']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('15-Minute Electricity Bill (KRW)')
plt.title('15-Minute Electricity Bill Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()


#%% bill_15m 컬럼 삭제 및 저장
df_p15d = df_p15d.drop(columns=['bill_15m'])

df_p15d.to_csv('df_p15d.csv', index=False)


#%% demand_kw

df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['demand_kw']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Power Demand (kW)')
plt.title('Power Demand Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()



#%%
df_p15d_sorted = df_p15d.sort_values('ts')

plt.figure(figsize=(14,6))

plt.plot(
    df_p15d_sorted['ts'],
    df_p15d_sorted['bill_15m']
)

plt.xlabel('Timestamp (ts)')
plt.ylabel('Electricity Usage (kWh)')
plt.title('15-Minute Electricity Usage Over Time')

plt.xticks(rotation=45)
plt.grid(True)

plt.show()

















# ========================((monthly_peak_power))==============================

# %%
df_mpp = pd.read_csv('monthly_peak_power_202605271650.csv')

# %%
# meter_id 값별 개수 확인
print(df_mpp['meter_id'].value_counts())

# %%
# meter_id가 1인 행만 남기기
df_mpp = df_mpp[df_mpp['meter_id'] == 1]

print(df_mpp['meter_id'].value_counts())

# %%
# 상관계수 계산
corr_matrix = df_mpp.corr(numeric_only=True)

# heatmap 출력
plt.figure(figsize=(12, 10))
sns.heatmap(
    corr_matrix,
    annot=True,        # 상관계수 표시
    cmap='coolwarm',   # 색상 테마
    fmt=".2f",         # 소수점 자리수
    linewidths=0.5
)

plt.title('df_mpp_Correlation Heatmap')
plt.show()
# %%
# 그래프 크기 설정
plt.figure(figsize=(12, 6))

# 막대그래프
plt.bar(df_mpp['id'], df_mpp['peak_power_kw'])

# 축 및 제목
plt.xlabel('id')
plt.ylabel('peak_power_kw')
plt.title('Peak Power by ID')

plt.show()


# %%
# 그래프 크기 설정
plt.figure(figsize=(12, 6))

# 막대그래프
plt.bar(df_mpp['month'], df_mpp['peak_power_kw'])

# 축 및 제목
plt.xlabel('month')
plt.ylabel('peak_power_kw')
plt.title('df_mpp_Peak Power by Month')

plt.show()



#%%
# year와 month를 합쳐 year_month 컬럼 생성
df_mpp['year_month'] = (
    df_mpp['year'].astype(str) + '-' +
    df_mpp['month'].astype(str).str.zfill(2)
)

# 확인
print(df_mpp[['year', 'month', 'year_month']].head())

# %%
# 그래프 크기 설정
plt.figure(figsize=(12, 6))

# 막대그래프
plt.bar(df_mpp['year_month'], df_mpp['peak_power_kw'])

# 축 및 제목
plt.xlabel('year_month')
plt.ylabel('peak_power_kw')
plt.title('df_mpp_Peak Power by Year_month')

plt.show()


# %%
# datetime 형식 변환
df_mpp['peak_timestamp'] = pd.to_datetime(df_mpp['peak_timestamp'])

# 시간/분/초 제거 (날짜만 남김)
df_mpp['peak_date'] = df_mpp['peak_timestamp'].dt.date

# 확인
print(df_mpp[['peak_timestamp', 'peak_date']].head())


# %%
print(df_mpp.sort_values(by='peak_date')['peak_date'])

# %%
# peak_date를 datetime으로 변환
df_mpp['peak_date'] = pd.to_datetime(df_mpp['peak_date'])

# 날짜에서 day(1~31) 추출
df_mpp['peak_day'] = df_mpp['peak_date'].dt.day

# 상관계수 계산 (peak_day vs peak_power_kw)
corr = df_mpp[['peak_day', 'peak_power_kw']].corr()

print(corr)


# ===============((billing_power_history))==================

# %% 
df_bph = pd.read_csv('billing_power_history_202605271651.csv')


# %%
df_bph.columns


# %%
df_bph.head()

#%%
# meter_id가 1인 것만 남기기
df_bph = df_bph[df_bph['meter_id'] == 1]

# 확인
print(df_bph['meter_id'].value_counts())


# %% billing month와 biling year ? 상관계수 -0.81
# 상관계수 계산
corr_matrix = df_bph.corr(numeric_only=True)

# heatmap 출력
plt.figure(figsize=(12, 10))
sns.heatmap(
    corr_matrix,
    annot=True,        # 상관계수 표시
    cmap='coolwarm',   # 색상 테마
    fmt=".2f",         # 소수점 자리수
    linewidths=0.5
)

plt.title('Correlation Heatmap')
plt.show()


# %% max_demand_power_kw(월 최대 수요 확인)
# billing_year + billing_month → 연월 컬럼 생성 (문자열 형태)
df_bph['billing_year_month'] = (
    df_bph['billing_year'].astype(str) + '-' +
    df_bph['billing_month'].astype(str).str.zfill(2)
)

# 확인
print(df_bph[['billing_year', 'billing_month', 'billing_year_month']].head())



# %%
# billing_year_month별 최대 수요 전력 계산
monthly_max = (
    df_bph.groupby('billing_year_month')['max_demand_power_kw']
    .max()
    .reset_index()
)

# 정렬 (중요: 시간순)
monthly_max = monthly_max.sort_values('billing_year_month')

# 차트
plt.figure(figsize=(12, 6))
plt.plot(
    monthly_max['billing_year_month'].astype(str),
    monthly_max['max_demand_power_kw'],
    marker='o'
)

plt.xticks(rotation=45)
plt.xlabel('Billing Year-Month')
plt.ylabel('Max Demand Power (kW)')
plt.title('df_bph_Monthly Max Demand Power')

plt.grid(True)
plt.show()






# =====================((v_hourly_kwh_cum_exact))===========================

# %%
df_vhkce = pd.read_csv('v_hourly_kwh_cum_exact_kst_202605281401.csv')




# %%
# ============================================================
# Fold 3 MAE 이상치 보정을 위한 EDA
# ============================================================


#%%-------------------------------
# CSV 불러오기
# -------------------------------
import pandas as pd
import matplotlib.pyplot as plt

# 한글 깨짐 방지 (Windows)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

df_jt = pd.read_csv('january_temp.csv')


# -------------------------------
# 시계열 기온 그래프
# -------------------------------
plt.figure(figsize=(14, 6))

plt.plot(
    df_jt['date'],
    df_jt['aver_temp'],
    marker='o',
    linewidth=2,
    label='평균기온'
)

plt.plot(
    df_jt['date'],
    df_jt['min_temp'],
    marker='v',
    linestyle='--',
    linewidth=1.5,
    label='최저기온'
)

plt.plot(
    df_jt['date'],
    df_jt['max_temp'],
    marker='^',
    linestyle='--',
    linewidth=1.5,
    label='최고기온'
)

plt.title('2026년 1월 광주 일별 기온 변화', fontsize=15)
plt.xlabel('날짜')
plt.ylabel('기온 (℃)')
plt.xticks(rotation=45)
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()
plt.show()


#%% 🔥12월 ~ 3월 기온 추이 (1월 하순 한파 여부 확인)

import pandas as pd
import matplotlib.pyplot as plt

# 한글 깨짐 방지
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 데이터 불러오기
df_temp = pd.read_csv('gwangju_temp.csv')

# 날짜형 변환
df_temp['date'] = pd.to_datetime(df_temp['date'])

# 12월 ~ 3월 데이터 선택
df_temp = df_temp[
    df_temp['date'].dt.month.isin([12, 1, 2, 3])
].copy()

# 날짜순 정렬
df_temp = df_temp.sort_values('date')

# -------------------------------
# Line Chart
# -------------------------------
plt.figure(figsize=(16, 6))

plt.plot(
    df_temp['date'],
    df_temp['avg_temp'],
    linewidth=2.5,
    marker='o',
    markersize=3,
    label='평균기온'
)

plt.plot(
    df_temp['date'],
    df_temp['daily_min_temp'],
    linestyle='--',
    linewidth=1.5,
    label='최저기온'
)

plt.plot(
    df_temp['date'],
    df_temp['daily_max_temp'],
    linestyle='--',
    linewidth=1.5,
    label='최고기온'
)

# 1월 하순 영역 강조
plt.axvspan(
    pd.Timestamp('2026-01-21'),
    pd.Timestamp('2026-01-31'),
    alpha=0.2,
    label='1월 하순'
)

plt.title('광주 일별 기온 추이 (12월 ~ 3월)', fontsize=15)
plt.xlabel('Date')
plt.ylabel('Temperature (℃)')
plt.xticks(rotation=45)
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()

plt.show()
# %%
