def build_user(prompt: str, passages: list, tool_text: str) -> str:
    lines = [prompt, "", "资料:"]
    for item in passages:
        lines.append(f"[{item['doc_id']}] {item['title']}：{item['text'][:180]}")
    if tool_text:
        lines.append("工具结果：" + tool_text)
    return "\n".join(lines)
