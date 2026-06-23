# Energy Planner

GRU 기반 단기 전력 사용량 24시간 동시 예측 시스템

---

## 1. 프로젝트 개요

Energy Planner는 15분 단위 전력 계량 데이터와 기온 데이터를 활용하여 향후 24시간의 시간별 전력 사용량(kWh)을 동시에 예측하는 AI 시스템입니다.

기존 Recursive Forecast 방식에서 발생하는 오차 누적(Error Propagation) 문제를 개선하기 위해 GRU(Gated Recurrent Unit) 기반 Direct Multi-Step Forecast 구조를 적용하였습니다.

---

## 2. 프로젝트 구조

```text
energy_planner_project/
├── README.md
├── energy_planner_v4_final.py
├── requirements.txt
├── data/
│   ├── df_hour_v4.csv
│   ├── df_p15d.csv
│   └── raw/
│       ├── gwangju_temp.csv
│       └── power_15m_data_202605271649.csv
├── research/
│   └── fold_predictions.npy
└── artifacts/
    ├── models/
    │   └── gru_v4_final.pth
    ├── processors/
    │   ├── gru_v4_feature_scaler.pkl
    │   └── gru_v4_target_scaler.pkl
    └── specs/
        ├── feature_spec.json
        ├── target_spec.json
        ├── training_metadata.json
        └── model_config.json
```

---

## 3. 개발 환경

* Python : 3.12.10
* PyTorch : 2.12.0+cpu
* NumPy : 2.4.6
* Pandas : 3.0.3
* Scikit-Learn : 1.9.0
* Joblib : 1.5.3
* Serving Device : CPU

---

## 4. 모델 정보

| 항목               | 값         |
| ---------------- | --------- |
| Model            | GRU       |
| Model Version    | v4_1_5    |
| Input Features   | 26        |
| Lookback Window  | 168 Hours |
| Forecast Horizon | 24 Hours  |
| Hidden Size      | 256       |
| Num Layers       | 3         |
| Dropout          | 0.2       |
| Output Size      | 24        |
| Total Parameters | 1,013,784 |
| Model Size       | 3.87 MB   |
| Target           | kwh_1h    |
| Target Unit      | kWh       |

---

## 5. 모델 구조

```text
Input
[Batch, 168, 26]
        ↓
GRU
hidden_size = 256
num_layers = 3
dropout = 0.2
        ↓
Last Hidden State
[Batch, 256]
        ↓
Linear
256 → 24
        ↓
Output
[Batch, 24]
```

---

## 6. 추론 파이프라인

1. 최근 168시간 전력 및 기온 데이터 수집
2. Feature Engineering 수행
3. feature_spec.json 순서대로 Feature 정렬
4. Feature Scaler 적용
5. Tensor 변환
6. GRU 모델 추론
7. Target Scaler 역변환
8. 향후 24시간 전력 사용량(kWh) 반환

---

## 7. Feature 정보

* Feature Count : 26
* Feature Order : artifacts/specs/feature_spec.json 기준

주의사항

* Feature 개수는 반드시 26개여야 한다.
* Feature 순서를 변경하면 안 된다.
* Feature 누락 시 추론 오류가 발생할 수 있다.

---

## 8. 전처리 객체(Scaler)

### Feature Scaler

* File : artifacts/processors/gru_v4_feature_scaler.pkl
* Class : StandardScaler
* Input Dimension : 26

### Target Scaler

* File : artifacts/processors/gru_v4_target_scaler.pkl
* Class : StandardScaler
* Mean : 2.5714
* Scale : 1.7317

주의사항

* fit()
* fit_transform()

위 메서드는 운영 환경에서 절대 호출하지 않는다.

반드시 아래 순서를 따른다.

```python
X_scaled = feature_scaler.transform(X)
prediction = model(X_scaled)
prediction = target_scaler.inverse_transform(prediction)
```

---

## 9. 모델 로드 예시

```python
import torch

model = GRUModel(
    input_size=26,
    hidden_size=256,
    num_layers=3,
    output_size=24
)

model.load_state_dict(
    torch.load(
        "artifacts/models/gru_v4_final.pth",
        map_location=torch.device("cpu")
    )
)

model.eval()
```

---

## 10. 실행 방법

### 패키지 설치

```bash
pip install -r requirements.txt
```

### 모델 실행

```bash
python energy_planner_v4_final.py
```

---

## 11. 산출물 목록

### 모델 파일

* artifacts/models/gru_v4_final.pth

### 전처리 객체

* artifacts/processors/gru_v4_feature_scaler.pkl
* artifacts/processors/gru_v4_target_scaler.pkl

### 규격 파일

* artifacts/specs/feature_spec.json
* artifacts/specs/target_spec.json
* artifacts/specs/training_metadata.json
* artifacts/specs/model_config.json

### 검증 데이터

* research/fold_predictions.npy
* data/df_hour_v4.csv

---

## 12. 운영 시 주의사항

1. CPU 환경에서 map_location='cpu'를 반드시 적용한다.
2. Feature 순서를 변경하지 않는다.
3. Feature Scaler와 Target Scaler를 재학습하지 않는다.
4. model.eval()을 반드시 호출한다.
5. 입력 Shape은 반드시 [Batch, 168, 26]을 유지한다.
6. 출력 Shape은 반드시 [Batch, 24]를 유지한다.

---

Author : 송지원
Project : Energy Planner
Last Update : 2026-06-23
