"""
Trace Recorder - 全链路Trace记录与可视化
记录完整的思考-行动-观察Trace，生成HTML可视化报告
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceStep:
    """单步Trace记录"""
    step_index: int
    thought: str = ""
    tool_name: str = ""
    tool_params: dict = field(default_factory=dict)
    tool_result: str = ""
    observation: str = ""
    duration_ms: float = 0.0
    token_consumed: int = 0
    success: bool = True
    error: str = ""


@dataclass
class TraceRecord:
    """完整Trace记录"""
    trace_id: str = ""
    agent_name: str = ""
    scenario: str = ""
    user_message: str = ""
    start_time: str = ""
    end_time: str = ""
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    steps: list[TraceStep] = field(default_factory=list)
    final_response: str = ""
    success: bool = False


class TraceRecorder:
    """全链路Trace记录器"""

    def __init__(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "reports", "traces"
            )
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        self._current_trace: TraceRecord | None = None

    def start_trace(self, agent_name: str, scenario: str,
                    user_message: str) -> str:
        """开始记录Trace"""
        trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_name}"
        self._current_trace = TraceRecord(
            trace_id=trace_id,
            agent_name=agent_name,
            scenario=scenario,
            user_message=user_message,
            start_time=datetime.now().isoformat(),
        )
        return trace_id

    def record_step(self, step: TraceStep):
        """记录单个步骤"""
        if self._current_trace:
            self._current_trace.steps.append(step)
            self._current_trace.total_tokens += step.token_consumed

    def end_trace(self, final_response: str = "", success: bool = True):
        """结束Trace记录并保存"""
        if not self._current_trace:
            return

        self._current_trace.end_time = datetime.now().isoformat()
        self._current_trace.final_response = final_response[:2000]
        self._current_trace.success = success

        if self._current_trace.steps:
            self._current_trace.total_duration_ms = sum(
                s.duration_ms for s in self._current_trace.steps
            )

        self._save_trace()
        self._current_trace = None

    def _save_trace(self):
        trace = self._current_trace
        if not trace:
            return

        # 保存JSON
        json_path = os.path.join(self._output_dir, f"{trace.trace_id}.json")
        trace_data = {
            "trace_id": trace.trace_id,
            "agent_name": trace.agent_name,
            "scenario": trace.scenario,
            "user_message": trace.user_message,
            "start_time": trace.start_time,
            "end_time": trace.end_time,
            "total_duration_ms": trace.total_duration_ms,
            "total_tokens": trace.total_tokens,
            "success": trace.success,
            "final_response": trace.final_response,
            "steps": [
                {
                    "index": s.step_index,
                    "thought": s.thought,
                    "tool_name": s.tool_name,
                    "tool_params": s.tool_params,
                    "tool_result": str(s.tool_result)[:500],
                    "observation": s.observation,
                    "duration_ms": s.duration_ms,
                    "token_consumed": s.token_consumed,
                    "success": s.success,
                    "error": s.error,
                }
                for s in trace.steps
            ],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)

        # 保存HTML可视化
        html_path = os.path.join(self._output_dir, f"{trace.trace_id}.html")
        html = self._generate_html(trace)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

    def _generate_html(self, trace: TraceRecord) -> str:
        """生成HTML格式的Trace可视化报告"""
        steps_html = ""
        for s in trace.steps:
            status_class = "success" if s.success else "failure"
            status_text = "✓" if s.success else "✗"
            steps_html += f"""
            <div class="step {status_class}">
                <div class="step-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="step-num">Step {s.step_index}</span>
                    <span class="step-status">{status_text}</span>
                    <span class="step-tool">{s.tool_name or 'Think'}</span>
                    <span class="step-duration">{s.duration_ms:.0f}ms</span>
                    <span class="step-tokens">{s.token_consumed} tokens</span>
                </div>
                <div class="step-body">
                    <div class="section">
                        <h4>Thought</h4>
                        <pre>{self._escape_html(s.thought) or '(No explicit thought)'}</pre>
                    </div>
                    <div class="section">
                        <h4>Tool Call</h4>
                        <div class="tool-name">{s.tool_name or 'N/A'}</div>
                        <pre>{self._escape_html(json.dumps(s.tool_params, ensure_ascii=False, indent=2)) if s.tool_params else '{}'}</pre>
                    </div>
                    <div class="section">
                        <h4>Result</h4>
                        <pre>{self._escape_html(str(s.tool_result)[:1000]) if s.tool_result else '(Empty)'}</pre>
                    </div>
                    <div class="section">
                        <h4>Observation</h4>
                        <pre>{self._escape_html(s.observation) or '(No observation)'}</pre>
                    </div>
                    {f'<div class="section error"><h4>Error</h4><pre>{self._escape_html(s.error)}</pre></div>' if s.error else ''}
                </div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trace Report - {trace.trace_id}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 24px 32px; }}
