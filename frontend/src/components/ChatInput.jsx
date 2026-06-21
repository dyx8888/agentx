import { useState, useRef, useEffect } from 'react';
import { SendOutlined } from '@ant-design/icons';

const QUICK_ACTIONS = [
  { label: '帮我找达人', message: '帮我找美妆达人' },
  { label: '分析数据', message: '帮我分析最近的销售数据' },
  { label: '策划脚本', message: '帮我策划一个短视频脚本' },
  { label: '物流跟踪', message: '帮我查一下物流状态' },
];

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('');
  const textareaRef = useRef(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [value]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (message) => {
    onSend(message);
  };

  return (
    <div className="border-t border-[var(--color-hairline)] bg-white px-4 py-3">
      {/* Quick Actions */}
      <div className="flex gap-2 mb-3 flex-wrap">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => handleQuickAction(action.message)}
            disabled={disabled}
            className="px-3 py-1.5 text-xs border border-[var(--color-hairline)] rounded-full
              text-[var(--color-mute)] hover:text-[var(--color-ink)] hover:border-[var(--color-ink)]
              bg-white transition-colors disabled:opacity-50"
          >
            {action.label}
          </button>
        ))}
      </div>

      {/* Input Row */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          disabled={disabled}
          rows={1}
          className="flex-1 px-4 py-2.5 text-sm border border-[var(--color-hairline)] rounded-lg
            bg-white text-[var(--color-ink)] placeholder:text-[var(--color-mute)]
            resize-none outline-none focus:border-[var(--color-ink)] transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ minHeight: '44px', maxHeight: '120px' }}
        />

        <button
          onClick={handleSend}
          data-testid="send-btn"
          disabled={disabled || !value.trim()}
          className="w-11 h-11 flex items-center justify-center rounded-lg
            bg-[var(--color-ink)] text-white hover:opacity-90 transition-opacity
            disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
        >
          <SendOutlined className="text-lg" />
        </button>
      </div>
    </div>
  );
}