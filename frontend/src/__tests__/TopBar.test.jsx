import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TopBar from '@/components/TopBar';

const mocks = vi.hoisted(() => ({
  authState: {
    user: { username: 'alice', company_id: 239, is_admin: false },
  },
  getTodayCost: vi.fn(),
  getCostSummary: vi.fn(),
  getEmbeddingConfig: vi.fn(),
  getLlmConfig: vi.fn(),
}));

vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => mocks.authState,
}));

vi.mock('@/api/costs', () => ({
  getTodayCost: mocks.getTodayCost,
  getCostSummary: mocks.getCostSummary,
}));

vi.mock('@/api/rag', () => ({
  getEmbeddingConfig: mocks.getEmbeddingConfig,
}));

vi.mock('@/api/llmConfig', () => ({
  getLlmConfig: mocks.getLlmConfig,
}));

function renderTopBar() {
  return render(
    <TopBar
      model="glm-5.2"
      setModel={vi.fn()}
      embedding="bge-large-zh"
      setEmbedding={vi.fn()}
      filesOpen={false}
      onToggleFiles={vi.fn()}
      conversationTitle="新对话"
    />
  );
}

describe('TopBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authState.user = { username: 'alice', company_id: 239, is_admin: false };
    mocks.getEmbeddingConfig.mockResolvedValue({ mode: 'local', model_name: 'bge-large-zh' });
    mocks.getLlmConfig.mockResolvedValue({
      status: 'configured',
      providers: {
        zhipu: {
          gateway: 'https://llm.example.test',
          apiKeyMasked: 'sk-****test',
          tpm: { glm: 100000 },
        },
      },
    });
    mocks.getTodayCost.mockResolvedValue({
      total_input_tokens: 100,
      total_output_tokens: 50,
      total_cost: 0.1,
    });
    mocks.getCostSummary.mockResolvedValue({
      total_cost: 0.1,
      total_input_tokens: 100,
      total_output_tokens: 50,
      cost_by_model: [],
    });
  });

  it('hides the Token cost entry from ordinary users and does not call admin cost APIs', async () => {
    renderTopBar();

    expect(screen.queryByRole('button', { name: 'Token 消耗' })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(mocks.getEmbeddingConfig).toHaveBeenCalled();
    });
    expect(mocks.getTodayCost).not.toHaveBeenCalled();
    expect(mocks.getCostSummary).not.toHaveBeenCalled();
  });

  it('does not fall back to company 1 when the current user has no company_id', async () => {
    mocks.authState.user = { username: 'alice', is_admin: false };

    renderTopBar();

    await waitFor(() => {
      expect(mocks.getEmbeddingConfig).toHaveBeenCalled();
    });
    expect(mocks.getLlmConfig).not.toHaveBeenCalled();
  });

  it('shows Token cost entry for admins and loads usage data', async () => {
    mocks.authState.user = { username: 'admin', company_id: 239, is_admin: true };

    renderTopBar();

    expect(screen.getByRole('button', { name: 'Token 消耗' })).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getTodayCost).toHaveBeenCalled();
      expect(mocks.getCostSummary).toHaveBeenCalledWith(1);
      expect(mocks.getCostSummary).toHaveBeenCalledWith(30);
    });
  });

  it('labels cost values as USD, matching backend cost_usd data', async () => {
    mocks.authState.user = { username: 'admin', company_id: 239, is_admin: true };

    renderTopBar();

    await waitFor(() => {
      expect(mocks.getTodayCost).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Token 消耗' }));

    expect(await screen.findAllByText('$0.10')).toHaveLength(2);
    expect(screen.queryByText('¥0.10')).not.toBeInTheDocument();
  });
});
