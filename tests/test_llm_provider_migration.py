import json
import os
import sys
import hashlib
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from omegaconf import OmegaConf


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

survey_utils_stub = ModuleType("utils.utils")
survey_utils_stub.extract_json = lambda value: value
survey_utils_stub.get_hash = lambda value: hashlib.md5(value.encode("utf-8")).hexdigest()
previous_survey_utils = sys.modules.get("utils.utils")
sys.modules["utils.utils"] = survey_utils_stub

try:
    from src.agents.survey_agent.utils import api_call
finally:
    if previous_survey_utils is None:
        sys.modules.pop("utils.utils", None)
    else:
        sys.modules["utils.utils"] = previous_survey_utils

from src.config import DEFAULT_CONFIG_PATH, reload_config
from src.llm.provider_registry import (
    build_chat_completions_url,
    provider_required_settings,
    resolve_role_model,
    resolve_model,
    resolve_provider,
)
from src.llm.runtime_env import SUBPROCESS_ENV_KEYS, hydrate_subprocess_env


def _project_config(provider: str = "qwen"):
    return OmegaConf.create(
        {
            "llm": {
                "default_provider": provider,
                "providers": {
                    "openai": {
                        "api_key_env": "OPENAI_API_KEY",
                        "api_key": "openai-test-key",
                        "base_url": "https://api.openai.com/v1",
                        "api_style": "chat_completions",
                        "openhands_model_prefix": "openai",
                        "tokenizer_fallback": "o200k_base",
                        "token_limit_parameter": "",
                        "default_models": {
                            "survey": "gpt-5.4-mini",
                            "judge": "gpt-5.5",
                            "blog": "gpt-5.5",
                        },
                    },
                    "qwen": {
                        "api_key_env": "DASHSCOPE_API_KEY",
                        "api_key": "qwen-test-key",
                        "base_url": "https://dashscope.example/compatible-mode/v1",
                        "api_style": "chat_completions",
                        "openhands_model_prefix": "openai",
                        "tokenizer_fallback": "utf8_bytes",
                        "token_limit_parameter": "max_tokens",
                        "default_models": {
                            "survey": "qwen3.6-flash",
                            "judge": "qwen3.8-max",
                            "blog": "qwen3.8-max",
                        },
                    },
                },
                "models": {
                    "gpt-5.5": {
                        "provider": "openai",
                        "api_style": "chat_completions",
                        "capabilities": {"chat_completions": True},
                    },
                    "gpt-5.4-mini": {
                        "provider": "openai",
                        "api_style": "chat_completions",
                        "capabilities": {"chat_completions": True},
                    },
                    "qwen3-max-2026-01-23": {
                        "provider": "qwen",
                        "api_style": "responses",
                        "capabilities": {"responses": True},
                    },
                    "qwen3.6-flash": {
                        "provider": "qwen",
                        "api_style": "chat_completions",
                        "capabilities": {
                            "chat_completions": True,
                            "streaming": True,
                            "json_object": True,
                        },
                    },
                    "qwen3.8-max": {
                        "provider": "qwen",
                        "api_style": "chat_completions",
                        "capabilities": {
                            "chat_completions": True,
                            "streaming": True,
                        },
                    },
                    "qwen-image-3.0-pro": {
                        "provider": "qwen",
                        "api_style": "images",
                        "capabilities": {"image_generation": True},
                    },
                },
            },
            "blog": {
                "provider": provider,
                "model": "",
            },
        }
    )


def _survey_config(*, stream: bool = False, context_window: int = 100):
    return OmegaConf.create(
        {
            "APIInfo": {
                "llm_provider": "qwen",
                "llm_api_key": "",
                "llm_api_base_url": "",
                "llm_model_name": "qwen3.6-flash",
                "llm_max_context_length": context_window,
                "use_stream_mode": stream,
                "batch_chat_agent_worker": 1,
                "chat_timeout": 30,
                "low_flow_mode": False,
                "low_flow_latency": 0,
                "exponential_backoff": False,
                "exponential_backoff_time": 1,
                "exponential_backoff_max_time": 2,
            },
            "ModuleInfo": {
                "Judge": {
                    "provider": "qwen",
                    "judge_llm_api_key": "",
                    "judge_llm_api_base_url": "",
                    "model": "qwen3.8-max",
                }
            },
        }
    )


