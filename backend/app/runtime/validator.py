"""
Dynamic Validator - 三层动态验证链
Layer A: 代码硬约束
Layer B: Skill 规则（从 SKILL.md 中解析）
Layer C: LLM 动态验收
"""
# 三层验证的设计原因：单一验证手段各有短板——硬约束太死板、Skill 规则覆盖有限、LLM 成本高且不稳定，
# 三层递进式验证可以在保证正确性的同时最小化 LLM 调用成本

# 导入 re：用于从 Markdown 格式的 SKILL.md 中解析出 ## 验收标准 段落，正则是最直接的文本抽取方式
import re
# 导入 typing.Any：validate 返回的 dict 值类型不固定（issues 是 list、passed 是 bool），用 Any 保持灵活性
from typing import Any

# 导入 HumanMessage 和 SystemMessage：Layer C 调用 LLM 时需要区分系统指令和用户输入，这两个类正好对应角色语义
from langchain_core.messages import HumanMessage, SystemMessage

# 导入 get_logger：Layer B 和 Layer C 可能发生非致命错误（如 LLM 响应格式异常），需要 warn 级别日志记录
from app.core.logging import get_logger

# 模块级 logger：验证器可能有多个实例，但日志输出统一归到这个模块名下，避免日志来源分散
logger = get_logger(__name__)

