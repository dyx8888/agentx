import { useEffect, useRef } from 'react';
import { Users, BarChart3, FileText, Truck } from 'lucide-react';
import { cn } from '@/lib/utils';
import MessageBubble from '@/components/MessageBubble';

/* ═══════════════════════════════════════════════════════════════
   Capabilities — 4 cards with macaron tinted icon backgrounds
   ═══════════════════════════════════════════════════════════════ */

const CAPABILITIES = [
  {
    id: 'talent',
    icon: Users,
    title: '达人搜索与邀约草稿',
    desc: '基于已导入达人库筛选，不自动外发',
    prompt: '只基于我的达人库搜索护肤类小红书达人，并生成待审核邀约草稿',
    tint: 'bg-macaron-pink',
  },
  {
    id: 'analysis',
    icon: BarChart3,
    title: '数据分析与报告',
    desc: '接入店铺/平台数据后生成带来源报告',
    prompt: '基于已导入的店铺数据生成本周销售分析报告',
    tint: 'bg-macaron-blue',
  },
  {
    id: 'content',
    icon: FileText,
    title: '内容策划与脚本',
    desc: '基于品牌资料和知识库生成草稿',
    prompt: '为一款保温杯写一段 60 秒的短视频带货脚本',
    tint: 'bg-macaron-mint',
  },
  {
    id: 'logistics',
    icon: Truck,
    title: '物流跟踪与样品管理',
    desc: '接入订单/物流数据后查询状态',
    prompt: '查询已接入订单的物流状态，如果没有数据请明确说明',
    tint: 'bg-macaron-yellow',
  },
];

/* ═══════════════════════════════════════════════════════════════
   Greeting helper
   ═══════════════════════════════════════════════════════════════ */

function greeting() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

/* ═══════════════════════════════════════════════════════════════
   Welcome screen (empty state)
   ═══════════════════════════════════════════════════════════════ */

function Welcome({ onPick }) {
  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-4 py-10">
      <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
        <span className="font-heading text-2xl font-semibold lowercase">x</span>
      </div>
      <h1 className="font-heading text-3xl font-semibold text-foreground text-balance md:text-4xl">
        {greeting()}，有什么可以帮你？
      </h1>

      <div className="mt-12 grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
        {CAPABILITIES.map(({ id, icon: Icon, title, desc, prompt, tint }) => (
          <button
            key={id}
            type="button"
            onClick={() => onPick(prompt)}
            className="group flex items-start gap-3 rounded-2xl border border-border bg-card p-4 text-left shadow-sm transition-all hover:border-primary/30 hover:shadow-md"
          >
            <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', tint)}>
              <Icon className="size-5 text-foreground/80" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">{title}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{desc}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   ChatArea (default export)
   Props: { messages, isStreaming, conversationTitle, onApprove,
            onReject, onDraftMessage }
   ═══════════════════════════════════════════════════════════════ */

export default function ChatArea({
  messages = [],
  isStreaming = false,
  conversationTitle,
  onApprove,
  onReject,
  onDraftMessage,
  onFileClick,
  onUserFileClick,
}) {
  const sentinelRef = useRef(null);
  const isEmpty = messages.length === 0;

  const lastMessage = messages[messages.length - 1];
  const lastContentLength = lastMessage?.content?.length ?? 0;

  useEffect(() => {
    sentinelRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, lastContentLength, isStreaming]);

  const handlePick = (prompt) => {
    onDraftMessage?.(prompt);
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isEmpty ? (
          <Welcome onPick={handlePick} />
        ) : (
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                onApprove={onApprove}
                onReject={onReject}
                onFileClick={onFileClick}
                onUserFileClick={onUserFileClick}
              />
            ))}
            <div ref={sentinelRef} aria-hidden="true" />
          </div>
        )}
      </div>
    </div>
  );
}

