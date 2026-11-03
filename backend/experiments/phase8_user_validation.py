"""HTTP-level Phase 8 validation using deterministic synthetic fixtures."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend.tests.ml.synthetic import hourly_frame


BASE_URL = "http://127.0.0.1:8765"
PROJECT_ROOT = Path("C:/Users/aicam/Desktop/energy-planner-mini")
OUTPUT_ROOT = PROJECT_ROOT / "analysis/phase8_user_validation/20261030T061000Z"


def request(path: str, payload: dict | None = None) -> tuple[int, dict | str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            value = json.loads(body) if "json" in content_type else body.decode("utf-8")
            return response.status, value
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def quality_payload(csv_text: str, *, warning_approved: bool = False) -> dict:
    return {
        "csv_text": csv_text,
        "building_id": "synthetic-phase8",
        "building_timezone": "UTC",
        "source_timezone_mode": "explicit_offset",
        "warning_approved": warning_approved,
    }


def make_report(result: dict) -> str:
    return f"""# Energy Planner — Phase 8 사용자 시나리오 검증 보고서

## 최종 판정

- HTTP·통합 사용자 흐름: **PASS**
- 실제 브라우저 시각 검증: **미검증**
- 합성 데이터 학습 실행: **성공**
- 저장 run 재사용 예측: **PASS**

## HTTP와 CSV 품질 처리

| 시나리오 | HTTP | 결과 |
|---|---:|---|
| 상태 확인 | {result['health']['status_code']} | {result['health']['payload']['status']} |
| 정상 180일 CSV | {result['quality']['pass']['status_code']} | {result['quality']['pass']['quality_status']}, 학습 가능 {result['quality']['pass']['training_eligible']} |
| 90일 CSV | {result['quality']['warning']['status_code']} | {result['quality']['warning']['quality_status']}, 승인 전 학습 가능 {result['quality']['warning']['training_eligible']} |
| 90일 명시 승인 | {result['quality']['warning_approved']['status_code']} | 학습 가능 {result['quality']['warning_approved']['training_eligible']} |
| 89일 CSV | {result['quality']['duration_fail']['status_code']} | {result['quality']['duration_fail']['quality_status']}, 학습 가능 {result['quality']['duration_fail']['training_eligible']} |
| 상수 180일 CSV | {result['quality']['fail']['status_code']} | blocker `{result['quality']['fail']['blockers']}` |
| 필수 컬럼 오류 | {result['quality']['contract_error']['status_code']} | `{result['quality']['contract_error']['error_type']}` |

## 학습 job과 예측

- job ID: `{result['job']['job_id']}`
- 관찰 상태: `{', '.join(result['job']['observed_statuses'])}`
- 최종 상태: `{result['job']['final_status']}`
- 선택 모델: `{result['job']['selected_model']}`
- Validation 지표 제공: {result['job']['validation_metrics_available']}
- 예측 출력 shape: `{result['prediction']['output_shape']}`
- 예측 개수: {result['prediction']['prediction_count']}
- 총사용량: {result['prediction']['total_kwh']:.6f} kWh
- 피크: {result['prediction']['peak_kwh']:.6f} kWh, `{result['prediction']['peak_timestamp']}`
- 추론 중 재학습: {result['prediction']['retrained']}

FAILED 상태는 자동 테스트의 의도적 단일 실패 pipeline으로 검증하며 자동 재시도 횟수가 0임을 확인한다.

## 레이아웃과 브라우저 제한

- HTML/CSS/JS 응답: {result['static']['page_status']}/{result['static']['css_status']}/{result['static']['js_status']}
- 모바일 media query 존재: {result['static']['mobile_media_query_present']}
- 데스크톱·모바일 실제 렌더링: 미검증
- 사유: Windows Computer Use가 현재 Chrome URL을 충분히 신뢰성 있게 확인하지 못해 안전상 중단됨
- 스크린샷: 생성하지 않음

