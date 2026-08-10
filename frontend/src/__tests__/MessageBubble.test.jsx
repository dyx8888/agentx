import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MessageBubble from '@/components/MessageBubble';

describe('MessageBubble', () => {
  it('shows a clear progress message while waiting for the first assistant content', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-pending',
          role: 'assistant',
          content: '',
          isStreaming: true,
          sources: [],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('正在理解问题并选择合适的数据源...')).toBeInTheDocument();
  });

  it('shows retrieval progress after sources arrive but before content arrives', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-sources',
          role: 'assistant',
          content: '',
          isStreaming: true,
          sources: [{ title: '知识库片段', url: '' }],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('已找到相关证据，正在组织回答...')).toBeInTheDocument();
  });

  it('shows a slow response notice when the first assistant content takes too long', () => {
    render(
      <MessageBubble
        slowNoticeMs={0}
        message={{
          id: 'assistant-slow',
          role: 'assistant',
          content: '',
          isStreaming: true,
          sources: [],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText(/外部模型或工具响应较慢/)).toBeInTheDocument();
    expect(screen.getByText(/停止按钮后重试/)).toBeInTheDocument();
  });

  it('shows model fallback warnings above assistant content', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-warning',
          role: 'assistant',
          content: 'Final answer',
          isStreaming: false,
          sources: [],
          warnings: [
            {
              id: 'model_fallback-primary-backup',
              code: 'model_fallback',
              message: 'Primary model failed; switched to backup model.',
            },
          ],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('Primary model failed; switched to backup model.')).toBeInTheDocument();
    expect(screen.getByText('Final answer')).toBeInTheDocument();
  });

  it('hides internal thinking, plans, and generic tool review controls', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-internal',
          role: 'assistant',
          content: '这是给用户看的业务回答',
          thinking: '反思：内部推理不应展示',
          plan: '执行计划：内部计划不应展示',
          isStreaming: false,
          sources: [],
          toolResults: [
            {
              id: 'tool-1',
              name: 'internal_tool',
              result: '[Action] RAG answer from knowledge base',
            },
          ],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('这是给用户看的业务回答')).toBeInTheDocument();
    expect(screen.queryByText(/反思/)).not.toBeInTheDocument();
    expect(screen.queryByText(/执行计划/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RAG answer from knowledge base/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '通过' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '驳回' })).not.toBeInTheDocument();
  });

  it('labels evidence by data source instead of calling every source a web page', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-sources-visible',
          role: 'assistant',
          content: '根据企业数据，推荐以下达人。',
          isStreaming: false,
          sources: [
            {
              title: '企业知识库片段',
              source_type: 'knowledge_base',
              source_note: '品牌私域资料',
            },
            {
              title: 'FULL测试成分达人B',
              data_source: 'manual_upload',
              source_note: '运营人工导入',
            },
            {
              title: '公开网页达人资料',
              data_source: 'public_web',
              url: 'https://public-source.invalid/kol',
            },
          ],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('数据来源与证据（3 条）')).toBeInTheDocument();
    expect(screen.getByText('知识库')).toBeInTheDocument();
    expect(screen.getByText('人工导入')).toBeInTheDocument();
    expect(screen.getByText('公开网页')).toBeInTheDocument();
    expect(screen.getByText(/品牌私域资料/)).toBeInTheDocument();
    expect(screen.queryByText(/搜索到 3 个网页/)).not.toBeInTheDocument();
  });
});
