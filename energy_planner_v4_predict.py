# =====================================
# 🎉 energy planner project 🎉
# =====================================
#
# energy_planner_v4_predict.py
# 저장된 GRU 모델을 이용한
# 향후 24시간 전력 사용량 예측
#
# =====================================

#%% 🔥라이브러리

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import joblib
import json

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
            batch_first=True
        )

        self.fc = nn.Linear(
            hidden_size,
            output_size
        )

    def forward(self, x):

        out, hidden = self.gru(x)

        out = out[:, -1, :]

        out = self.fc(out)

        return out


#%% 🔥Feature 목록 불러오기

with open(
    "feature_columns.json",
    "r"
) as f:

    FEATURES = json.load(f)

print(f"Feature 개수 : {len(FEATURES)}")


#%% 🔥Scaler 불러오기

feature_scaler = joblib.load(
    "gru_v4_feature_scaler.pkl"
)

target_scaler = joblib.load(
    "gru_v4_target_scaler.pkl"
)

print("Scaler Load 완료")


#%% 🔥모델 생성

model = GRUModel(
    input_size=len(FEATURES),
    hidden_size=128,
    num_layers=2,
    output_size=24
)

#%% 🔥모델 불러오기

model.load_state_dict(
    torch.load(
        "gru_v4_final.pth",
        map_location="cpu"
    )
)

model.eval()

print("Model Load 완료")


#%% 🔥Feature Engineering 결과 불러오기

df = pd.read_csv(
    "df_hour_v4.csv"
)

print(df.shape)


#%% 🔥최근 168시간 추출

X_input = (
    df[FEATURES]
    .tail(168)
)

print(X_input.shape)


#%% 🔥Scaling

X_scaled = feature_scaler.transform(
    X_input
)

print(X_scaled.shape)


#%% 🔥Tensor 변환

X_tensor = torch.tensor(
    X_scaled,
    dtype=torch.float32
).unsqueeze(0)

print(X_tensor.shape)


#%% 🔥예측

with torch.no_grad():

    pred_scaled = model(
        X_tensor
    ).numpy()

print(pred_scaled.shape)


#%% 🔥Inverse Scaling

pred = (
    target_scaler
    .inverse_transform(
        pred_scaled.reshape(-1, 1)
    )
    .flatten()
)

print(pred.shape)


#%% 🔥예측 결과 DataFrame

pred_df = pd.DataFrame({

    "hour_ahead":
        range(1, 25),

    "pred_kwh":
        pred

})

print(pred_df)


#%% 💾저장

pred_df.to_csv(
    "gru_v4_prediction.csv",
    index=False,
    encoding="utf-8-sig"
)

print(
    "\n예측 완료 : gru_v4_prediction.csv"
)

#%% 📈 Future 24h Forecast

import matplotlib.pyplot as plt

plt.figure(figsize=(12,5))

plt.plot(
    range(1,25),
    pred,
    marker='o'
)

plt.title(
    '(GRU) Future 24 Hour Forecast'
)

plt.xlabel('Hour Ahead')
plt.ylabel('kWh')

plt.grid(True)

plt.tight_layout()

plt.show()
# %%
