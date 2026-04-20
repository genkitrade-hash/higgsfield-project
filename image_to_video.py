import json
import os
import sys
import time

import requests

API_URL = "https://platform.higgsfield.ai/higgsfield-ai/dop/lite"
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 600


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python image_to_video.py <image_url> [prompt]", file=sys.stderr)
        return 2

    image_url = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) >= 3 else ""

    api_key = os.environ["HF_API_KEY"]
    api_secret = os.environ["HF_API_SECRET"]

    headers = {
        "Content-Type": "application/json",
        "hf-api-key": api_key,
        "hf-secret": api_secret,
    }

    payload = {
        "prompt": prompt,
        "input_images": [{"type": "image_url", "image_url": image_url}],
        "motions": [],
        "enhance_prompt": True,
    }

    response = requests.post(API_URL, headers=headers, json=payload)

    print(f"HTTP {response.status_code}")
    print("Response headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print("Response body:")
    print(response.text)

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        print("Response was not JSON; nothing to poll.", file=sys.stderr)
        return 0

    job_id = _extract_job_id(data)
    if not job_id:
        video_url = _extract_video_url(data)
        if video_url:
            print("\nVideo URL:")
            print(video_url)
            return 0
        print("\nNo job id and no video url found in response.", file=sys.stderr)
        return 1

    print(f"\nPolling job {job_id} ...")
    status_url = f"{API_URL}/{job_id}"
    deadline = time.time() + POLL_TIMEOUT_SECONDS

    while time.time() < deadline:
        poll_resp = requests.get(status_url, headers=headers)
        print(f"\nHTTP {poll_resp.status_code}")
        print(poll_resp.text)
        poll_resp.raise_for_status()
        poll_data = poll_resp.json()

        status = (
            poll_data.get("status")
            or poll_data.get("state")
            or poll_data.get("job_status")
        )
        if isinstance(status, str) and status.lower() in {
            "completed",
            "complete",
            "succeeded",
            "success",
            "done",
            "finished",
        }:
            video_url = _extract_video_url(poll_data)
            if video_url:
                print("\nVideo URL:")
                print(video_url)
                return 0
            print("\nJob finished but no video url found.", file=sys.stderr)
            return 1
        if isinstance(status, str) and status.lower() in {
            "failed",
            "error",
            "cancelled",
            "canceled",
        }:
            print(f"\nJob ended with status: {status}", file=sys.stderr)
            return 1

        time.sleep(POLL_INTERVAL_SECONDS)

    print("\nTimed out waiting for job to finish.", file=sys.stderr)
    return 1


def _extract_job_id(data):
    if not isinstance(data, dict):
        return None
    for key in ("id", "job_id", "jobset_id", "request_id", "task_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_video_url(data):
    if isinstance(data, dict):
        video = data.get("video")
        if isinstance(video, dict):
            url = video.get("url")
            if isinstance(url, str):
                return url
        for key in ("video_url", "url", "output_url", "result_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        result = data.get("result") or data.get("output")
        if result is not None:
            found = _extract_video_url(result)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _extract_video_url(item)
            if found:
                return found
    return None


if __name__ == "__main__":
    sys.exit(main())
