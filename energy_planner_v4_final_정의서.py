# ============================================================
# energy_planner_v4_final_정의서.py
# 목적:
# 정의서 작성에 필요한 메타데이터 및 프로젝트 정보를 자동 점검
# ============================================================

#%% 🔥1차검증
import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

ARTIFACT_FILES = [
    "energy_planner_project/artifacts/models/gru_v4_final.pth",
    "energy_planner_project/artifacts/processors/gru_v4_feature_scaler.pkl",
    "energy_planner_project/artifacts/processors/gru_v4_target_scaler.pkl",
    "energy_planner_project/artifacts/specs/feature_spec.json",
    "energy_planner_project/artifacts/specs/target_spec.json",
    "energy_planner_project/artifacts/specs/training_metadata.json",
    "energy_planner_project/requirements.txt",
    "energy_planner_project/research/fold_predictions.npy",
    "energy_planner_project/data/df_hour_v4.csv"
]


# ============================================================
# 공통 출력 함수
# ============================================================

def print_title(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ============================================================
# 프로젝트 경로
# ============================================================

def show_project_root():
    print_title("PROJECT ROOT")
    print(PROJECT_ROOT)


# ============================================================
# 산출물 존재 여부 확인
# ============================================================

def check_artifacts():
    print_title("ARTIFACT CHECK")

    for file in ARTIFACT_FILES:
        path = PROJECT_ROOT / file

        if path.exists():
            print(f"[OK]       {file}")
        else:
            print(f"[MISSING]  {file}")


# ============================================================
# JSON 읽기
# ============================================================

def load_json(path):

    path = PROJECT_ROOT / path

    if not path.exists():
        print(f"\n[MISSING] {path}")
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# feature_spec
# ============================================================

def show_feature_spec():
    print_title("FEATURE SPEC")

    data = load_json(
        "artifacts/specs/feature_spec.json"
    )

    if data is None:
        return

    feature_count = data.get("feature_count", 0)
    features = data.get("features", [])

    print(f"Feature Count : {feature_count}\n")

    for i, feature in enumerate(features, start=1):
        print(f"{i:02d}. {feature}")


# ============================================================
# target_spec
# ============================================================

def show_target_spec():
    print_title("TARGET SPEC")

    data = load_json(
        "energy_planner_project/artifacts/specs/target_spec.json"
    )

    if data is None:
        return

    print(
        json.dumps(
            data,
            indent=4,
            ensure_ascii=False
        )
    )


# ============================================================
# training_metadata
# ============================================================

def show_training_metadata():
    print_title("TRAINING METADATA")

    data = load_json(
        "energy_planner_project/artifacts/specs/training_metadata.json"
    )

    if data is None:
        return

    for key, value in data.items():
        print(f"{key:20} : {value}")


# ============================================================
# requirements 요약
# ============================================================

def show_requirements_summary():
    print_title("REQUIREMENTS SUMMARY")

    path = PROJECT_ROOT / "requirements.txt"

    if not path.exists():
        print("requirements.txt 없음")
        return

    packages = [
        "torch",
        "numpy",
        "pandas",
        "scikit-learn",
        "matplotlib",
        "joblib",
        "optuna",
        "lightgbm",
        "xgboost",
        "tensorflow"
    ]

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for package in packages:
        found = False

        for line in lines:
            if line.lower().startswith(package.lower()):
                print(line.strip())
                found = True
                break

        if not found:
            print(f"{package} : NOT FOUND")


# ============================================================
# model_config 생성
# ============================================================

def generate_model_config():
    print_title("MODEL CONFIG")

    feature_spec = load_json(
        "energy_planner_project/artifacts/specs/feature_spec.json"
    )

    if feature_spec is None:
        print("feature_spec.json 필요")
        return

    model_config = {
        "model_type": "GRU",
        "input_size": feature_spec["feature_count"],
        "hidden_size": 256,
        "num_layers": 3,
        "output_size": 24,
        "dropout": 0.2
    }

    save_path = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/specs/model_config.json"
    )

    save_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        save_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            model_config,
            f,
            indent=4,
            ensure_ascii=False
        )

    print("model_config.json 생성 완료")
    print(json.dumps(
        model_config,
        indent=4,
        ensure_ascii=False
    ))


