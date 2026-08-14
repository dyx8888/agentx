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
  it('renders grounded KOL results as readable enterprise talent cards', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-kol-results',
          role: 'assistant',
          content: [
            '已基于当前企业达人库找到 1 位匹配“护肤、小红书”的达人：',
            '',
            '| # | 达人名称 | 平台 | 粉丝数 | 互动率 | 分类 | 数据来源 |',
            '|---|---|---|---:|---:|---|---|',
            '| 1 | 企业护肤达人A | 小红书 | 12.0万 | 4.2% | 护肤 | 人工导入 |',
            '',
            '以上结果均来自当前企业达人库，未使用 mock/demo/fallback 数据。',
          ].join('\n'),
          isStreaming: false,
          sources: [],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('企业达人库结果')).toBeInTheDocument();
    expect(screen.getByText('企业护肤达人A')).toBeInTheDocument();
    expect(screen.getByText('小红书')).toBeInTheDocument();
    expect(screen.getByText('12.0万')).toBeInTheDocument();
    expect(screen.getByText('4.2%')).toBeInTheDocument();
    expect(screen.getByText('护肤')).toBeInTheDocument();
    expect(screen.getByText('企业达人库')).toBeInTheDocument();
    expect(screen.getByText('人工导入')).toBeInTheDocument();
  });

  it('renders requires_kol_data as an actionable data setup prompt', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-kol-required',
          role: 'assistant',
          code: 'requires_kol_data',
          content: '当前企业达人库无匹配数据（requires_kol_data）。',
          isStreaming: false,
          sources: [],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('需要企业达人数据')).toBeInTheDocument();
    expect(screen.getByText(/导入达人数据/)).toBeInTheDocument();
    expect(screen.getByText(/完成平台授权/)).toBeInTheDocument();
    expect(screen.getByText(/不会用 mock\/demo 达人补齐结果/)).toBeInTheDocument();
  });

  it('does not show KOL cards for ordinary assistant messages', () => {
    render(
      <MessageBubble
        message={{
          id: 'assistant-normal',
          role: 'assistant',
          content: '这是一条普通聊天回答，保留原有 markdown 渲染。',
          isStreaming: false,
          sources: [],
          toolResults: [],
          delegations: [],
        }}
      />
    );

    expect(screen.getByText('这是一条普通聊天回答，保留原有 markdown 渲染。')).toBeInTheDocument();
    expect(screen.queryByText('企业达人库结果')).not.toBeInTheDocument();
    expect(screen.queryByText('需要企业达人数据')).not.toBeInTheDocument();
  });
});