class _FakeResponse:
    def __init__(self, payload=None, lines=None):
        self.status_code = 200
        self._payload = payload or {}
        self._lines = lines or []
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)

    def raise_for_status(self):
        return None


class _CharacterEncoding:
    def encode(self, text):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


@pytest.fixture(autouse=True)
def _restore_global_config_cache():
    import src.config as config_module

    previous_config = config_module._config
    yield
    config_module._config = previous_config


@pytest.mark.parametrize(
    ("provider_name", "key_env", "base_url"),
    [
        ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1"),
        (
            "qwen",
            "DASHSCOPE_API_KEY",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ],
)
def test_default_config_resolves_openai_and_qwen(
    monkeypatch,
    provider_name,
    key_env,
    base_url,
):
    monkeypatch.setenv("QWENSCI_LLM_PROVIDER", provider_name)
    monkeypatch.setenv(key_env, "test-key")
    if provider_name == "qwen":
        monkeypatch.setenv("DASHSCOPE_BASE_URL", base_url)
        monkeypatch.delenv("SURVEY_LLM_MODEL", raising=False)
        monkeypatch.delenv("SURVEY_JUDGE_MODEL", raising=False)
        monkeypatch.delenv("BLOG_LLM_MODEL", raising=False)
    else:
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)

    config = reload_config(str(DEFAULT_CONFIG_PATH))
    provider = resolve_provider(config)

    assert provider.name == provider_name
    assert provider.api_key == "test-key"
    assert provider.base_url == base_url
    expected_survey_model = "qwen3.6-flash" if provider_name == "qwen" else "gpt-5.4-mini"
    assert resolve_role_model(config, "survey", provider_name).name == expected_survey_model


def test_default_config_prefers_qwen_without_provider_override(monkeypatch):
    monkeypatch.delenv("QWENSCI_LLM_PROVIDER", raising=False)

    config = reload_config(str(DEFAULT_CONFIG_PATH))

    assert resolve_provider(config).name == "qwen"
    assert config.survey.APIInfo.llm_provider == "qwen"


def test_openai_provider_accepts_legacy_api_base(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv(
        "OPENAI_API_BASE",
        "https://legacy-gateway.example/v1/chat/completions",
    )
    config = OmegaConf.create(
        {
            "llm": {
                "default_provider": "openai",
                "providers": {"openai": {"base_url": ""}},
            }
        }
    )

    provider = resolve_provider(config)

    assert provider.base_url == "https://legacy-gateway.example/v1/chat/completions"
    assert build_chat_completions_url(provider.base_url) == provider.base_url


def test_registered_model_rejects_wrong_provider():
    with pytest.raises(ValueError, match="registered for provider 'openai'"):
        resolve_model(_project_config(), "gpt-5.5", "qwen")


def test_chat_completions_url_accepts_base_or_complete_endpoint():
    base_url = "https://dashscope.example/compatible-mode/v1"
    endpoint = f"{base_url}/chat/completions"

    assert build_chat_completions_url(base_url) == endpoint
    assert build_chat_completions_url(endpoint) == endpoint


def test_doctor_requirements_use_current_provider_credentials():
    requirements = provider_required_settings(resolve_provider(_project_config()))

    assert requirements[0] == (
        "DASHSCOPE_API_KEY",
        True,
        "required by provider=qwen",
    )
    assert all(label != "OPENAI_API_KEY" for label, _, _ in requirements)


def test_dashscope_key_is_forwarded_to_pipeline_subprocess(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "subprocess-test-key")
    env = hydrate_subprocess_env({}, [DEFAULT_CONFIG_PATH.parent / ".missing-env"])

    assert "DASHSCOPE_API_KEY" in SUBPROCESS_ENV_KEYS
    assert env["DASHSCOPE_API_KEY"] == "subprocess-test-key"


def test_survey_non_streaming_qwen_fixture(monkeypatch):
    project_config = _project_config()
    request = {}

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )

    def fake_post(url, headers, json, timeout, stream):
        request.update(
            url=url,
            headers=headers,
            payload=json,
            timeout=timeout,
            stream=stream,
        )
        return _FakeResponse({"choices": [{"message": {"content": "survey answer"}}]})

    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config())

    assert agent.remote_chat("question", max_output_tokens=12) == "survey answer"
    assert request["url"].endswith("/compatible-mode/v1/chat/completions")
    assert request["headers"]["Authorization"] == "Bearer qwen-test-key"
    assert request["payload"]["model"] == "qwen3.6-flash"
    assert request["payload"]["max_tokens"] == 12
    assert request["stream"] is False