# ============================================================
# 정의서 요약
# ============================================================

def generate_definition_report():
    print_title("MODEL SUMMARY")

    feature_spec = load_json(
        "energy_planner_project/artifacts/specs/feature_spec.json"
    )

    target_spec = load_json(
        "energy_planner_project/artifacts/specs/target_spec.json"
    )

    metadata = load_json(
        "energy_planner_project/artifacts/specs/training_metadata.json"
    )

    if (
        feature_spec is None
        or target_spec is None
        or metadata is None
    ):
        return

    print(
        f"Project Version : "
        f"energy_planner_v4_final"
    )

    print(
        f"Model           : "
        f"{metadata['model_name']}"
    )

    print(
        f"Input Features  : "
        f"{feature_spec['feature_count']}"
    )

    print(
        f"Lookback        : "
        f"{metadata['lookback']} Hours"
    )

    print(
        f"Forecast        : "
        f"{metadata['forecast_horizon']} Hours"
    )

    print(
        f"Epochs          : "
        f"{metadata['epochs']}"
    )

    print(
        f"Target          : "
        f"{target_spec['target']}"
    )

    print(
        f"Target Unit     : "
        f"{target_spec['target_unit']}"
    )

    print(
        f"Hidden Size     : "
        f"{metadata['hidden_size']}"
    )

    print(
        f"Num Layers      : "
        f"{metadata['num_layers']}"
    )

    print(
        f"Dropout         : "
        f"{metadata['dropout']}"
    )

    print(
        f"Best Train Loss : "
        f"{metadata['best_train_loss']:.6f}"
    )


# ============================================================
# main
# ============================================================

def main():

    show_project_root()

    check_artifacts()

    show_feature_spec()

    show_target_spec()

    show_training_metadata()

    show_requirements_summary()

    generate_model_config()

    generate_definition_report()


if __name__ == "__main__":
    main()


#%% 🔥2차검증


import pickle
import traceback
import torch
import torch.nn as nn

# 기존 스크립트의 PROJECT_ROOT 환경을 그대로 준수합니다.
from energy_planner_v4_final_정의서 import PROJECT_ROOT, print_title, load_json


# ============================================================
# [추가 검증 1] 실제 GRU 가중치 파일(.pth) 구조 및 내부 차원 실측
# ============================================================
def verify_pth_weights_and_dimensions():
    print_title("ADVANCED: PTH WEIGHTS & DIMENSION REAL-CHECK")
    pth_path = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/models/gru_v4_final.pth"
    )

    if not pth_path.exists():
        print(f"[MISSING] .pth 파일이 존재하지 않습니다: {pth_path}")
        return

    try:
        # 원칙 3(서버 운영 전제)에 따라 CPU 디바이스 환경으로 안전하게 로드 검증
        state_dict = torch.load(pth_path, map_location=torch.device("cpu"))
        print(f"[SUCCESS] gru_v4_final.pth 로드 완료 (CPU map_location 검증 성공)")

        # 가중치 딕셔너리 키 배열 구조 실측
        print("\n--- 실제 가중치 레이어 별 텐서 차원 (State Dict Shapes) ---")
        for layer_name, tensor in state_dict.items():
            print(f"Layer: {layer_name:<30} | Shape: {list(tensor.shape)}")

        # 원칙 1 검증: 실제 가중치 파일 내 input_size 및 hidden_size 추출
        # GRU의 첫 번째 레이어 가중치(weight_ih_l0)의 가로 차원은 [3 * hidden_size, input_size] 입니다.
        if "gru.weight_ih_l0" in state_dict:
            weight_shape = state_dict["gru.weight_ih_l0"].shape
            actual_hidden_size = weight_shape[0] // 3
            actual_input_size = weight_shape[1]

            print("\n--- 실제 가중치 파일 내부 바이너리 실측 결과 ---")
            print(f"실측 입력 피처 차원(Input Size) : {actual_input_size}")
            print(f"실측 은닉 뉴런 수(Hidden Size)   : {actual_hidden_size}")

            # feature_spec.json의 feature_count와 교차 정합성 체크
            feature_spec = load_json(
                "energy_planner_project/artifacts/specs/feature_spec.json"
            )
            if feature_spec and (
                feature_spec.get("feature_count") != actual_input_size
            ):
                print(
                    f"⚠️ [경고] 정합성 불일치! feature_spec.json({feature_spec.get('feature_count')}) != pth실측({actual_input_size})"
                )
            else:
                print(
                    "✅ [정합성 통과] feature_spec.json과 .pth 모델 가중치 차원이 일치합니다."
                )
    except Exception as e:
        print(f"[ERROR] .pth 파일 내부 검증 중 오류 발생")
        traceback.print_exc()


