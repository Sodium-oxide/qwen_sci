from src.agents.idea_agent.utils.workflow.ligagent_utils import generate_idea_introduction


class _Logger:
    def __init__(self):
        self.warning_messages = []
        self.info_messages = []

    def warning(self, message, *args):
        self.warning_messages.append(message % args if args else message)

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)


def _prompt_template():
    return "Topic: {topic}\nMature idea: {mature_idea}\nIdea: {idea}\nPapers: {papers}"


def _generate(chat_fn, logger, **kwargs):
    return generate_idea_introduction(
        chat_fn=chat_fn,
        prompt_template=_prompt_template(),
        model="qwen3.8-flash",
        topic="A compact-object topic",
        best_entry={"title": "A test idea", "abstract": "A test abstract."},
        paper_entries=[{"paper_id": "p1", "title": "Paper 1", "summary": "Evidence."}],
        mature_idea="A mature anchor",
        logger=logger,
        **kwargs,
    )


def test_introduction_requests_json_object_and_accepts_valid_payload():
    calls = []

    def chat_fn(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return '{"introduction":"A complete introduction."}'

    logger = _Logger()
    result = _generate(chat_fn, logger)

    assert result == "A complete introduction."
    assert len(calls) == 1
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert calls[0][1]["max_output_tokens"] == 25600
    assert not logger.warning_messages


def test_introduction_repairs_incomplete_json_before_fallback():
    responses = ['{"introduction":"truncated', '{"introduction":"Repaired introduction."}']
    calls = []

    def chat_fn(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return responses.pop(0)

    logger = _Logger()
    result = _generate(chat_fn, logger)

    assert result == "Repaired introduction."
    assert len(calls) == 2
    assert calls[1][1]["response_format"] == {"type": "json_object"}
    assert "previous response violated the JSON contract" in calls[1][0]
    assert any("requesting repair" in message for message in logger.warning_messages)
    assert logger.info_messages


def test_introduction_uses_fallback_after_bounded_repair_attempts():
    calls = []

    def chat_fn(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return '{"introduction":"still truncated'

    logger = _Logger()
    result = _generate(chat_fn, logger, json_repair_attempts=2)

    assert "A test idea refines the mature idea" in result
    assert len(calls) == 3
    assert any("using fallback" in message for message in logger.warning_messages)