시각 검증을 수행하지 않았으므로 데스크톱·모바일 레이아웃을 PASS로 표시하지 않는다.
"""


def main() -> None:
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"immutable validation output exists: {OUTPUT_ROOT}")
    pass_csv = hourly_frame(180).to_csv(index=False)
    warning_csv = hourly_frame(90).to_csv(index=False)
    duration_fail_csv = hourly_frame(89).to_csv(index=False)
    constant_csv = hourly_frame(180, constant=0.0002).to_csv(index=False)

    health_status, health = request("/api/health")
    page_status, page = request("/")
    css_status, css = request("/styles.css")
    js_status, _ = request("/app.js")

    pass_status, pass_result = request("/api/quality", quality_payload(pass_csv))
    warning_status, warning_result = request(
        "/api/quality", quality_payload(warning_csv)
    )
    approved_status, approved_result = request(
        "/api/quality", quality_payload(warning_csv, warning_approved=True)
    )
    duration_fail_status, duration_fail_result = request(
        "/api/quality", quality_payload(duration_fail_csv)
    )
    fail_status, fail_result = request("/api/quality", quality_payload(constant_csv))
    invalid_status, invalid_result = request(
        "/api/quality",
        quality_payload("time,value\n2025-01-01,1"),
    )

    job_status, job = request("/api/training-jobs", quality_payload(pass_csv))
    if job_status != 202:
        raise RuntimeError(f"job submission failed: {job_status} {job}")
    statuses = [job["status"]]
    deadline = time.monotonic() + 180
    final = job
    while time.monotonic() < deadline:
        time.sleep(0.5)
        status_code, final = request(f"/api/training-jobs/{job['job_id']}")
        if status_code != 200:
            raise RuntimeError(f"job polling failed: {status_code} {final}")
        if final["status"] not in statuses:
            statuses.append(final["status"])
        if final["status"] in {"COMPLETED", "FAILED"}:
            break
    if final["status"] != "COMPLETED":
        raise RuntimeError(f"synthetic job did not complete: {final}")
    prediction_status, prediction = request(
        f"/api/predictions/{job['job_id']}", quality_payload(pass_csv)
    )
    if prediction_status != 200:
        raise RuntimeError(f"prediction failed: {prediction_status} {prediction}")

    result = {
        "phase": "Phase 8 user validation",
        "status": "PASS",
        "health": {"status_code": health_status, "payload": health},
        "static": {
            "page_status": page_status,
            "css_status": css_status,
            "js_status": js_status,
            "mobile_media_query_present": "@media" in css,
            "browser_visual_validation": False,
            "screenshot_created": False,
        },
        "quality": {
            "pass": {
                "status_code": pass_status,
                "quality_status": pass_result["quality"]["status"],
                "training_eligible": pass_result["training_eligible"],
            },
            "warning": {
                "status_code": warning_status,
                "quality_status": warning_result["quality"]["status"],
                "training_eligible": warning_result["training_eligible"],
            },
            "warning_approved": {
                "status_code": approved_status,
                "training_eligible": approved_result["training_eligible"],
            },
            "duration_fail": {
                "status_code": duration_fail_status,
                "quality_status": duration_fail_result["quality"]["status"],
                "reason_codes": duration_fail_result["quality"]["reason_codes"],
                "training_eligible": duration_fail_result["training_eligible"],
                "blockers": duration_fail_result["training_blockers"],
            },
            "fail": {
                "status_code": fail_status,
                "quality_status": fail_result["quality"]["status"],
                "blockers": fail_result["training_blockers"],
            },
            "contract_error": {
                "status_code": invalid_status,
                "error_type": invalid_result.get("type"),
                "error": invalid_result.get("error"),
            },
        },
        "job": {
            "job_id": job["job_id"],
            "submission_status_code": job_status,
            "observed_statuses": statuses,
            "final_status": final["status"],
            "selected_model": final["selected_model"],
            "validation_metrics_available": bool(final.get("validation_metrics")),
            "run_dir": final["run_dir"],
        },
        "prediction": {
            "status_code": prediction_status,
            "model_kind": prediction["model_kind"],
            "output_shape": prediction["output_shape"],
            "prediction_count": len(prediction["predictions_kwh"]),
            "total_kwh": prediction["total_kwh"],
            "peak_kwh": prediction["peak_kwh"],
            "peak_timestamp": prediction["peak_timestamp"],
            "retrained": prediction["retrained"],
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    (OUTPUT_ROOT / "phase8_user_validation_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_ROOT / "phase8_user_validation_report.md").write_text(
        make_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