# ============================================================
# [추가 검증 2] 전처리 스케일러(.pkl) 파일 복원 및 차원 실측
# ============================================================
def verify_scaler_artifacts():
    print_title("ADVANCED: SCALER OBJECT REAL-CHECK")

    feature_scaler_path = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/processors/gru_v4_feature_scaler.pkl"
    )
    target_scaler_path = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/processors/gru_v4_target_scaler.pkl"
    )

    # 1. 입력 피처 스케일러 검증
    if feature_scaler_path.exists():
        try:
            with open(feature_scaler_path, "rb") as f:
                scaler_X = pickle.load(f)
            print(f"[SUCCESS] Feature Scaler 복원 성공 ({type(scaler_X)})")

            # 스케일러가 기억하고 있는 학습 데이터셋의 실제 피처 개수 실측
            if hasattr(scaler_X, "n_features_in_"):
                print(
                    f"스케일러 기대 입력 차원 수 (n_features_in_) : {scaler_X.n_features_in_}"
                )
        except Exception as e:
            print(f"[ERROR] Feature Scaler 로드 실패: {e}")
    else:
        print(f"[MISSING] Feature Scaler 파일 없음: {feature_scaler_path}")

    # 2. 타겟 역변환 스케일러 검증
    if target_scaler_path.exists():
        try:
            with open(target_scaler_path, "rb") as f:
                scaler_y = pickle.load(f)
            print(f"[SUCCESS] Target Scaler 복원 성공 ({type(scaler_y)})")
            if hasattr(scaler_y, "mean_"):
                print(
                    f"타겟 변수 학습 평균값 (mean_)               : {scaler_y.mean_[0]:.4f}"
                )
                print(
                    f"타겟 변수 학습 표준편차 (scale_)             : {scaler_y.scale_[0]:.4f}"
                )
        except Exception as e:
            print(f"[ERROR] Target Scaler 로드 실패: {e}")
    else:
        print(f"[MISSING] Target Scaler 파일 없음: {target_scaler_path}")


# ============================================================
# Execution Entrypoint
# ============================================================
if __name__ == "__main__":
    print("============================================================")
    print("정의서 보완을 위한 2차 딥러닝 바이너리 정합성 추가 검증 시작")
    print("============================================================")
    verify_pth_weights_and_dimensions()
    verify_scaler_artifacts()

#%% 3차검증
from datetime import datetime

def show_file_metadata():
    print_title("FILE METADATA")

    files = [
        "energy_planner_project/artifacts/models/gru_v4_final.pth",
        "energy_planner_project/artifacts/processors/gru_v4_feature_scaler.pkl",
        "energy_planner_project/artifacts/processors/gru_v4_target_scaler.pkl"
    ]

    for file in files:
        path = PROJECT_ROOT / file

        if path.exists():
            stat = path.stat()

            size_mb = stat.st_size / (1024 ** 2)

            created = datetime.fromtimestamp(
                stat.st_ctime
            )

            print(f"\n{path.name}")
            print(f"Size      : {size_mb:.2f} MB")
            print(f"Created   : {created}")





#%% 1. 파일 크기 및 생성일 추출

from datetime import datetime