.header h1 {{ font-size: 24px; margin-bottom: 8px; }}
.header .meta {{ font-size: 14px; opacity: 0.9; display: flex; gap: 24px; flex-wrap: wrap; }}
.summary {{ display: flex; gap: 16px; padding: 20px 32px; background: white; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }}
.summary-card {{ background: #f8f9fa; border-radius: 8px; padding: 16px 24px; min-width: 120px; }}
.summary-card .label {{ font-size: 12px; color: #888; text-transform: uppercase; }}
.summary-card .value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
.summary-card .value.success {{ color: #28a745; }}
.summary-card .value.failure {{ color: #dc3545; }}
.container {{ max-width: 900px; margin: 24px auto; padding: 0 16px; }}
.step {{ background: white; border-radius: 8px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
.step-header {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; user-select: none; }}
.step-header:hover {{ background: #f8f9fa; }}
.step-num {{ font-weight: 600; color: #667eea; min-width: 60px; }}
.step-status {{ font-size: 18px; min-width: 24px; }}
.success .step-status {{ color: #28a745; }}
.failure .step-status {{ color: #dc3545; }}
.step-tool {{ flex: 1; font-weight: 500; }}
.step-duration {{ color: #888; font-size: 13px; }}
.step-tokens {{ color: #888; font-size: 13px; }}
.step-body {{ padding: 0 16px 16px; }}
.step.collapsed .step-body {{ display: none; }}
.section {{ margin-top: 12px; }}
.section h4 {{ font-size: 13px; color: #667eea; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
.section pre {{ background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 4px; padding: 10px; font-size: 13px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; }}
.section.error pre {{ background: #fff5f5; border-color: #ffc9c9; color: #dc3545; }}
.tool-name {{ background: #e8f0fe; color: #1967d2; padding: 2px 8px; border-radius: 4px; font-size: 13px; font-weight: 500; display: inline-block; margin-bottom: 8px; }}
.footer {{ text-align: center; padding: 24px; color: #888; font-size: 13px; }}
</style>
</head>
<body>
<div class="header">
    <h1>Agent Trace Report</h1>
    <div class="meta">
        <span>Trace: {trace.trace_id}</span>
        <span>Agent: {trace.agent_name}</span>
        <span>Scenario: {trace.scenario}</span>
    </div>
</div>
<div class="summary">
    <div class="summary-card">
        <div class="label">Status</div>
        <div class="value {'success' if trace.success else 'failure'}">{'PASS' if trace.success else 'FAIL'}</div>
    </div>
    <div class="summary-card">
        <div class="label">Duration</div>
        <div class="value">{trace.total_duration_ms:.0f}ms</div>
    </div>
    <div class="summary-card">
        <div class="label">Steps</div>
        <div class="value">{len(trace.steps)}</div>
    </div>
    <div class="summary-card">
        <div class="label">Tokens</div>
        <div class="value">{trace.total_tokens}</div>
    </div>
</div>
<div class="container">
    <h3 style="margin-bottom: 16px;">Message: {self._escape_html(trace.user_message[:200])}</h3>
    {steps_html}
    <div class="section">
        <h4>Final Response</h4>
        <pre>{self._escape_html(trace.final_response[:2000])}</pre>
    </div>
</div>
<div class="footer">Generated at {datetime.now().isoformat()} | AgentX Trace Recorder</div>
</body>
</html>"""

    @staticmethod
    def _escape_html(text: str) -> str:
        return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── 全局实例 ──────────────────────────

_trace_recorder: TraceRecorder | None = None


def get_trace_recorder() -> TraceRecorder:
    global _trace_recorder
    if _trace_recorder is None:
        _trace_recorder = TraceRecorder()
    return _trace_recorder