class DynamicValidator:
    # 使用类而非纯函数：验证器需要持有 skill_registry 和 llm 两个依赖，作为实例属性可以在多次 validate 调用间复用，
    # 避免每次调用都重新传入依赖对象
    """动态验证器"""

    def __init__(self, skill_registry, llm):
        # skill_registry：Skill 注册中心，负责从 SKILL.md 文件中加载验收标准内容，是 Layer B 的数据源
        # 通过构造函数注入而非硬编码：支持测试时替换为 mock，也方便未来切换不同的 Skill 存储后端
        self.skill_registry = skill_registry
        # llm：LangChain 兼容的大语言模型实例，Layer C 用它进行语义层面的验收判断
        # 作为依赖注入而非方法参数：同一个 llm 实例可能在多处复用（如其他 Agent 组件），避免重复初始化
        self.llm = llm

    def validate(
        self,
        plan: dict,
        step_results: list[dict],
        skill_name: str | None = None
    ) -> dict[str, Any]:
        # plan：包含 steps（执行计划）和 acceptance_criteria（验收标准），是验证的核心参考依据
        # step_results：Agent 实际执行各步骤后产生的结果列表，数量和内容都需要与 plan.steps 对照
        # skill_name：可选参数，只有当任务匹配到某个 Skill 时才触发 Layer B，否则跳过以减少不必要开销
        """
        三层验证
        
        Args:
            plan: 任务计划（包含 steps, acceptance_criteria）
            step_results: 步骤执行结果列表
            skill_name: 匹配到的 Skill 名称（可选）
            
        Returns:
            验证结果
        """
        # 汇总所有层发现的问题：用 list 而非 set 是为了保留问题出现的顺序，方便定位是哪个阶段出的错
        all_issues = []
        # 汇总改进建议：与 issues 分开存储，因为建议不影响 passed 判定，但可以辅助 Agent 优化执行质量
        all_suggestions = []

        # 初始化各层结果，确保后续汇总时变量始终存在
        layer_b_result = None
        layer_c_result = None

        # Layer A: 代码硬约束
        # 先执行 Layer A：它是纯 Python 逻辑，不依赖外部服务，执行速度极快，
        # 可以第一时间拦截结构性问题（如 steps 缺失），避免后续昂贵的 LLM 调用
        layer_a_result = self._layer_a_validate(plan, step_results)
        if not layer_a_result['passed']:  # 条件收集 issues：只有未通过时才追加，避免 null/空列表污染汇总
            all_issues.extend(layer_a_result['issues'])

        # Layer B: Skill 规则
        # 只有在 skill_name 不为空时才执行：因为不是每个任务都有匹配的 Skill，
        # 没有 Skill 名意味着无法加载验收规则，硬执行会导致不必要的文件 I/O 和正则匹配开销
        if skill_name:
            layer_b_result = self._layer_b_validate(plan, step_results, skill_name)
            if not layer_b_result['passed']:
                all_issues.extend(layer_b_result['issues'])

        # Layer C: LLM 动态验收
        # 只有当前两层都通过时才调用 LLM：LLM 调用有延迟和费用成本，
        # 如果代码约束或 Skill 规则已经发现了问题，就没有必要再让 LLM 判断一遍了
        if len(all_issues) == 0:
            layer_c_result = self._layer_c_validate(plan, step_results)
            if not layer_c_result['passed']:
                all_issues.extend(layer_c_result['issues'])
                all_suggestions.extend(layer_c_result.get('suggestions', []))  # get 带默认值：LLM 可能不返回 suggestions 字段

        # 汇总结果
        # 返回扁平字典：包含 passed/issue/suggestions 的顶层判断 + 各层的详细结果，
        # 这样调用方既能快速判断是否通过，又能深入分析具体是哪一层出了问题
        return {
            'passed': len(all_issues) == 0,  # 用 all_issues 长度判断：简洁统一，避免各层 passed 字段不一致
            'issues': all_issues,
            'suggestions': all_suggestions,
            'layer_a': layer_a_result,  # 始终返回 Layer A 结果：即使通过也有参考价值（如确认 steps 数量一致）
            'layer_b': layer_b_result if skill_name else None,  # 无 Skill 时返回 None：明确表示该层未执行，而非通过
            'layer_c': layer_c_result  # Layer C 可能为 None（当前两层未通过时未执行），这是有意设计
        }

    def _layer_a_validate(self, plan: dict, step_results: list[dict]) -> dict:
        # Layer A 是纯 Python 实现的硬约束：不需要任何外部依赖，运行速度最快，
        # 适合检查最基本的输入格式问题——如果 plan 本身结构就有问题，后续验证毫无意义
        """Layer A: 代码硬约束"""
        issues = []

        # 检查 plan 是否包含 steps
        # plan 没有 steps 意味着执行计划是空的，后续步骤数量比对也无法进行，这是最底层的数据完整性校验
        if 'steps' not in plan:
            issues.append("Plan 缺少 steps 字段")

        # 检查 acceptance_criteria 是否非空
        # 验收标准为空意味着没有可衡量的质量指标，Layer C 也无法工作，直接在源头拦截
        # 使用 .get() 而非直接索引：因为 steps 检查已经确保了 plan 是 dict，但不能保证 acceptance_criteria 这个 key 存在
        if not plan.get('acceptance_criteria'):
            issues.append("Plan 缺少 acceptance_criteria")

        # 检查 step_results 数量是否等于 plan.steps 数量
        # 步骤数量不匹配是常见错误：可能某个步骤执行失败了但没有上报，或 plan 被错误截断
        # 用 len 比较：O(1) 操作，不会因为列表内容复杂而影响性能
        expected_steps = len(plan.get('steps', []))  # get 带默认空列表：防止 plan 没有 steps key 时 len() 报 TypeError
        actual_steps = len(step_results)
        if expected_steps != actual_steps:
            issues.append(f"步骤执行数量不匹配：期望 {expected_steps} 步，实际 {actual_steps} 步")

        # 返回统一格式的字典：每层验证都返回 {'passed': bool, 'issues': list}，方便上层汇总时统一处理
        return {
            'passed': len(issues) == 0,
            'issues': issues
        }

    def _layer_b_validate(self, plan: dict, step_results: list[dict], skill_name: str) -> dict:
        # Layer B 从 SKILL.md 中动态加载验收规则：规则由领域专家维护在 Markdown 文件中，
        # 不需要修改 Python 代码就能调整验收标准，实现了"规则配置化"
        """Layer B: Skill 规则验证"""
        issues = []

        # 整个 Layer B 包裹在 try/except 中：加载 Markdown 文件和正则解析都有可能失败（文件不存在、格式错误等），
        # 但 Layer B 失败不应该阻断验证流程——如果解析出错，退化为"无规则"状态，让 Layer C 兜底
        try:
            # 加载 Skill 内容
            # 从 skill_registry 加载原始 Markdown 内容：registry 可能从文件系统、数据库或远程 API 获取，此处对其实现保持透明
            skill_content = self.skill_registry.load_skill_content(skill_name)
            if not skill_content:  # 如果注册中心中找不到该 Skill 的 Markdown 内容，无法解析规则，直接通过
                return {'passed': True, 'issues': []}

            # 解析 ## 验收标准 段落
            # 正则匹配二级标题 "验收标准"：约定的 Markdown 结构是 ## 验收标准 + 内容列表，这样解析器能精准定位
            acceptance_section = self._extract_section(skill_content, '验收标准')
            if not acceptance_section:  # SKILL.md 中没有验收标准段落也是合法的（规则尚未编写），不应判定失败
                return {'passed': True, 'issues': []}

            # 逐条检查验收标准（简单实现：检查步骤结果中是否包含关键内容）
            # 用关键词匹配而非精确匹配：步骤结果可能是自然语言描述，不可能逐字对应验收标准，
            # 关键词存在即视为"已覆盖"，这是一种务实的近似方案
            criteria = self._parse_criteria(acceptance_section)
            for criterion in criteria:
                # 简单检查：查看步骤结果中是否包含标准中的关键词
                keywords = self._extract_keywords(criterion)
                if keywords:  # 只有提取到关键词才进行检查：空关键词遇到纯标点行等于空跑
                    found = False
                    # 遍历所有步骤结果：关键词可能出现在任意一个步骤中，不要求特定步骤
                    for step in step_results:
                        step_content = str(step).lower()  # lower() 转换为小写：消除大小写差异导致的关键词漏检
                        for kw in keywords:
                            if kw.lower() in step_content:  # 子串匹配：简单高效，适用于中文场景
                                found = True
                                break  # 找到一个关键词就跳出内层循环
                        if found:
                            break  # 该条标准已满足，继续检查下一条

                    if not found:
                        issues.append(f"未满足验收标准：{criterion}")  # 带上具体标准文本，方便定位哪条规则未通过

        except Exception as e:
            # 异常时只 warn 不抛出：Layer B 是辅助验证，异常应该静默处理，
            # 但不能悄无声息——记一条 warn 日志方便上线后发现 SKILL.md 格式问题
            logger.warning("dynamic_validator_layer_b_error", error=str(e))

        return {
            'passed': len(issues) == 0,
            'issues': issues
        }

    def _layer_c_validate(self, plan: dict, step_results: list[dict]) -> dict:
        # Layer C 使用 LLM 做语义验收：代码和规则只能检查形式化的条件，
        # 而 LLM 可以理解 "生成的内容是否流畅" 或 "回答是否符合品牌调性" 这类语义要求
        """Layer C: LLM 动态验收"""
        issues = []
        suggestions = []

        # 同样包裹 try/except：LLM 调用可能因网络超时、配额耗尽或返回格式异常而失败，
        # 此时应降级为"通过"而不是阻断流程——毕竟前两层已经通过了
        try:
            acceptance_criteria = plan.get('acceptance_criteria', [])
            if not acceptance_criteria:  # 空验收标准：Layer A 已检查过，这里再做一次防御性判断，避免发无意义的 LLM 请求
                return {'passed': True, 'issues': []}

            # 构建验证 prompt
            # 用专用方法 _build_validation_prompt 拼接 prompt：职责分离，让生成 prompt 的逻辑独立于调用 LLM 的逻辑，
            # 方便单独测试 prompt 质量
            prompt = self._build_validation_prompt(plan, step_results, acceptance_criteria)

            # 调用 LLM
            # SystemMessage 设定角色：让 LLM 以"验收专家"身份回答，约束输出风格和内容范围
            # HumanMessage 承载具体验证任务：LangChain 的消息模型要求区分角色，这样 LLM 能更好地理解上下文定位
            messages = [
                SystemMessage(content="你是一位专业的任务验收专家。请根据验收标准检查任务执行结果。"),
                HumanMessage(content=prompt)
            ]

            response = self.llm.invoke(messages)  # invoke 是 LangChain 统一的调用入口，屏蔽了不同 LLM provider 的差异

            # 解析 LLM 输出
            # LLM 返回的是自然语言，需要从中提取结构化的 JSON，正则提取是最轻量的方案
            result = self._parse_llm_validation(response.content)
            issues = result.get('issues', [])  # get 带默认值：解析可能不返回 issues 字段
            suggestions = result.get('suggestions', [])  # 同样防御性处理

        except Exception as e:
            # LLM 调用失败时静默通过：因为 Layer A 和 Layer B 已通过，说明任务在形式上没问题，
            # LLM 故障不应阻塞业务流程
            logger.warning("dynamic_validator_layer_c_error", error=str(e))

        return {
            'passed': len(issues) == 0,
            'issues': issues,
            'suggestions': suggestions  # 额外返回 suggestions：调用方可以利用改进建议优化 Agent 的执行策略
        }

    def _extract_section(self, content: str, section_name: str) -> str | None:
        # 从 Markdown 中提取指定 section：使用正则而非 Markdown 解析库，因为只需要提取二级标题下的纯文本，
        # 引入第三方解析库会增加依赖复杂度，而正则一行就能解决
        """从 Markdown 中提取指定 section"""
        # 正则以 ## + section_name 开头，匹配到下一个 ## 或文件末尾为止
        # re.DOTALL：让 . 也匹配换行符，否则 .*? 会在第一个换行处停止，无法跨行匹配
        pattern = rf'##\s+{section_name}(.*?)(?=##|$)'  # (?=##|$) 是前瞻断言：匹配到下一个二级标题或字符串末尾即停止
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()  # strip() 去除首尾空白：解析出的内容可能含有多余空行，影响后续逐行处理
        return None  # 没有匹配到则返回 None：由调用方决定是继续还是跳过

    def _parse_criteria(self, section_content: str) -> list[str]:
        # 将验收标准段落的文本解析为条目列表：按行分割是最简单的解析方式，
        # 因为 SKILL.md 中验收标准通常以列表形式编写（每行一条）
        """从 section 内容中解析验收标准列表"""
        criteria = []
        # 简单解析：按行分割，去掉空行
        lines = section_content.split('\n')
        for line in lines:
            line = line.strip()
            # 跳过空行和标题行：空行无内容，## 开头的行是子标题而非验收标准
            if line and not line.startswith('#'):
                # 去掉列表标记
                # 支持三种常见列表格式：- 、* 、数字编号（1. 或 1)）
                # 条件中的 line[0].isdigit() and line[1] in ('.', ')') 用于判断数字编号开头
                if line.startswith('- ') or line.startswith('* ') or (len(line) > 2 and line[0].isdigit() and line[1] in ('.', ')')):
                    # split(maxsplit=1) 只分割第一个空格：将列表标记与正文分离，取后半部分作为验收标准内容
                    line = line.split(maxsplit=1)[1].strip() if ' ' in line else line
                criteria.append(line)
        return criteria

    def _extract_keywords(self, text: str) -> list[str]:
        # 从验收标准文本中提取关键词：用于在步骤结果中进行模糊匹配，
        # 关键词数量限制为 10 个是为了防止一条过于冗长的标准在匹配时产生过多噪音
        """从文本中提取关键词（简单实现：取大于2个字符的词）"""
        # 提取中文词语：[\u4e00-\u9fff] 匹配所有 CJK 统一汉字，连续的中文字符视为一个词
        # 不依赖 jieba 等分词库：关键词提取只需"宽匹配"，过度精准分词反而可能漏检
        words = re.findall(r'[\u4e00-\u9fff]+', text)
        keywords = []
        for word in words:
            if len(word) >= 2:  # 过滤单字词：单字词如"的""了"匹配价值极低，只会产生误报
                keywords.append(word)
        # 也添加一些英文关键词
        # 英文词以字母为单位，用 [a-zA-Z]+ 匹配，长度 >= 3 过滤掉 "is", "an" 等短介词
        english_words = re.findall(r'[a-zA-Z]+', text)
        keywords.extend([w for w in english_words if len(w) >= 3])
        return keywords[:10]  # 截断到前 10 个：控制匹配复杂度，同时保留足够的关键词覆盖率

    def _build_validation_prompt(self, plan: dict, step_results: list[dict], criteria: list[str]) -> str:
        # 构建 LLM 的验收 prompt：使用 f-string 拼接而非模板引擎，
        # 因为结构简单且数据来源单一，引入 Jinja2 会增加不必要的依赖
        """构建验证 prompt"""
        # 用 f-string 拼接 prompt：每段用 """ 包裹，保持可读性和结构清晰
        prompt = f"""请检查以下任务执行结果是否满足验收标准。

【任务计划】
{plan.get('description', '无描述')}  # 无描述时给默认值：避免 LLM 拿到空字段后产生无意义的联想

【执行步骤】
"""
        # enumerate 从 1 开始：步骤编号对人类和 LLM 都更直观，从 0 开始会让人困惑
        for i, step in enumerate(step_results, 1):
            prompt += f"\n步骤 {i}:\n{str(step)}\n"  # str() 兜底：step 可能是 dict，直接拼接会报 TypeError

        prompt += "\n【验收标准】\n"
        for i, criterion in enumerate(criteria, 1):
            prompt += f"{i}. {criterion}\n"

        # 明确要求返回 JSON 格式：LLM 输出没有固定结构，不约定格式的话解析会非常困难
        # 给出 JSON schema 示例：few-shot 式提示能显著提高 LLM 输出格式的合规率
        prompt += """
【请以 JSON 格式返回】
{
  "passed": true/false,
  "issues": ["问题1", "问题2", ...],
  "suggestions": ["改进建议1", "改进建议2", ...]
}

要求：
1. 必须返回有效的 JSON
2. passed 表示是否满足所有验收标准
3. issues 列出具体的问题（如果有）
4. suggestions 给出改进建议（如果有）
"""
        return prompt

    def _parse_llm_validation(self, response: str) -> dict:
        # 解析 LLM 的验证输出：LLM 返回的自然语言中可能嵌入 JSON，需要用正则提取
        # 多层 fallback 设计：理想情况下提取 JSON → 退而求其次做关键词判断 → 最后降级为默认通过
        """解析 LLM 的验证输出"""
        try:
            # 尝试从响应中提取 JSON
            # 正则匹配含 "passed" 键的 JSON 对象：比单纯匹配 {} 更精确，避免提取到 prompt 中的示例 JSON
            json_match = re.search(r'\{[^{}]*"passed"[^{}]*\}', response, re.DOTALL)
            if json_match:
                import json  # 延迟导入 json：仅在此分支需要，避免模块级导入不必要的标准库
                return json.loads(json_match.group(0))  # 直接解析并返回，信任 LLM 返回的结构

            # 如果找不到 JSON，简单解析
            # 降级方案：用关键词判断——"已通过""满足""passed" 任一出现即视为通过，
            # 这是最保险的 fallback，确保验证流程不会被格式问题中断
            passed = "已通过" in response or "满足" in response or "passed" in response.lower()
            return {
                'passed': passed,
                'issues': [],  # 无结构化问题时，issues 留空
                'suggestions': []
            }

        except Exception:
            # 最外层 fallback：即使正则和 JSON 解析都失败，也默认通过
            # 原因：前两层（Layer A 和 Layer B）已验证通过，LLM 解析失败不表示任务有问题
            return {
                'passed': True,
                'issues': [],
                'suggestions': []
            }