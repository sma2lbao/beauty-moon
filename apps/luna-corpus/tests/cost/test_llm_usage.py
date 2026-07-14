"""LLM 层 token 用量捕获。"""
import asyncio
from types import SimpleNamespace

from app.services import llm
from app.services.llm import TokenUsage, extract_usage


def test_extract_usage_from_metadata():
    resp = SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 34})
    usage = extract_usage(resp, "ark", "m")
    assert usage == TokenUsage(input_tokens=12, output_tokens=34, model="m", provider="ark")


def test_extract_usage_missing_returns_none():
    resp = SimpleNamespace()  # 无 usage_metadata
    assert extract_usage(resp, "ark", "m") is None


def test_generate_response_with_usage(monkeypatch):
    fake_resp = SimpleNamespace(
        content="hello",
        usage_metadata={"input_tokens": 5, "output_tokens": 7},
    )

    class FakeChat:
        def invoke(self, _prompt):
            return fake_resp

    monkeypatch.setattr(llm, "get_chat_model", lambda: FakeChat())
    monkeypatch.setattr(llm.settings, "llm_provider", SimpleNamespace(value="ark"))
    monkeypatch.setattr(llm.settings, "ark_model", "deepseek")

    text, usage = llm.generate_response_with_usage("q")
    assert text == "hello"
    assert usage.input_tokens == 5
    assert usage.output_tokens == 7


def test_streaming_fills_usage_holder(monkeypatch):
    class Chunk(SimpleNamespace):
        pass

    async def fake_astream(_prompt):
        yield SimpleNamespace(content="a", usage_metadata=None)
        yield SimpleNamespace(
            content="b", usage_metadata={"input_tokens": 3, "output_tokens": 4}
        )

    class FakeChat:
        def astream(self, prompt):
            return fake_astream(prompt)

    monkeypatch.setattr(llm, "get_chat_model", lambda: FakeChat())
    monkeypatch.setattr(llm.settings, "llm_provider", SimpleNamespace(value="ark"))
    monkeypatch.setattr(llm.settings, "ark_model", "deepseek")

    holder: dict = {}

    async def run():
        out = ""
        async for tok in llm.generate_streaming_response("q", usage_holder=holder):
            out += tok
        return out

    out = asyncio.run(run())
    assert out == "ab"
    assert holder["usage"].input_tokens == 3
    assert holder["usage"].output_tokens == 4
