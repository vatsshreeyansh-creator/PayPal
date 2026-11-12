// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import type { ConversationCreateRequest, ConversationResponse } from '../types/api';
import { ConversationPanel } from './ConversationPanel';

const articleContext: ConversationCreateRequest = {
  context_type: 'article', article_id: 'article-1', symbol: null, research_context: null,
};

function response(id: string, title: string, reference = 'article-1'): ConversationResponse {
  return {
    conversation_id: id, context_type: 'article', context_reference: reference, context_title: title,
    created_at: '2026-11-10T10:00:00Z', messages: [],
  };
}

let host: HTMLDivElement;
let root: Root;

function mount(context = articleContext, key = 'article-1') {
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  act(() => root.render(<ConversationPanel key={key} context={context} />));
}

function startButton(): HTMLButtonElement {
  const button = [...host.querySelectorAll('button')].find((item) => item.textContent?.includes('Start contextual conversation'));
  if (!button) throw new Error('Conversation start button is missing');
  return button;
}

async function clickStart() {
  await act(async () => { startButton().click(); await Promise.resolve(); });
}

afterEach(() => {
  if (root) act(() => root.unmount());
  host?.remove();
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ConversationPanel restoration and request reliability', () => {
  it('restores a saved conversation and disables creating another while loading', async () => {
    window.localStorage.setItem('tradepoint-ai-conversation:article:article-1', 'saved-id');
    let resolveRestore!: (value: ConversationResponse) => void;
    const restore = vi.spyOn(api, 'getConversation').mockReturnValue(new Promise((resolve) => { resolveRestore = resolve; }));
    const create = vi.spyOn(api, 'createConversation');
    mount();

    expect(restore).toHaveBeenCalledWith('saved-id');
    expect(host.textContent).toContain('Restoring saved conversation…');
    expect(startButton().disabled).toBe(true);
    await clickStart();
    expect(create).not.toHaveBeenCalled();

    await act(async () => { resolveRestore(response('saved-id', 'Saved TCS article')); await Promise.resolve(); });
    expect(host.textContent).toContain('Saved TCS article');
    expect(host.textContent).not.toContain('Restoring saved conversation…');
    expect(host.querySelector('input[placeholder="Ask a follow-up question…"]')).not.toBeNull();
  });

  it('clears an invalid saved ID after restore failure and allows a fresh start', async () => {
    window.localStorage.setItem('tradepoint-ai-conversation:article:article-1', 'expired-id');
    vi.spyOn(api, 'getConversation').mockRejectedValue(new Error('Conversation not found.'));
    vi.spyOn(api, 'createConversation').mockResolvedValue(response('new-id', 'Fresh conversation'));
    mount();

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Conversation not found.');
    expect(window.localStorage.getItem('tradepoint-ai-conversation:article:article-1')).toBeNull();
    expect(startButton().disabled).toBe(false);
    await clickStart();
    expect(host.textContent).toContain('Fresh conversation');
  });

  it('does not let a late restore from a replaced article overwrite the new selection', async () => {
    window.localStorage.setItem('tradepoint-ai-conversation:article:article-1', 'old-id');
    let resolveOld!: (value: ConversationResponse) => void;
    vi.spyOn(api, 'getConversation').mockReturnValue(new Promise((resolve) => { resolveOld = resolve; }));
    vi.spyOn(api, 'createConversation').mockResolvedValue(response('new-id', 'New article conversation', 'article-2'));
    mount(articleContext, 'article-1');

    const nextContext: ConversationCreateRequest = { ...articleContext, article_id: 'article-2' };
    act(() => root.render(<ConversationPanel key="article-2" context={nextContext} />));
    await clickStart();
    expect(host.textContent).toContain('New article conversation');

    await act(async () => { resolveOld(response('old-id', 'Old article conversation')); await Promise.resolve(); });
    expect(host.textContent).toContain('New article conversation');
    expect(host.textContent).not.toContain('Old article conversation');
  });

  it('reuses the request ID for a retry of the same unsent question', async () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'request-uuid-1') });
    vi.spyOn(api, 'createConversation').mockResolvedValue(response('conversation-id', 'TCS article'));
    const send = vi.spyOn(api, 'sendConversationMessage')
      .mockRejectedValueOnce(new Error('Temporary provider error.'))
      .mockResolvedValue(response('conversation-id', 'TCS article'));
    mount();
    await clickStart();

    const input = host.querySelector<HTMLInputElement>('input[placeholder="Ask a follow-up question…"]');
    const form = host.querySelector('form');
    if (!input || !form) throw new Error('Message form was not rendered');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (!setter) throw new Error('Native input setter is unavailable');
    setter.call(input, 'Why did margins decline?');
    act(() => input.dispatchEvent(new Event('input', { bubbles: true })));
    await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); });
    expect(input.value).toBe('Why did margins decline?');
    await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); });

    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[0][1]).toBe('request-uuid-1');
    expect(send.mock.calls[1][1]).toBe('request-uuid-1');
  });
});