def test_survey_qwen_json_object_response_format(monkeypatch):
    project_config = _project_config()
    request = {}

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )

    def fake_post(url, headers, json, timeout, stream):
        request["payload"] = json
        return _FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config())

    assert agent.remote_chat(
        "return the requested structure",
        max_output_tokens=12,
        response_format="json_object",
    ) == '{"ok": true}'
    assert request["payload"]["response_format"] == {"type": "json_object"}
    assert (
        "Structured-output contract: return exactly one valid json object."
        in request["payload"]["messages"][0]["content"]
    )


def test_survey_batch_qwen_json_object_response_format(monkeypatch):
    """The batched path must preserve JSON mode all the way to the provider."""
    project_config = _project_config()
    request = {}

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )

    def fake_post(url, headers, json, timeout, stream):
        request["payload"] = json
        return _FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config())

    assert agent.supports_response_format("json_object") is True
    assert agent.batch_remote_chat(
        ["return json"],
        workers=1,
        future_timeout=2,
        max_output_tokens=12,
        response_format="json_object",
    ) == ['{"ok": true}']
    assert request["payload"]["response_format"] == {"type": "json_object"}


def test_json_object_parameter_error_is_not_retried_or_recast_as_validation(monkeypatch):
    project_config = _project_config()
    post_count = 0

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )

    def fake_post(_url, headers, json, timeout, stream):
        nonlocal post_count
        post_count += 1
        response = _FakeResponse()
        response.status_code = 400
        response.text = json_module.dumps(
            {
                "error": {
                    "code": "invalid_parameter_error",
                    "message": (
                        "'messages' must contain the word 'json' in some form, "
                        "to use 'response_format' of type 'json_object'."
                    ),
                }
            }
        )
        return response

    # The fake callback needs the module while its ``json`` argument shadows
    # the import name used by the test module.
    json_module = json
    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config())

    with pytest.raises(
        api_call.NonRetryableRequestError,
        match="Qwen rejected json_object mode",
    ) as exc_info:
        agent.batch_remote_chat_with_retry(
            ["assignment output"],
            validate_fn=lambda result, _info: (bool(result), result),
            max_retry=10,
            workers=1,
            future_timeout=2,
            max_output_tokens=12,
            response_format="json_object",
            info_dict={},
        )

    assert post_count == 1
    assert exc_info.value.status_code == 400
    assert "invalid_parameter_error" in exc_info.value.response_body


def test_deep_survey_limits_batch_chat_concurrency():
    config = OmegaConf.load(
        os.path.join(
            PROJECT_ROOT,
            "src",
            "agents",
            "survey_agent",
            "config",
            "deep_survey.yaml",
        )
    )

    assert config.APIInfo.batch_chat_agent_worker == 4
    assert config.APIInfo.chat_timeout == 600
    assert config.APIInfo.batch_chat_timeout == 600


def test_batch_chat_marks_unfinished_requests_for_retry(monkeypatch):
    class _Logger:
        def __init__(self):
            self.warnings = []

        def warning(self, message):
            self.warnings.append(message)

    completion_gate = threading.Event()
    logger = _Logger()
    agent = object.__new__(api_call.ChatAgent)
    agent.batch_workers = 2
    agent.config = SimpleNamespace(
        APIInfo=SimpleNamespace(batch_chat_timeout=1, low_flow_mode=False)
    )
    agent.logger = logger

    def fake_remote_chat(index, prompt, *_args):
        if prompt == "slow":
            completion_gate.wait(5)
        return index, prompt.upper()

    monkeypatch.setattr(agent, "_ChatAgent__remote_chat", fake_remote_chat)
    try:
        results = agent.batch_remote_chat(
            ["fast", "slow"],
            workers=2,
            future_timeout=0.05,
        )
    finally:
        completion_gate.set()

    assert results == ["FAST", None]
    assert any("marking 1 pending request" in warning for warning in logger.warnings)


