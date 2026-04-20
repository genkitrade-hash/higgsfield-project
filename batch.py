import csv
import os
import sys
import time
from datetime import datetime, timezone

import requests

API_URL = "https://platform.higgsfield.ai/bytedance/seedream/v4/text-to-image"
PROMPTS_FILE = "prompts.txt"
RESULTS_FILE = "results.csv"
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 600


def main() -> int:
    try:
        api_key = os.environ["HF_API_KEY"]
        api_secret = os.environ["HF_API_SECRET"]
    except KeyError as exc:
        print(f"Missing env var: {exc}", file=sys.stderr)
        return 2

    headers = {
        "Content-Type": "application/json",
        "hf-api-key": api_key,
        "hf-secret": api_secret,
    }

    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        prompts = [line.strip() for line in f if line.strip()]

    if not prompts:
        print(f"No prompts found in {PROMPTS_FILE}.", file=sys.stderr)
        return 1

    results_exists = os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not results_exists:
            writer.writerow(["prompt", "image_url", "timestamp"])

        total = len(prompts)
        for i, prompt in enumerate(prompts, start=1):
            try:
                image_url = generate_image(prompt, headers)
                timestamp = datetime.now(timezone.utc).isoformat()
                writer.writerow([prompt, image_url, timestamp])
                csvfile.flush()
                print(f"{i}/{total} done ✅  {prompt!r} -> {image_url}")
            except Exception as exc:
                timestamp = datetime.now(timezone.utc).isoformat()
                writer.writerow([prompt, f"ERROR: {exc}", timestamp])
                csvfile.flush()
                print(f"{i}/{total} failed ❌  {prompt!r}: {exc}", file=sys.stderr)

    return 0


def generate_image(prompt: str, headers: dict) -> str:
    payload = {"prompt": prompt, "enhance_prompt": True}
    response = requests.post(API_URL, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    data = response.json()
    image_url = _extract_image_url(data)
    if image_url:
        return image_url

    job_id = _extract_job_id(data)
    if not job_id:
        raise RuntimeError(f"No job id and no image url in response: {data}")

    status_url = f"{API_URL}/{job_id}"
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        poll_resp = requests.get(status_url, headers=headers)
        if poll_resp.status_code >= 400:
            raise RuntimeError(f"Poll HTTP {poll_resp.status_code}: {poll_resp.text}")
        poll_data = poll_resp.json()

        status = (
            poll_data.get("status")
            or poll_data.get("state")
            or poll_data.get("job_status")
        )
        if isinstance(status, str) and status.lower() in {
            "completed", "complete", "succeeded", "success", "done", "finished",
        }:
            image_url = _extract_image_url(poll_data)
            if image_url:
                return image_url
            raise RuntimeError(f"Job finished but no image url: {poll_data}")
        if isinstance(status, str) and status.lower() in {
            "failed", "error", "cancelled", "canceled",
        }:
            raise RuntimeError(f"Job ended with status {status}: {poll_data}")

    raise TimeoutError(f"Timed out waiting for job {job_id}")


def _extract_job_id(data):
    if not isinstance(data, dict):
        return None
    for key in ("id", "job_id", "jobset_id", "request_id", "task_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_image_url(data):
    if isinstance(data, dict):
        image = data.get("image")
        if isinstance(image, dict):
            url = image.get("url")
            if isinstance(url, str):
                return url
        for key in ("image_url", "url", "output_url", "result_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for key in ("images", "results", "outputs"):
            value = data.get(key)
            found = _extract_image_url(value)
            if found:
                return found
        result = data.get("result") or data.get("output")
        if result is not None:
            found = _extract_image_url(result)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _extract_image_url(item)
            if found:
                return found
    return None


if __name__ == "__main__":
    sys.exit(main())