def show_file_metadata():
    print_title("FILE METADATA")

    files = [
        "energy_planner_project/artifacts/models/gru_v4_final.pth",
        "energy_planner_project/artifacts/processors/gru_v4_feature_scaler.pkl",
        "energy_planner_project/artifacts/processors/gru_v4_target_scaler.pkl"
    ]

    for file in files:
        path = PROJECT_ROOT / file

        if path.exists():
            stat = path.stat()

            size_mb = stat.st_size / (1024 ** 2)

            created = datetime.fromtimestamp(
                stat.st_ctime
            )

            print(f"\n{path.name}")
            print(f"Size      : {size_mb:.2f} MB")
            print(f"Created   : {created}")

#%% 2. 스케일러 실제 정보 추출

import joblib

def verify_scaler_artifacts():
    print_title("ADVANCED: SCALER REAL-CHECK")

    feature_scaler = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/processors/gru_v4_feature_scaler.pkl"
    )

    target_scaler = (
        PROJECT_ROOT
        / "energy_planner_project/artifacts/processors/gru_v4_target_scaler.pkl"
    )

    try:
        scaler_X = joblib.load(feature_scaler)

        print("[SUCCESS] Feature Scaler")

        print(
            f"type              : {type(scaler_X).__name__}"
        )

        print(
            f"n_features_in_    : {scaler_X.n_features_in_}"
        )

        print(
            f"mean shape        : {scaler_X.mean_.shape}"
        )

        print(
            f"scale shape       : {scaler_X.scale_.shape}"
        )

    except Exception as e:
        print(e)

    try:
        scaler_y = joblib.load(target_scaler)

        print("\n[SUCCESS] Target Scaler")

        print(
            f"type              : {type(scaler_y).__name__}"
        )

        print(
            f"mean              : {scaler_y.mean_[0]:.4f}"
        )

        print(
            f"scale             : {scaler_y.scale_[0]:.4f}"
        )

    except Exception as e:
        print(e)


#%% 3. 데이터셋 정보 추출
import pandas as pd

def show_dataset_info():
    print_title("DATASET INFO")

    csv_path = (
        PROJECT_ROOT
        / "energy_planner_project/data/df_hour_v4.csv"
    )

    if not csv_path.exists():
        return

    df = pd.read_csv(csv_path)

    print(f"Rows           : {len(df):,}")
    print(f"Columns        : {df.shape[1]}")
    print(f"Memory(MB)     : "
          f"{df.memory_usage().sum()/1024**2:.2f}")

    print(
        f"Missing Values : "
        f"{df.isnull().sum().sum()}"
    )


#%% 4. Fold Prediction 성능 요약

import numpy as np

def show_cv_info():
    print_title("WALK-FORWARD VALIDATION")

    path = (
        PROJECT_ROOT
        / "energy_planner_project/research/fold_predictions.npy"
    )

    if not path.exists():
        return

    fold_predictions = np.load(
        path,
        allow_pickle=True
    ).item()

    print(
        f"Fold Count : "
        f"{len(fold_predictions)}"
    )

    print(
        f"Validation Months : "
        f"{list(fold_predictions.keys())}"
    )

#%% 5. 실제 PyTorch 환경 추출
import sys
import sklearn
import pandas as pd
import numpy as np

def show_environment():
    print_title("EXECUTION ENVIRONMENT")

    print(f"Python        : {sys.version}")
    print(f"PyTorch       : {torch.__version__}")
    print(f"Numpy         : {np.__version__}")
    print(f"Pandas        : {pd.__version__}")
    print(f"Scikit-Learn  : {sklearn.__version__}")

    
#%% 6. 실제 GRU 파라미터 개수
# 
def show_parameter_count():
    print_title("MODEL PARAMETERS")

    state_dict = torch.load(
        PROJECT_ROOT
        / "energy_planner_project/artifacts/models/gru_v4_final.pth",
        map_location="cpu"
    )

    total_params = 0

    for tensor in state_dict.values():
        total_params += tensor.numel()

    print(
        f"Total Parameters : "
        f"{total_params:,}"
    ) 

show_file_metadata()
show_dataset_info()
show_cv_info()
show_environment()
show_parameter_count()
verify_scaler_artifacts()                                   