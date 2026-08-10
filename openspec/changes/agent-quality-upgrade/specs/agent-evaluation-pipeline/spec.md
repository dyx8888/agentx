## ADDED Requirements

### Requirement: 测试用例定义
系统SHALL支持通过YAML文件定义评测测试用例，包含输入消息、预期工具调用列表、预期结果关键词。

#### Scenario: 加载测试用例集
- **WHEN** 评测流水线启动
- **THEN** 系统从 `tests/evaluation/cases/` 目录加载所有YAML测试用例

#### Scenario: 测试用例格式验证
- **WHEN** 测试用例YAML缺少必填字段（message）
- **THEN** 系统报告验证错误，跳过该用例

### Requirement: 评测指标计算
系统SHALL在每次评测运行后自动计算以下指标：任务完成率、工具调用准确率、平均执行步数、平均Token消耗。

#### Scenario: 正常评测运行
- **WHEN** 评测流水线运行完所有测试用例
- **THEN** 系统输出包含四项指标的评测报告

#### Scenario: 工具调用准确率计算
- **WHEN** 测试用例指定了expected_tools
- **THEN** 系统比对实际调用的工具列表与预期列表，计算准确率

### Requirement: CI集成
评测流水线SHALL可通过命令行 `python -m app.evaluation run` 触发，支持CI集成。

#### Scenario: CI中运行评测
- **WHEN** CI流水线执行 `python -m app.evaluation run --ci`
- **THEN** 系统以非0退出码表示评测未通过（完成率低于阈值）

#### Scenario: 评测报告生成
- **WHEN** 评测运行完成
- **THEN** 系统在 `tests/evaluation/reports/` 目录生成JSON和Markdown格式的评测报告

### Requirement: 根因分析
评测流水线SHALL在运行完成后自动进行根因分析，归纳失败模式并关联优化建议。

#### Scenario: 失败模式自动分类
- **WHEN** 评测中有用例未通过
- **THEN** 系统自动分析失败原因，归类为：规划错误、工具误选、参数错误、幻觉、安全绕过、异常处理差

#### Scenario: 优化建议自动生成
- **WHEN** 根因分析识别出"工具误选"为Top 1失败模式
- **THEN** 系统输出优化建议："建议优化工具描述和参数说明，提高工具选择准确率"，并关联受影响的具体工具

#### Scenario: 根因分析报告
- **WHEN** 评测和根因分析完成
- **THEN** 系统生成包含以下内容的报告：Top 3失败模式、每种模式的影响案例数、对应的优化建议

### Requirement: 人工校准机制
系统SHALL支持定期人工抽检，校准LLM-as-Judge的评分准确性。

#### Scenario: 人工抽检校准
- **WHEN** 评测运行累计50次
- **THEN** 系统随机抽取5个案例，提示人工评审员对比LLM评分与人工判断

#### Scenario: Golden Test Set维护
- **WHEN** 人工评审员标注标准答案
- **THEN** 系统将标注结果存入 `tests/evaluation/golden/` 目录，作为LLM-as-Judge的校准基准

### Requirement: 回归测试
每次Agent修改后，系统SHALL自动运行评测集并对比上次分数，低于阈值告警。

#### Scenario: 回归测试通过
- **WHEN** 修改Agent后运行评测，各项指标变化 < 5%
- **THEN** 系统输出"回归测试通过"，标记为可上线

#### Scenario: 回归测试退化
- **WHEN** 修改Agent后运行评测，任务完成率下降 > 10%
- **THEN** 系统输出"回归测试未通过：任务完成率从85%降至72%"，阻止上线

### Requirement: 全链路Trace记录
评测运行中SHALL记录完整的思考-行动-观察Trace，支持按步骤展开查看。

#### Scenario: 完整Trace记录
- **WHEN** 评测运行一个测试用例
- **THEN** 系统记录每步的：thought（推理内容）、tool_call（工具名+参数+结果）、duration_ms、token_usage

#### Scenario: Trace可视化
- **WHEN** 评测运行完成
- **THEN** 系统生成HTML格式的Trace报告，支持按步骤展开/折叠，标注成功/失败步骤