def test_batch_chat_token_admission_backfills_capacity_without_wave_barrier(monkeypatch):
    class _Logger:
        def __init__(self):
            self.infos = []

        def info(self, message, *args):
            self.infos.append(message % args if args else message)

        def warning(self, *_args, **_kwargs):
            pass

    agent = object.__new__(api_call.ChatAgent)
    agent.batch_workers = 10
    agent.config = SimpleNamespace(
        APIInfo=SimpleNamespace(batch_chat_timeout=1, low_flow_mode=False)
    )
    agent.logger = _Logger()
    agent.estimate_tokens = {"slow": 7, "blocked": 6, "small": 3}.get

    slow_started = threading.Event()
    small_completed = threading.Event()
    release_slow = threading.Event()
    started_prompts = []

    def fake_remote_chat(index, prompt, *_args):
        started_prompts.append(prompt)
        if prompt == "slow":
            slow_started.set()
            release_slow.wait(1)
        if prompt == "small":
            small_completed.set()
        return index, prompt.upper()

    monkeypatch.setattr(agent, "_ChatAgent__remote_chat", fake_remote_chat)

    outcome = {}
    runner = threading.Thread(
        target=lambda: outcome.setdefault(
            "results",
            agent.batch_remote_chat(
                ["slow", "blocked", "small"],
                workers=3,
                future_timeout=1,
                max_in_flight_tokens=10,
            ),
        )
    )
    runner.start()
    try:
        assert slow_started.wait(0.3)
        # ``small`` fits beside the 7-token slow request. The 6-token prompt
        # does not, so a static wave implementation would leave this spare
        # capacity idle until ``slow`` finishes.
        assert small_completed.wait(0.3)
        assert "blocked" not in started_prompts
    finally:
        release_slow.set()
    runner.join(1)

    assert not runner.is_alive()
    assert outcome["results"] == ["SLOW", "BLOCKED", "SMALL"]
    assert any(
        "3 batch requests with rolling scheduler" in info
        for info in agent.logger.infos
    )


def test_token_admission_blocks_retry_wave_while_timed_out_request_is_still_running(
    monkeypatch,
):
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

    release_first_request = threading.Event()
    first_request_finished = threading.Event()
    started_prompts = []
    agent = object.__new__(api_call.ChatAgent)
    agent.batch_workers = 1
    agent.config = SimpleNamespace(
        APIInfo=SimpleNamespace(batch_chat_timeout=1, low_flow_mode=False)
    )
    agent.logger = _Logger()
    agent.estimate_tokens = lambda prompt: len(prompt)

    def fake_remote_chat(index, prompt, *_args):
        started_prompts.append(prompt)
        if prompt == "first":
            release_first_request.wait(1)
            first_request_finished.set()
        return index, prompt.upper()

    monkeypatch.setattr(agent, "_ChatAgent__remote_chat", fake_remote_chat)
    try:
        assert agent.batch_remote_chat(
            ["first"],
            workers=1,
            future_timeout=0.05,
            max_in_flight_tokens=5,
        ) == [None]
        # The first future cannot be cancelled after it enters the request
        # layer.  The second batch must wait for its token slot rather than
        # begin an overlapping large-context retry.
        assert agent.batch_remote_chat(
            ["retry"],
            workers=1,
            future_timeout=0.05,
            max_in_flight_tokens=5,
        ) == [None]
        assert started_prompts == ["first"]
    finally:
        release_first_request.set()
    assert first_request_finished.wait(1)


def test_batch_chat_uses_the_batch_request_timeout(monkeypatch):
    project_config = _project_config()
    request = {}

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )

    def fake_post(_url, headers, json, timeout, stream):
        request.update(payload=json, timeout=timeout, stream=stream)
        return _FakeResponse({"choices": [{"message": {"content": "batch answer"}}]})

    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config(context_window=20_000))

    assert agent.batch_remote_chat(
        ["batch question"],
        workers=1,
        future_timeout=2,
    ) == ["batch answer"]
    assert request["timeout"] == 2
    assert request["stream"] is False


