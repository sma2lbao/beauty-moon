from app.services.prompt_builder import build_rag_prompt, render_prompt


def test_render_prompt_replaces_body():
    tpl = "PREFIX\n{body}\nSUFFIX"
    out = render_prompt(tpl, question="Q?", context="CTX")
    assert out.startswith("PREFIX")
    assert out.endswith("SUFFIX")
    assert "Q?" in out and "CTX" in out


def test_build_rag_prompt_backward_compatible():
    # 旧签名仍可用，输出含中文默认外壳
    out = build_rag_prompt(question="Q?", context="CTX")
    assert "基于文档的问答助手" in out
    assert "Q?" in out