import { useState, useRef, useEffect } from 'react';
import { SendOutlined, PaperClipOutlined, PictureOutlined, FileTextOutlined, CodeOutlined, XOutlined, LoadingOutlined } from '@ant-design/icons';
import { message } from 'antd';

function getFileIcon(file) {
  if (file.type.startsWith('image/')) return PictureOutlined;
  if (file.type.includes('pdf')) return FileTextOutlined;
  if (file.type.includes('json') || file.type.includes('code') || file.name.match(/\.(py|js|ts|css|html)$/)) return CodeOutlined;
  return FileTextOutlined;
}

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('');
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

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
    setFiles([]);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (e) => {
    const selectedFiles = Array.from(e.target.files || []);
    const validFiles = selectedFiles.filter((file) => {
      if (file.size > 10 * 1024 * 1024) { message.warning(`${file.name} 超过 10MB 限制`); return false; }
      return true;
    });
    setFiles((prev) => [...prev, ...validFiles]);
    e.target.value = '';
  };

  const handleRemoveFile = (index) => { setFiles((prev) => prev.filter((_, i) => i !== index)); };

  const handleDrop = (e) => {
    e.preventDefault();
    const droppedFiles = Array.from(e.dataTransfer.files || []);
    const validFiles = droppedFiles.filter((file) => {
      if (file.size > 10 * 1024 * 1024) { message.warning(`${file.name} 超过 10MB 限制`); return false; }
      return true;
    });
    setFiles((prev) => [...prev, ...validFiles]);
  };

  const handleDragOver = (e) => { e.preventDefault(); };

  return (
    <div className="px-6 pb-6 bg-white" onDrop={handleDrop} onDragOver={handleDragOver}>
      {/* Uploaded Files */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {files.map((file, index) => {
            const Icon = getFileIcon(file);
            return (
              <div key={index} className="flex items-center gap-2 px-3 py-1.5 bg-gray-50
                border border-gray-200 rounded-full">
                <Icon className="text-gray-400 text-xs" />
                <span className="text-[11px] text-gray-600 truncate max-w-[120px]">{file.name}</span>
                <button onClick={() => handleRemoveFile(index)} className="text-gray-400 hover:text-red-500 transition-colors">
                  <XOutlined className="text-[10px]" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Unified Input Card — DeepSeek style */}
      <div className="bg-white border border-gray-200 rounded-2xl shadow-lg
        focus-within:border-gray-400 focus-within:ring-2 focus-within:ring-gray-200/50
        transition-all duration-150 overflow-hidden">

        {/* Main row: paperclip | textarea | send */}
        <div className="flex items-end gap-3 px-4 pt-3 pb-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="flex items-center justify-center w-9 h-9 rounded-full
              text-gray-400 hover:text-gray-600 hover:bg-gray-100
              transition-all disabled:opacity-50 flex-shrink-0 mb-0.5"
            title="上传文件"
          >
            <PaperClipOutlined className="text-base" />
          </button>
          <input ref={fileInputRef} type="file" multiple onChange={handleFileSelect} className="hidden" />

          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent border-none outline-none resize-none
              text-sm text-gray-900 placeholder:text-gray-400 leading-relaxed
              disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ minHeight: '28px', maxHeight: '120px' }}
          />

          <button
            onClick={handleSend}
            data-testid="send-btn"
            disabled={disabled || !value.trim()}
            className="flex items-center justify-center w-9 h-9 rounded-full
              bg-gray-900 text-white
              hover:bg-gray-700
              transition-all duration-150
              disabled:opacity-25 disabled:cursor-not-allowed
              flex-shrink-0 mb-0.5"
          >
            {uploading ? (
              <LoadingOutlined className="text-sm animate-spin" />
            ) : (
              <SendOutlined className="text-sm" />
            )}
          </button>
        </div>

        {/* Drag hint — INSIDE the card */}
        <div className="px-4 pb-2.5">
          <span className="text-[11px] text-gray-400">
            支持拖拽文件到此上传（最大 10MB）
          </span>
        </div>
      </div>
    </div>
  );
}