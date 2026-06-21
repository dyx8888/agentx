import { useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import CardRenderer from '@/components/cards/CardRenderer';

const WELCOME_CAPABILITIES = [
  { icon: '🔍', label: '达人搜索', desc: '智能匹配带货达人' },
  { icon: '📊', label: '数据分析', desc: '销售/流量数据洞察' },
  { icon: '✍️', label: '内容策划', desc: '短视频脚本自动生成' },
  { icon: '📦', label: '物流跟踪', desc: '订单物流状态查询' },
];

function WelcomeMessage({ onCapabilityClick }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 text-center">
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6"
        style={{ background: 'linear-gradient(135deg, #007cf0, #00dfd8)' }}
      >
        <RobotOutlined className="text-3xl text-white" />
      </div>
      <h2 className="text-xl font-semibold text-[var(--color-ink)] mb-2">
        Master 智能助手
      </h2>
      <p className="text-sm text-[var(--color-mute)] max-w-md mb-8 leading-relaxed">
        我是您的专属 AI 工作助手，可以帮您搜索达人、分析数据、策划内容、跟踪物流。
        请告诉我您需要什么帮助？
      </p>
      <div className="grid grid-cols-2 gap-3 max-w-md w-full">
        {WELCOME_CAPABILITIES.map((cap) => (
          <button
            key={cap.label}
            onClick={() => onCapabilityClick(cap.label)}
            className="flex flex-col items-center gap-2 p-4 rounded-xl border border-[var(--color-hairline)]
              bg-white hover:border-[var(--color-ink)] hover:shadow-sm transition-all text-left"
          >
            <span className="text-2xl">{cap.icon}</span>
            <span className="text-sm font-medium text-[var(--color-ink)]">{cap.label}</span>
            <span className="text-xs text-[var(--color-mute)]">{cap.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function UserMessage({ content }) {
  return (
    <div className="flex justify-end gap-2 px-4">
      <div
        className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-md
        bg-[var(--color-canvas-soft)] border border-[var(--color-canvas-soft-2)]
        text-sm text-[var(--color-ink)] leading-relaxed whitespace-pre-wrap break-words"
      >
        {content}
      </div>
      <div className="w-7 h-7 rounded-full bg-[var(--color-ink)] text-white flex items-center justify-center flex-shrink-0 mt-1">
        <UserOutlined className="text-xs" />
      </div>
    </div>
  );
}

function MasterMessage({ content, isStreaming, metadata, onReview }) {
  return (
    <div className="flex gap-2 px-4">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-1"
        style={{ background: 'linear-gradient(135deg, #007cf0, #00dfd8)' }}
      >
        <RobotOutlined className="text-xs text-white" />
      </div>
      <div
        className={`max-w-[80%] px-4 py-2.5 rounded-2xl rounded-bl-md
        bg-white border text-sm leading-relaxed break-words
        ${isStreaming ? 'border-[var(--color-success)]' : 'border-[var(--color-hairline)]'}`}
      >
        {content ? (
          <div className="prose prose-sm max-w-none prose-headings:text-[var(--color-ink)] prose-p:text-[var(--color-ink)] prose-a:text-[var(--color-link)] prose-strong:text-[var(--color-ink)] prose-code:text-[var(--color-error)] prose-code:bg-[var(--color-canvas-soft)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-[var(--color-canvas-soft)] prose-pre:border prose-pre:border-[var(--color-hairline)] prose-li:text-[var(--color-ink)]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
        ) : isStreaming ? (
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-mute)] animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-mute)] animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-mute)] animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        ) : null}

        {/* Streaming cursor */}
        {isStreaming && content && (
          <span className="inline-block w-0.5 h-4 bg-[var(--color-ink)] ml-0.5 align-middle animate-pulse" />
        )}

        {/* Plan Steps */}
        {metadata?.plan?.steps && metadata.plan.steps.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {metadata.plan.steps.map((step) => (
              <div key={step.id} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-[var(--color-mute)] w-4">{step.id}</span>
                <span className="text-[var(--color-body)]">{step.description || step.title}</span>
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[var(--color-link-bg-soft)] text-[var(--color-link)]">
                  {step.tool || 'pending'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Source References */}
        {metadata?.sources && metadata.sources.length > 0 && (
          <div className="mt-3 pt-3 border-t border-[var(--color-hairline)]">
            <div className="text-xs text-[var(--color-mute)] mb-1.5 font-medium">参考来源</div>
            <div className="flex flex-wrap gap-1.5">
              {metadata.sources.map((ref, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full
                    bg-[var(--color-link-bg-soft)] text-[var(--color-link)] cursor-pointer
                    hover:bg-[var(--color-link)] hover:text-white transition-colors"
                  title={ref.content}
                >
                  {ref.source_file || `来源 ${i + 1}`}
                  {ref.score != null && (
                    <span className="opacity-60">({Math.round(ref.score * 100)}%)</span>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Inline Tool Result Cards */}
        {metadata?.toolResults && metadata.toolResults.length > 0 && (
          <div className="mt-3 pt-3 border-t border-[var(--color-hairline)]">
            <div className="text-xs text-[var(--color-mute)] mb-2 font-medium">产出物</div>
            {metadata.toolResults.map((tr, i) => (
              <CardRenderer key={i} toolResult={tr} onReview={onReview} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatArea({ messages, isStreaming, onCapabilityClick, onReview }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 流式更新时也滚动
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
        <div className="flex flex-col gap-4 py-6">
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