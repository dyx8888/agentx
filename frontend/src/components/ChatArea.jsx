import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RobotOutlined, UserOutlined, RocketOutlined, DownOutlined, RightOutlined, CheckCircleOutlined, FileTextOutlined, LinkOutlined } from '@ant-design/icons';
import CardRenderer from '@/components/cards/CardRenderer';

const WELCOME_CAPABILITIES = [
  { label: '达人搜索', message: '帮我找美妆护肤类抖音达人，粉丝10-50万' },
  { label: '分析数据', message: '帮我分析这批达人的数据质量' },
  { label: '策划脚本', message: '帮我策划一期618返场直播脚本' },
  { label: '查物流', message: '查一下发给达人的样品物流状态' },
];

/* ============================================================
   Welcome Message
   ============================================================ */
function WelcomeMessage({ onCapabilityClick }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-16 text-center">
      <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6 shadow-sm"
        style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
        <RocketOutlined className="text-2xl text-white" />
      </div>

      <h2 className="text-xl font-bold text-gray-900 mb-2 tracking-tight">AgentX 智能助手</h2>
      <p className="text-sm text-gray-500 max-w-[480px] leading-relaxed mb-10">
        我是您的专属 AI 工作助手，可以帮您搜索达人、分析数据、策划内容、跟踪物流
      </p>

      {/* Quick buttons — rounded-lg, NOT pill */}
      <div className="flex flex-wrap gap-3 justify-center max-w-[600px]">
        {WELCOME_CAPABILITIES.map((cap) => (
          <button
            key={cap.label}
            onClick={() => onCapabilityClick(cap.message)}
            className="inline-flex items-center px-5 py-2.5 text-sm font-medium
              bg-white border border-gray-200 rounded-lg shadow-sm
              text-gray-700 mx-2
              hover:bg-gray-50 hover:border-gray-300 hover:text-gray-900
              transition-all duration-150 whitespace-nowrap"
          >
            {cap.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ============================================================
   User Message Bubble — wider, larger avatar
   ============================================================ */
function UserMessage({ content }) {
  return (
    <div className="flex justify-end gap-4 px-8 max-w-[900px] mx-auto w-full">
      <div className="max-w-[80%] px-5 py-3 rounded-2xl rounded-br-md
        bg-gray-900 text-white text-sm leading-relaxed whitespace-pre-wrap break-words">
        {content}
      </div>
      <div className="w-8 h-8 min-w-8 rounded-full bg-gray-200
        text-gray-500 flex items-center justify-center flex-shrink-0 mt-0.5">
        <UserOutlined className="text-sm" />
      </div>
    </div>
  );
}

/* ============================================================
   Reasoning Panel — larger text, larger avatar, DeepSeek style
   ============================================================ */
function ReasoningPanel({ metadata }) {
  const [collapsed, setCollapsed] = useState(false);
  const hasPlan = metadata?.plan?.steps?.length > 0;
  const hasSources = metadata?.sources?.length > 0;

  if (!hasPlan && !hasSources) return null;

  return (
    <div className="mt-5 rounded-2xl overflow-hidden bg-gray-50/80 border border-gray-100">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-3 px-5 py-3.5
          hover:bg-gray-100/80 transition-colors"
      >
        <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
          <RobotOutlined className="text-xs text-white" />
        </div>
        <div className="flex items-center gap-2 flex-1">
          <span className="text-sm font-medium text-gray-700">
            {collapsed ? '正在思考中...' : '思考与推理过程'}
          </span>
          {hasPlan && (
            <span className="px-2 py-0.5 text-[11px] font-medium rounded-full
              bg-purple-100 text-purple-600">
              {metadata.plan.steps.length} 步骤
            </span>
          )}
        </div>
        {collapsed ? (
          <RightOutlined className="text-xs text-gray-400" />
        ) : (
          <DownOutlined className="text-xs text-gray-400" />
        )}
      </button>

      {!collapsed && (
        <div className="px-5 pb-4 space-y-2">
          {hasPlan && metadata.plan.steps.map((step, idx) => (
            <div
              key={step.id || idx}
              className="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-white"
            >
              <span className="font-mono text-sm text-indigo-500 w-6 flex-shrink-0 font-medium">
                {step.id || idx + 1}
              </span>
              <span className="flex-1 text-sm text-gray-600">
                {step.description || step.title || '处理中...'}
              </span>
              {step.tool && (
                <span className="px-2 py-0.5 text-[11px] font-medium rounded-full
                  bg-purple-100 text-purple-600">
                  {step.tool}
                </span>
              )}
            </div>
          ))}

          {hasSources && (
            <div className="pt-3 mt-1 border-t border-gray-100">
              <div className="flex items-center gap-1.5 mb-2 text-xs text-gray-400">
                <LinkOutlined className="text-xs" />
                参考来源
              </div>
              <div className="flex flex-wrap gap-1.5">
                {metadata.sources.map((ref, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full
                      bg-white text-gray-500 cursor-pointer
                      hover:bg-indigo-50 hover:text-indigo-600 transition-colors"
                    title={ref.content}
                  >
                    <FileTextOutlined className="text-[10px]" />
                    {ref.source_file || `来源 ${i + 1}`}
                    {ref.score != null && (
                      <span className="opacity-50">({Math.round(ref.score * 100)}%)</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Master (AI) Message Bubble — larger avatar
   ============================================================ */
function MasterMessage({ content, isStreaming, metadata, onReview }) {
  return (
    <div className="flex gap-4 px-8 max-w-[900px] mx-auto w-full">
      <div className="w-8 h-8 min-w-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
        style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
        <RobotOutlined className="text-xs text-white" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-sm leading-relaxed break-words">
          {content ? (
            <div className="prose prose-sm max-w-none
              prose-headings:text-gray-900 prose-headings:font-semibold prose-headings:text-sm
              prose-p:text-gray-600 prose-p:leading-relaxed
              prose-a:text-indigo-600
              prose-strong:text-gray-900
              prose-code:text-indigo-600 prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:font-mono prose-code:text-xs
              prose-pre:bg-gray-50 prose-pre:border prose-pre:border-gray-200 prose-pre:rounded-xl prose-pre:p-4
              prose-li:text-gray-600 prose-hr:border-gray-200">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          ) : isStreaming ? (
            <div className="flex items-center gap-2 py-1">
              <span className="flex gap-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-dot-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-dot-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-dot-bounce" style={{ animationDelay: '300ms' }} />
              </span>
              <span className="text-xs text-gray-400">思考中...</span>
            </div>
          ) : null}

          {isStreaming && content && (
            <span className="inline-block w-0.5 h-4 bg-indigo-500 ml-0.5 align-middle animate-typing-cursor" />
          )}
        </div>

        <ReasoningPanel metadata={metadata} />

        {metadata?.toolResults && metadata.toolResults.length > 0 && (
          <div className="mt-5 space-y-3">
            <div className="flex items-center gap-2">
              <CheckCircleOutlined className="text-emerald-500 text-sm" />
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">产出物</span>
            </div>
            {metadata.toolResults.map((tr, i) => (
              <CardRenderer key={i} toolResult={tr} onReview={onReview} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================================================
   ChatArea
   ============================================================ */
export default function ChatArea({ messages, isStreaming, onCapabilityClick, onReview }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (isStreaming && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [isStreaming, messages]);

  const hasMessages = messages.length > 0;

  return (
    <div className="flex-1 overflow-y-auto">
      <span data-testid="message-count" className="hidden">{messages.length}</span>
      {!hasMessages ? (
        <WelcomeMessage onCapabilityClick={onCapabilityClick} />
      ) : (
        <div className="flex flex-col gap-6 py-8">
          {messages.map((msg, idx) =>
            msg.role === 'user' ? (
              <UserMessage key={msg.id || idx} content={msg.content} />
            ) : (
              <MasterMessage
                key={msg.id || idx}
                content={msg.content}
                isStreaming={isStreaming && idx === messages.length - 1}
                metadata={msg.metadata}
                onReview={onReview}
              />
            )
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}