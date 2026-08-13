import json

from deerflow.agents.rumor_agent import tools as rumor_tools


class _FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_parse_unknown_does_not_match_no() -> None:
    signal = rumor_tools._parse_model_signal("Unknown")

    assert signal.label == "uncertain"
    assert signal.rationale == ""


def test_parse_legacy_labels_accepts_only_exact_tokens_with_outer_punctuation() -> None:
    assert rumor_tools._parse_model_signal("  'Yes'。 ").label == "rumor"
    assert rumor_tools._parse_model_signal("No.").label == "non_rumor"
    assert rumor_tools._parse_model_signal("Unknown！").label == "uncertain"
    assert rumor_tools._parse_model_signal("The answer is No").status == "invalid_output"


def test_parse_json_signal() -> None:
    signal = rumor_tools._parse_model_signal('```json\n{"label":"rumor","rationale":"来源与事实冲突"}\n```')

    assert signal.label == "rumor"
    assert signal.rationale == "来源与事实冲突"


def test_parse_invalid_output_falls_back_to_uncertain() -> None:
    signal = rumor_tools._parse_model_signal("大概是真的，但我不确定")

    assert signal.label == "uncertain"
    assert signal.rationale == "模型未返回可识别的结构化标签"


def test_rumor_check_uses_configured_openai_compatible_service(
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse({"choices": [{"message": {"content": '{"label":"non_rumor","rationale":"文本与已知事实一致"}'}}]})

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example/v1/")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "openai_chat")
    monkeypatch.setenv("RUMOR_MODEL_API_KEY", "secret-token")
    monkeypatch.setenv("RUMOR_MODEL_NAME", "rumorbuster-qwen-2.5-3b")

    result = json.loads(rumor_tools.rumor_check_tool.invoke({"claim": "测试主张"}))

    assert captured["url"] == "http://model.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"]["model"] == "rumorbuster-qwen-2.5-3b"
    assert captured["json"]["temperature"] == 0
    assert result["status"] == "ok"
    assert result["role"] == "auxiliary_signal"
    assert result["label"] == "non_rumor"
    assert result["authoritative"] is False
    assert "confidence" not in result


def test_rumor_check_uses_modelscope_chat_contract(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse(
            {
                "response": " Yes。 ",
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 1,
                    "total_tokens": 81,
                },
            }
        )

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")
    monkeypatch.setenv("RUMOR_MODEL_NAME", "congyang/fine-tuned-qwen")
    monkeypatch.setenv("RUMOR_MODEL_TIMEOUT_SECONDS", "20")

    result = rumor_tools.classify_claim_text("待检测主张")

    assert captured["url"] == "http://model.example/v1/chat"
    assert captured["json"]["messages"][1] == {"role": "user", "content": "待检测主张"}
    assert captured["json"]["max_new_tokens"] == 8
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["top_p"] == 1
    assert captured["json"]["repetition_penalty"] == 1
    assert 19 < captured["timeout"] <= 20
    assert result["status"] == "ok"
    assert result["raw_label"] == "Yes"
    assert result["mapped_label"] == "rumor"
    assert result["usage"]["total_tokens"] == 81
    assert len(result["input_hash"]) == 64
    assert result["request_id"]
    assert result["called_at"].endswith("+00:00")


def test_modelscope_base_url_may_already_end_in_v1(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        return _FakeResponse({"response": "Unknown", "usage": {}})

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example/v1/")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")

    result = rumor_tools.classify_claim_text("待检测主张")

    assert captured["url"] == "http://model.example/v1/chat"
    assert result["mapped_label"] == "uncertain"


def test_classifier_audit_never_contains_api_key(monkeypatch) -> None:
    def fake_post(url, *, json, headers, timeout):
        return _FakeResponse({"response": "No", "usage": {}})

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")
    monkeypatch.setenv("RUMOR_MODEL_API_KEY", "do-not-leak-this-key")

    result = rumor_tools.classify_claim_text("待检测主张")

    assert "do-not-leak-this-key" not in json.dumps(result, ensure_ascii=False)


def test_classifier_retries_one_502_then_succeeds(monkeypatch) -> None:
    calls = 0

    def fake_post(url, *, json, headers, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FakeResponse({}, status_code=502)
        return _FakeResponse({"response": "No", "usage": {}})

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")

    result = rumor_tools.classify_claim_text("待检测主张")

    assert calls == 2
    assert result["mapped_label"] == "non_rumor"


def test_classifier_does_not_retry_business_error(monkeypatch) -> None:
    calls = 0

    def fake_post(url, *, json, headers, timeout):
        nonlocal calls
        calls += 1
        raise rumor_tools.requests.exceptions.HTTPError("bad request")

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")

    result = rumor_tools.classify_claim_text("待检测主张")

    assert calls == 1
    assert result["status"] == "unavailable"


def test_rumor_check_returns_safe_unavailable_payload(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise rumor_tools.requests.exceptions.Timeout("slow model")

    monkeypatch.setattr(rumor_tools.requests, "post", fake_post)
    monkeypatch.setenv("RUMOR_MODEL_BASE_URL", "http://model.example/v1")
    monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "openai_chat")

    result = json.loads(rumor_tools.rumor_check_tool.invoke({"claim": "测试主张"}))

    assert result["status"] == "unavailable"
    assert result["role"] == "auxiliary_signal"
    assert result["label"] == "uncertain"
    assert result["authoritative"] is False
    assert result["subclaims"][0]["status"] == "unavailable"
    assert "confidence" not in result
