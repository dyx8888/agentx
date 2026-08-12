"""
感知管道 - 输入过滤器
验证和清洗用户输入：长度检查、有害内容清除、空白规范化
"""
# 模块 docstring 列出三个核心职责，让后续维护者一眼看清职责边界

import re  # 引入正则引擎，因为有害模式匹配和空白规范化都依赖正则表达式的灵活性

from app.core.logging import get_logger  # 使用项目统一日志门面，确保日志格式和输出目标一致

logger = get_logger(__name__)  # 模块级 logger，使用 __name__ 确保日志来源可追溯到本模块

MAX_INPUT_LENGTH = (
    16000  # 限制在 16k 字符，既覆盖绝大多数合法输入，又能防止恶意超长字符串耗尽 LLM token 预算
)
HARMFUL_PATTERNS = [  # 用列表而非字典存储模式，是为了支持后续扩展时只需 append 即可，无需考虑键冲突
    (r"<script[^>]*>.*?</script>", "script_tag"),  # XSS 攻击最常见的载体，必须优先过滤
    (r"javascript\s*:", "javascript_uri"),  # 伪协议注入，即使没有 script 标签也能执行恶意代码
    (
        r"on\w+\s*=\s*[\"'][^\"']*[\"']",
        "inline_event_handler",
    ),  # 内联事件处理器也是 XSS 变体，不可遗漏
    (r"<iframe[^>]*>", "iframe_tag"),  # iframe 可用于嵌入钓鱼页面，属于高风险标签
    (r"<object[^>]*>", "object_tag"),  # object 标签可加载外部插件，潜在攻击面
    (r"<embed[^>]*>", "embed_tag"),  # embed 类似 object，同样有外部内容加载风险
    (r"\bDROP\s+TABLE\b", "sql_drop", re.IGNORECASE),  # SQL 注入的破坏性操作，大小写不敏感避免绕过
    (r"\bDELETE\s+FROM\b", "sql_delete", re.IGNORECASE),  # 数据库删除语句，即使不执行也要清洗掉
    (r"\bUNION\s+SELECT\b", "sql_union", re.IGNORECASE),  # SQL 联合查询注入的典型特征，必须拦截
    (r"\bINSERT\s+INTO\b", "sql_insert", re.IGNORECASE),  # 插入语句同样危险，防止数据投毒
    (r"(?:\b|_)exec\s*\((?:\s*['\"])", "exec_call"),  # 代码执行函数调用，所有变体都需要拦截
    (r"(?:\b|_)eval\s*\((?:\s*['\"])", "eval_call"),  # eval 同样危险，动态执行任意代码的入口
    (r"\\x[0-9a-fA-F]{2}", "hex_escape"),  # 十六进制转义常用于绕过文本过滤器，必须识别并清除
    (r"\x00", "null_byte"),  # null 字节可截断 C 语言字符串处理，引发意外行为
]


class InputFilter:
    """感知管道输入过滤器 - 验证和清洗原始用户输入"""

    @classmethod
    def filter(cls, text: str) -> str:  # 类方法设计使调用方无需实例化，适合无状态过滤场景
        """
        过滤用户输入：检查长度 → 移除有害内容 → 规范化空白

        Args:
            text: 原始用户输入文本

        Returns:
            清洗后的文本

        Raises:
            ValueError: 输入为空或超过最大长度限制
        """
        if text is None:  # None 先于 strip() 检查，避免 AttributeError
            raise ValueError("输入不能为空")

        text = text.strip()  # 先去除首尾空白再判空，因为纯空白输入同样无意义

        if not text:  # 空字符串同样拒绝，防止下游 LLM 收到无效输入
            raise ValueError("输入不能为空字符串")

        if len(text) > MAX_INPUT_LENGTH:  # 长度检查放在有害内容之前，因为超长输入先拒绝更高效
            raise ValueError(f"输入长度超过限制 ({len(text)} > {MAX_INPUT_LENGTH})，请缩短后重试")

        text = cls._remove_harmful_content(
            text
        )  # 先清有害再规范空白，因为有害内容可能包含刻意构造的空白

        text = cls._normalize_whitespace(text)  # 空白规范放到最后，确保前面的操作不受不规范空白干扰

        logger.debug(
            "input_filtered", original_length=len(text), filtered_length=len(text)
        )  # debug 级别避免生产环境日志洪水

        return text

    @classmethod
    def _remove_harmful_content(cls, text: str) -> str:  # 私有方法，外部只应通过 filter() 调用
        """移除有害内容模式"""
        for pattern_data in HARMFUL_PATTERNS:  # 遍历所有模式，每个希望命中的都会被替换为空字符串
            if isinstance(
                pattern_data, tuple
            ):  # 三元组 (pattern, name, flags)，二元组 (pattern, name)
                if len(pattern_data) == 3:  # 有三元组才有 flags，用长度判断更简洁
                    pattern, _, flags = pattern_data  # 解包时忽略 name 标签，因为这里只关心匹配逻辑
                else:  # 二元组没有 flags 参数
                    pattern, _, *rest = pattern_data  # 用 *rest 兜底兼容未来可能扩展的更多字段
                    flags = 0  # 无 flags 时设置默认值，防止 UnboundLocalError
            else:  # 兼容纯字符串模式，虽然当前列表全是元组，但保留扩展性
                pattern = pattern_data
                flags = 0
            text = re.sub(
                pattern, "", text, flags=flags
            )  # 替换为空字符串而非标记，因为有害内容不应留存任何痕迹
        return text

    @classmethod
    def _normalize_whitespace(cls, text: str) -> str:  # 独立方法便于单元测试单独验证空白处理逻辑
        """规范化空白字符"""
        text = text.replace("\r\n", "\n").replace(
            "\r", "\n"
        )  # 统一换行符为 \n，Windows/Mac/Linux 三种风格都要覆盖
        text = re.sub(
            r"\n{3,}", "\n\n", text
        )  # 超过 2 个连续换行压缩为 2 个，保留段落间距但避免大片空白
        text = re.sub(r" {2,}", " ", text)  # 多个空格压缩为单个，减少 LLM 的 token 浪费
        text = re.sub(r"\t+", " ", text)  # 制表符转为空格，因为 LLM 对 tab 的处理不一致
        return text.strip()  # 结尾再次 strip，确保规范化过程中不会引入首尾空白