def test_batch_retry_resubmits_only_failed_requests(monkeypatch):
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    agent = object.__new__(api_call.ChatAgent)
    agent.batch_workers = 2
    agent.model_name = "qwen3.6-flash"
    agent.exponential_backoff = False
    agent.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(batch_chat_timeout=1),
    )
    agent.logger = _Logger()
    submitted_batches = []

    def fake_batch_remote_chat(prompts, **_kwargs):
        submitted_batches.append(prompts)
        return ["first result", None] if len(submitted_batches) == 1 else ["retry result"]

    monkeypatch.setattr(agent, "batch_remote_chat", fake_batch_remote_chat)

    def validate_result(result, _info_dict):
        return (result is not None, result)

    assert agent.batch_remote_chat_with_retry(
        ["first prompt", "retry prompt"],
        validate_fn=validate_result,
        max_retry=2,
        info_dict={},
    ) == ["first result", "retry result"]
    assert submitted_batches == [["first prompt", "retry prompt"], ["retry prompt"]]


def test_survey_streaming_qwen_fixture(monkeypatch):
    project_config = _project_config()
    lines = [
        b'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}',
        b'data:{"choices":[{"delta":{"content":"visible "}}]}',
        b'data: {"choices":[{"delta":{"content":"answer"}}]}',
        b'data: [DONE]',
    ]

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )
    monkeypatch.setattr(
        api_call.requests,
        "post",
        lambda *args, **kwargs: _FakeResponse(lines=lines),
    )
    agent = api_call.ChatAgent(_survey_config(stream=True))

    assert agent.remote_chat("question", max_output_tokens=10) == "visible answer"


def test_survey_streaming_rejects_reasoning_without_final_content(monkeypatch):
    project_config = _project_config()
    lines = [
        b'data: {"choices":[{"delta":{"reasoning_content":"draft only"}}]}',
        b"data: [DONE]",
    ]

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: _CharacterEncoding(),
    )
    monkeypatch.setattr(
        api_call.requests,
        "post",
        lambda *args, **kwargs: _FakeResponse(lines=lines),
    )
    agent = api_call.ChatAgent(_survey_config(stream=True))

    with pytest.raises(api_call.requests.RequestException, match="without final content"):
        api_call.ChatAgent.remote_chat.__wrapped__(
            agent,
            "question",
            max_output_tokens=10,
        )


def test_survey_judge_can_use_independent_provider(monkeypatch):
    project_config = _project_config()
    config = _survey_config()
    config.ModuleInfo.Judge.provider = "openai"
    config.ModuleInfo.Judge.model = "gpt-5.5"
    monkeypatch.setattr(api_call, "load_config", lambda: project_config)

    agent = api_call.ChatAgent(config, use_different_api_for_judge=True)

    assert agent.provider_name == "openai"
    assert agent.model_name == "gpt-5.5"
    assert agent.remote_url == "https://api.openai.com/v1/chat/completions"
    assert agent.token == "openai-test-key"


def test_survey_qwen_tokenizer_fallback_and_long_input_truncation(monkeypatch):
    project_config = _project_config()
    request = {}

    monkeypatch.setattr(api_call, "load_config", lambda: project_config)
    monkeypatch.setattr(
        api_call.tiktoken,
        "encoding_for_model",
        lambda _model: (_ for _ in ()).throw(KeyError("unknown model")),
    )

    def fake_post(url, headers, json, timeout, stream):
        request["payload"] = json
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(
        api_call.tiktoken,
        "get_encoding",
        lambda _name: pytest.fail("Qwen fallback must not load a tiktoken BPE"),
    )
    monkeypatch.setattr(api_call.requests, "post", fake_post)
    agent = api_call.ChatAgent(_survey_config(context_window=10))

    assert agent.remote_chat("abcdefghijklmnopqrst", max_output_tokens=4) == "ok"
    assert request["payload"]["messages"][0]["content"] == "abcdef"


@pytest.mark.parametrize("model", ["qwen3-max-2026-01-23", "qwen-image-3.0-pro"])
def test_survey_rejects_non_chat_models(monkeypatch, model):
    project_config = _project_config()
    config = _survey_config()
    config.APIInfo.llm_model_name = model
    monkeypatch.setattr(api_call, "load_config", lambda: project_config)

    with pytest.raises(ValueError, match="missing required capabilities: chat_completions"):
        api_call.ChatAgent(config)


