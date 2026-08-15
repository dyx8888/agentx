import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getLlmConfig: vi.fn(),
  updateLlmConfig: vi.fn(),
}));

vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: { username: 'alice', company_id: 239, is_admin: true },
  }),
}));

vi.mock('@/api/llmConfig', () => ({
  getLlmConfig: mocks.getLlmConfig,
  updateLlmConfig: mocks.updateLlmConfig,
}));

import LlmConfigSection from '@/pages/settings/LlmConfigSection';

function renderSection() {
  return render(<LlmConfigSection />);
}

function configuredResponse(overrides = {}) {
  return {
    status: 'configured',
    setup_required: false,
    missing_required: [],
    providers: {
      deepseek: {
        providerType: 'openai_compatible',
        baseUrl: 'https://proxy.example.com/v1',
        gateway: 'https://proxy.example.com/v1',
        modelName: 'company-chat-model',
        enabled: true,
        preferredTasks: ['chat'],
        apiKeyMasked: 'sk-****3456',
        tpm: { 'deepseek-chat': 200000 },
        warnAt90: true,
        ...overrides,
      },
    },
  };
}

beforeEach(() => {
  mocks.getLlmConfig.mockReset();
  mocks.updateLlmConfig.mockReset();
  localStorage.clear();
});

describe('LlmConfigSection', () => {
  it('uses apiKeyMasked only as the API key placeholder', async () => {
    mocks.getLlmConfig.mockResolvedValue(configuredResponse());

    renderSection();

    const apiKeyInput = await screen.findByPlaceholderText('sk-****3456');
    expect(apiKeyInput).toHaveAttribute('type', 'password');
    expect(apiKeyInput).toHaveValue('');
    expect(apiKeyInput).not.toHaveValue('sk-****3456');
  });

  it('saves provider contract fields and keeps blank apiKey for existing keys', async () => {
    mocks.getLlmConfig.mockResolvedValue(configuredResponse());
    mocks.updateLlmConfig.mockResolvedValue(configuredResponse({ apiKeyMasked: 'sk-****9999' }));

    renderSection();

    await screen.findByPlaceholderText('sk-****3456');
    fireEvent.change(screen.getByLabelText('网关地址'), {
      target: { value: 'https://custom.example.com/v1' },
    });
    fireEvent.change(screen.getByLabelText('\u6a21\u578b\u540d\u79f0'), {
      target: { value: 'custom-model' },
    });
    fireEvent.change(screen.getByLabelText('\u9002\u7528\u4efb\u52a1'), {
      target: { value: 'chat, analysis' },
    });
    fireEvent.click(screen.getByRole('button', { name: '\u4fdd\u5b58\u914d\u7f6e' }));

    await waitFor(() => expect(mocks.updateLlmConfig).toHaveBeenCalledTimes(1));
    expect(mocks.updateLlmConfig).toHaveBeenCalledWith('239', {
      deepseek: expect.objectContaining({
        providerType: 'openai_compatible',
        baseUrl: 'https://custom.example.com/v1',
        gateway: 'https://custom.example.com/v1',
        modelName: 'custom-model',
        enabled: true,
        preferredTasks: ['chat', 'analysis'],
        apiKey: '',
      }),
    });
  });

  it('clears the password input state after a successful save', async () => {
    mocks.getLlmConfig.mockResolvedValue(configuredResponse());
    mocks.updateLlmConfig.mockResolvedValue(configuredResponse({ apiKeyMasked: 'sk-****2222' }));

    renderSection();

    const apiKeyInput = await screen.findByPlaceholderText('sk-****3456');
    fireEvent.change(apiKeyInput, { target: { value: 'sk-new-secret' } });
    expect(apiKeyInput).toHaveValue('sk-new-secret');

    fireEvent.click(screen.getByRole('button', { name: '\u4fdd\u5b58\u914d\u7f6e' }));

    await waitFor(() => expect(mocks.updateLlmConfig).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(apiKeyInput).toHaveValue(''));
    expect(await screen.findByPlaceholderText('sk-****2222')).toHaveValue('');
  });

  it('does not migrate legacy localStorage plaintext apiKey into state or payload', async () => {
    localStorage.setItem(
      'llm_providers',
      JSON.stringify({
        deepseek: {
          gateway: 'https://legacy.example.com/v1',
          apiKey: 'sk-legacy-plaintext',
        },
      })
    );
    mocks.getLlmConfig.mockResolvedValue({
      status: 'not_configured',
      setup_required: true,
      missing_required: ['apiKey'],
      providers: {},
    });
    mocks.updateLlmConfig.mockResolvedValue({
      status: 'not_configured',
      setup_required: true,
      missing_required: ['apiKey'],
      providers: {},
    });

    renderSection();

    const apiKeyInput = await screen.findByLabelText('API 密钥');
    expect(apiKeyInput).toHaveValue('');
    expect(apiKeyInput).not.toHaveValue('sk-legacy-plaintext');
    expect(localStorage.getItem('llm_providers')).toBeNull();

    fireEvent.change(screen.getByLabelText('网关地址'), {
      target: { value: 'https://proxy.example.com/v1' },
    });
    fireEvent.click(screen.getByRole('button', { name: '\u4fdd\u5b58\u914d\u7f6e' }));

    await waitFor(() => expect(mocks.updateLlmConfig).toHaveBeenCalledTimes(1));
    expect(JSON.stringify(mocks.updateLlmConfig.mock.calls[0][1])).not.toContain('sk-legacy-plaintext');
  });
});
