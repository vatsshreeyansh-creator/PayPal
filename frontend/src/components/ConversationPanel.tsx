import React, { useEffect, useRef, useState } from 'react';
import { Loader2, MessageCircle, Send } from 'lucide-react';
import { api } from '../services/api';
import type { ConversationCreateRequest, ConversationResponse } from '../types/api';

interface ConversationPanelProps { context: ConversationCreateRequest; }

export const ConversationPanel: React.FC<ConversationPanelProps> = ({ context }) => {
  const [conversation, setConversation] = useState<ConversationResponse | null>(null);
  const [draft, setDraft] = useState('');
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextKey = context.context_type === 'article'
    ? context.article_id
    : `${context.symbol}:${context.research_context?.generated_at ?? 'unknown-report'}`;
  const storageKey = `tradepoint-ai-conversation:${context.context_type}:${contextKey}`;
  const [savedState] = useState(() => {
    try {
      const id = window.localStorage.getItem(storageKey);
      return { id, restoring: id !== null, error: null as string | null };
    } catch {
      return { id: null, restoring: false, error: 'Saved conversations are unavailable in this browser.' };
    }
  });
  const [restoring, setRestoring] = useState(savedState.restoring);
  const [restoreError, setRestoreError] = useState(savedState.error);
  const selectionVersion = useRef(0);
  const sendingRef = useRef(false);
  const startingRef = useRef(false);
  const pendingRequest = useRef<{ content: string; id: string } | null>(null);

  useEffect(() => {
    const savedId = savedState.id;
    if (!savedId) return;
    let active = true;
    const restoreVersion = selectionVersion.current;
    void api.getConversation(savedId).then((value) => {
      const expectedReference = context.context_type === 'article' ? context.article_id : context.symbol;
      if (value.context_type !== context.context_type || value.context_reference !== expectedReference) {
        throw new Error('Saved conversation context does not match this article or report.');
      }
      if (active && selectionVersion.current === restoreVersion) setConversation(value);
    }).catch((reason: unknown) => {
      if (active) {
        try { window.localStorage.removeItem(storageKey); } catch { /* Storage may be disabled. */ }
        setRestoreError(reason instanceof Error ? reason.message : 'Conversation could not be restored.');
      }
    }).finally(() => {
      if (active) setRestoring(false);
    });
    return () => { active = false; };
  }, [storageKey, savedState.id, context.context_type, context.article_id, context.symbol]);

  const start = async () => {
    if (restoring || startingRef.current || conversation) return;
    startingRef.current = true;
    selectionVersion.current += 1;
    setStarting(true); setError(null); setRestoreError(null);
    try {
      const created = await api.createConversation(context);
      setConversation(created);
      try { window.localStorage.setItem(storageKey, created.conversation_id); }
      catch { setError('Conversation started, but this browser could not save it for resumption.'); }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Could not start the conversation.');
    } finally { startingRef.current = false; setStarting(false); }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!conversation || !draft.trim() || sending || restoring || sendingRef.current) return;
    const content = draft.trim();
    const request = pendingRequest.current?.content === content
      ? pendingRequest.current
      : { content, id: window.crypto.randomUUID() };
    pendingRequest.current = request;
    sendingRef.current = true;
    setSending(true); setError(null);
    try {
      setConversation(await api.sendConversationMessage(conversation.conversation_id, request.id, content));
      setDraft('');
      pendingRequest.current = null;
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'The assistant could not answer.');
    } finally { sendingRef.current = false; setSending(false); }
  };

  return <section className="mt-4 rounded-xl border border-indigo-500/20 bg-slate-950/70 p-4" aria-label="AI conversation">
    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-100"><MessageCircle className="h-4 w-4 text-indigo-300" />Ask a follow-up</div>
    {restoreError && <p role="alert" className="mb-3 text-xs text-rose-300">{restoreError}</p>}
    {error && <p role="alert" className="mb-3 text-xs text-rose-300">{error}</p>}
    {restoring && <p role="status" className="mb-3 text-xs text-slate-400">Restoring saved conversation…</p>}
    {!conversation ? <button type="button" onClick={() => void start()} disabled={restoring || starting}
      className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-60">
      {starting ? <><Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />Preparing context…</> : 'Start contextual conversation'}
    </button> : <>
      <div className="mb-3 max-h-72 space-y-3 overflow-y-auto" aria-live="polite">
        {conversation.messages.map((message, index) => <article key={`${message.created_at}-${index}`}
          className={`rounded-lg p-3 text-xs ${message.role === 'user' ? 'ml-6 bg-indigo-950/50 text-indigo-100' : 'mr-6 bg-slate-900 text-slate-200'}`}>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">{message.role === 'user' ? 'You' : `TradePoint AI${message.provider ? ` · ${message.provider}` : ''}`}</div>
          <p className="whitespace-pre-wrap">{message.content}</p>
        </article>)}
        {!conversation.messages.length && <p className="text-xs text-slate-500">Context pinned: {conversation.context_title}. Ask your first question.</p>}
      </div>
      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor={`conversation-question-${conversation.conversation_id}`} className="sr-only">Your follow-up question</label>
        <input id={`conversation-question-${conversation.conversation_id}`} value={draft}
          onChange={(event) => {
            const value = event.target.value;
            if (pendingRequest.current && value.trim() !== pendingRequest.current.content) pendingRequest.current = null;
            setDraft(value);
          }} maxLength={4000} required
          placeholder="Ask a follow-up question…" disabled={sending || restoring}
          className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500" />
        <button type="submit" disabled={sending || !draft.trim()} aria-label="Send question"
          className="rounded-lg bg-indigo-600 px-3 text-white disabled:opacity-50">
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </>}
  </section>;
};