def test_blog_builds_qwen_openhands_provider_config_without_network():
    from src.agents.blog_agent.agent.llm_config import build_openhands_config

    project_config = _project_config()
    result = build_openhands_config(
        project_config,
        model="qwen3.8-max",
        provider="qwen",
    )

    assert result == {
        "api_key": "qwen-test-key",
        "model": "openai/qwen3.8-max",
        "base_url": "https://dashscope.example/compatible-mode/v1",
    }


def test_blog_uses_qwen_role_default_and_rejects_image_model():
    from src.agents.blog_agent.agent.llm_config import build_openhands_config

    project_config = _project_config()

    assert build_openhands_config(project_config)["model"] == "openai/qwen3.8-max"
    with pytest.raises(ValueError, match="missing required capabilities: chat_completions"):
        build_openhands_config(
            project_config,
            model="qwen-image-3.0-pro",
            provider="qwen",
        )


def test_blog_preserves_explicit_legacy_openai_config():
    from src.agents.blog_agent.agent.llm_config import build_openhands_config

    project_config = _project_config(provider="openai")
    project_config.blog.model = "gpt-5.5"
    project_config.blog.provider = ""
    project_config.blog.openai = {
        "api_key": "legacy-blog-key",
        "base_url": "https://blog-gateway.example/v1",
    }

    assert build_openhands_config(project_config) == {
        "api_key": "legacy-blog-key",
        "model": "openai/gpt-5.5",
        "base_url": "https://blog-gateway.example/v1",
    }


def test_pipeline_survey_forwards_active_config(monkeypatch, tmp_path):
    experiment_to_symbolic_stub = ModuleType("src.pipeline.experiment_to_symbolic")
    experiment_to_symbolic_stub.convert_ablation_to_symbolic_memory = lambda *args, **kwargs: None
    experiment_to_symbolic_stub.normalize_component_family = lambda value: value
    monkeypatch.setitem(
        sys.modules,
        "src.pipeline.experiment_to_symbolic",
        experiment_to_symbolic_stub,
    )
    survey_storage_stub = ModuleType(
        "src.agents.survey_agent.utils.topic_survey_storage"
    )
    survey_storage_stub.apply_topic_survey_paths = lambda *args, **kwargs: None
    survey_storage_stub.build_survey_artifact_paths = lambda *args, **kwargs: SimpleNamespace(
        base_dir="survey-output/topic",
        markdown_path="survey-output/topic/survey.md",
        json_path="survey-output/topic/survey.json",
        evaluation_path="survey-output/topic/evaluation.json",
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.survey_agent.utils.topic_survey_storage",
        survey_storage_stub,
    )
    contracts_stub = ModuleType("src.pipeline.contracts")
    contracts_stub.EXPERIMENT_ABLATION_RESULTS_REL = "ablation_results.json"
    contracts_stub.EXPERIMENT_SYMBOLIC_MEMORY_RECEIPT_REL = "symbolic_memory_receipt.json"
    monkeypatch.setitem(sys.modules, "src.pipeline.contracts", contracts_stub)
    from src.pipeline import run_loop

    config_path = tmp_path / "custom-qwen.yaml"
    config_path.write_text("survey: {}\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(run_loop, "_get_subprocess_env", lambda: {})

    def fake_run_command(command, env=None):
        captured["command"] = command
        captured["env"] = env
        return 0

    monkeypatch.setattr(run_loop, "run_command", fake_run_command)

    assert run_loop.run_survey("topic", "survey-output", str(config_path)) is True
    config_path_index = captured["command"].index("--config-path")
    config_name_index = captured["command"].index("--config-name")
    runtime_config_path = Path(captured["env"]["QWENSCI_CONFIG"])
    assert captured["command"][config_path_index + 1] == str(runtime_config_path.parent)
    assert captured["command"][config_name_index + 1] == runtime_config_path.stem
    assert captured["env"]["QWENSCI_CONFIG_PATH"] == str(runtime_config_path)
    assert not any("BasicInfo.topic=" in item for item in captured["command"])
