import os
import sys
from types import SimpleNamespace


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules import fulltext_http
from modules.fulltext_http import FulltextHttpClient


class _Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_fulltext_http_client_retries_rate_limit_with_identifying_headers(monkeypatch):
    client = FulltextHttpClient(
        SimpleNamespace(
            fulltext_http_max_retries=1,
            fulltext_http_retry_base_delay_seconds=0.1,
            fulltext_http_retry_max_delay_seconds=1,
            fulltext_connect_timeout_seconds=3,
            fulltext_read_timeout_seconds=9,
        ),
        contact_email="researcher@example.org",
    )
    session = _Session([_Response(429, {"Retry-After": "0"}), _Response(200)])
    client._local.session = session
    sleeps = []
    monkeypatch.setattr(fulltext_http.time, "sleep", sleeps.append)

    response = client.get("https://repository.example/paper.pdf", headers={"Range": "bytes=0-"})

    assert response.status_code == 200
    assert session.calls[0][1]["headers"]["Range"] == "bytes=0-"
    assert "academic OA full-text retrieval" in session.calls[0][1]["headers"]["User-Agent"]
    assert "researcher@example.org" in session.calls[0][1]["headers"]["User-Agent"]
    assert session.calls[0][1]["timeout"] == (3.0, 9.0)
    assert sleeps == [0.0]
