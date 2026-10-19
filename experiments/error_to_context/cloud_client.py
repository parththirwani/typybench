import os
import time
import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import requests


ENV_KEY = "CODEMATE_API_KEY"
DEFAULT_BASE_URL = "https://llm.codemate.ai/v1"
DEFAULT_MODEL = "gpt-5.4-mini"


@dataclass
class CallRecord:
    request_id: str
    model: str
    prompt_hash: str
    response_id: Optional[str]
    status: str
    latency_ms: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    error: Optional[str] = None
    retries: int = 0


@dataclass
class CloudClient:
    base_url: str = None
    model: str = None
    api_key: str = None
    max_retries: int = 3
    retry_delay_s: float = 2.0
    records: list = field(default_factory=list)

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.environ.get(ENV_KEY, "")
        if self.base_url is None:
            self.base_url = os.environ.get("CODEMATE_BASE_URL", DEFAULT_BASE_URL)
        if self.model is None:
            self.model = os.environ.get("CODEMATE_MODEL", DEFAULT_MODEL)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def _prompt_hash(self, messages: list) -> str:
        raw = json.dumps(messages, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def chat(self, messages: list, temperature: float = 0.0, max_tokens: int = 1024) -> tuple[str, CallRecord]:
        prompt_hash = self._prompt_hash(messages)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = self.base_url.rstrip("/") + "/chat/completions"

        for attempt in range(1 + self.max_retries):
            t0 = time.monotonic()
            try:
                resp = self._session.post(url, json=body, timeout=120)
                latency_ms = (time.monotonic() - t0) * 1000
                if resp.status_code == 429 and attempt < self.max_retries:
                    time.sleep(self.retry_delay_s * (attempt + 1))
                    continue
                resp.raise_for_status()
            except requests.RequestException as e:
                latency_ms = (time.monotonic() - t0) * 1000
                record = CallRecord(
                    request_id="",
                    model=self.model,
                    prompt_hash=prompt_hash,
                    response_id=None,
                    status="error",
                    latency_ms=latency_ms,
                    input_tokens=None,
                    output_tokens=None,
                    error=str(e)[:300],
                    retries=attempt,
                )
                self.records.append(record)
                return "", record

            try:
                data = resp.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                usage = data.get("usage") or {}
                if not isinstance(usage, dict):
                    raise TypeError("usage is not an object")
            except (ValueError, KeyError, IndexError, TypeError) as e:
                record = CallRecord(
                    request_id=resp.headers.get("x-request-id", ""),
                    model=self.model, prompt_hash=prompt_hash,
                    response_id=None, status="invalid_response",
                    latency_ms=latency_ms, input_tokens=None,
                    output_tokens=None, error=f"Malformed response: {type(e).__name__}",
                    retries=attempt,
                )
                self.records.append(record)
                return "", record

            complete = choice.get("finish_reason") not in ("length", "content_filter")
            complete = complete and isinstance(content, str) and bool(content.strip())
            record = CallRecord(
                request_id=resp.headers.get("x-request-id", ""),
                model=self.model, prompt_hash=prompt_hash,
                response_id=data.get("id"),
                status="success" if complete else "invalid_response",
                latency_ms=latency_ms,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                error=None if complete else f"Incomplete or empty response: {choice.get('finish_reason')}",
                retries=attempt,
            )
            self.records.append(record)
            return content if complete else "", record


class MockCloudClient:
    def __init__(self, responses: dict[str, str] = None):
        self.responses = responses or {}
        self.records = []

    def chat(self, messages: list, temperature: float = 0.0, max_tokens: int = 1024) -> tuple[str, CallRecord]:
        raw = json.dumps(messages, sort_keys=True)
        key = hashlib.sha256(raw.encode()).hexdigest()[:16]
        content = self.responses.get(key, "def foo() -> int: return 42")
        import time
        record = CallRecord(
            request_id="mock-req-1",
            model="mock",
            prompt_hash=key,
            response_id="mock-resp-1",
            status="success",
            latency_ms=1.0,
            input_tokens=len(raw) // 4,
            output_tokens=len(content) // 4,
        )
        self.records.append(record)
        return content, record
