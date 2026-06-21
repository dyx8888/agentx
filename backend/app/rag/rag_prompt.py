import re  # 正则表达式用于解析引用标注 [来源1]、[来源2]
from typing import Optional  # 类型注解，Optional 表示可选的 system_instruction


RAG_SYSTEM_TEMPLATE = """你是一个基于知识库的问答助手。请基于以下参考资料回答用户的问题。

## 规则
1. 仅根据下方【参考资料】中的内容回答
2. 如果资料不足以回答，请明确回复："根据现有资料，我无法确定该问题的答案。建议您联系相关业务负责人确认。"
3. 回答时标注信息来源，如 [来源1]、[来源2]
4. 不要编造资料中不存在的信息
5. 保持回答简洁、专业"""  # 有参考资料时的 System Prompt，核心约束：仅基于参考资料回答，防止幻觉

RAG_EMPTY_TEMPLATE = """你是一个知识库问答助手。

## 注意
当前知识库中没有与用户问题相关的资料。请根据你的通用知识回答，但必须明确告知用户这一情况。"""  # 无参考资料时的降级 Template，要求明确告知用户资料来源不可靠

CITATION_PATTERN = re.compile(r'\[来源(\d+)\]')  # 预编译正则，匹配 [来源数字] 格式，提高解析效率


def build_rag_prompt(  # 构建 RAG Prompt 的核心函数
    query: str,  # 用户问题
    references: list[dict],  # 参考资料列表，每个 dict 包含 content/source_file/source_page
    system_instruction: Optional[str] = None,  # 可选的自定义 System Prompt，覆盖默认模板
) -> str:  # 返回完整的 Prompt 字符串
    if not references:  # 无参考资料时使用空模板
        return (
            (system_instruction or RAG_EMPTY_TEMPLATE)  # 优先使用自定义指令
            + "\n\n## 问题\n"  # 分隔符 + 问题标题
            + query  # 用户问题
        )

    system = system_instruction or RAG_SYSTEM_TEMPLATE  # 优先使用自定义指令
    parts = [system + "\n"]  # System Prompt 开头

    parts.append("## 参考资料")  # 参考资料标题
    for i, ref in enumerate(references, 1):  # 从 1 开始编号，与 [来源i] 对应
        source_info = ""  # 来源信息字符串
        source_file = ref.get("source_file", "")  # 文件名
        source_page = ref.get("source_page", 0)  # 页码
        if source_file:  # 有文件名时才显示
            source_info = f" (文件: {source_file}"  # 文件信息开头
            if source_page:  # 有页码时才追加
                source_info += f", 第{source_page}页"  # 页码信息
            source_info += ")"  # 闭合括号

        parts.append(f"\n[来源{i}]{source_info}")  # 引用标记 + 来源信息
        parts.append(ref.get("content", ""))  # 参考资料正文

    parts.append("\n---")  # 分隔线
    parts.append("## 问题")  # 问题标题
    parts.append(query)  # 用户问题

    return "\n".join(parts)  # 拼接为完整 Prompt


def build_system_prompt_with_context(context: str) -> str:  # 将上下文直接拼接到 System Prompt 后
    return RAG_SYSTEM_TEMPLATE + "\n\n## 参考资料\n" + context  # 简化版 Prompt 构建，适合已有完整上下文的场景


def parse_citations(text: str) -> list[int]:  # 从 LLM 回复中解析引用编号
    matches = CITATION_PATTERN.findall(text)  # 正则匹配所有 [来源数字]
    seen = set()  # 去重，避免重复引用
    result = []  # 结果列表
    for m in matches:  # 遍历匹配结果
        idx = int(m)  # 转为整数
        if idx not in seen:  # 未出现过
            seen.add(idx)  # 标记已见
            result.append(idx)  # 添加到结果
    return sorted(result)  # 排序返回，确保引用编号有序