import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertCircle, ArrowLeft, Bot, CheckCircle, Loader, Send, User } from 'lucide-react';
import { buildApiWebSocketUrl } from '../utils/network';

type ChatMessage = {
  id: string;
  role: 'ai' | 'candidate' | 'evaluation' | 'system';
  text: string;
  meta?: string;
};

type LiveQuestion = {
  question_id: string;
  question: string;
  skill?: string;
  difficulty?: string;
  question_number?: number;
  total?: number;
};

const messageId = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export default function LiveInterview() {
  const { session_id } = useParams<{ session_id: string }>();
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState<LiveQuestion | null>(null);
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    if (!session_id) return;

    const ws = new WebSocket(buildApiWebSocketUrl(`/ws/interview/${session_id}`));
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setError('');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'question') {
          setCurrentQuestion(data);
          setSubmitting(false);
          setMessages((items) => [
            ...items,
            {
              id: messageId(),
              role: 'ai',
              text: data.question,
              meta: `Question ${data.question_number} of ${data.total} • ${data.skill || 'General'}`,
            },
          ]);
          return;
        }

        if (data.type === 'evaluation') {
          setSubmitting(false);
          const pct = Math.round(Number(data.score || 0) * 100);
          setMessages((items) => [
            ...items,
            {
              id: messageId(),
              role: 'evaluation',
              text: data.feedback || 'Answer saved.',
              meta: `AI evaluation • ${pct}%`,
            },
          ]);
          return;
        }

        if (data.type === 'complete') {
          setComplete(true);
          setSubmitting(false);
          setCurrentQuestion(null);
          const pct = Math.round(Number(data.average_score || 0) * 100);
          setMessages((items) => [
            ...items,
            {
              id: messageId(),
              role: 'system',
              text: 'Interview complete. Thank you for your answers.',
              meta: `Average score ${pct}%`,
            },
          ]);
          return;
        }

        if (data.type === 'error') {
          setSubmitting(false);
          setMessages((items) => [
            ...items,
            { id: messageId(), role: 'system', text: data.message || 'Something went wrong.' },
          ]);
        }
      } catch {
        setMessages((items) => [
          ...items,
          { id: messageId(), role: 'system', text: 'Received an invalid message from the server.' },
        ]);
      }
    };

    ws.onerror = () => {
      setError('Could not connect to the live AI interview.');
      setSubmitting(false);
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };

    return () => ws.close();
  }, [session_id]);

  const submitAnswer = () => {
    if (!answer.trim() || !currentQuestion || wsRef.current?.readyState !== WebSocket.OPEN) return;
    const text = answer.trim();
    wsRef.current.send(JSON.stringify({
      type: 'answer',
      question_id: currentQuestion.question_id,
      answer: text,
    }));
    setMessages((items) => [
      ...items,
      { id: messageId(), role: 'candidate', text, meta: 'Your answer' },
    ]);
    setAnswer('');
    setCurrentQuestion(null);
    setSubmitting(true);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submitAnswer();
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white px-4 py-8">
      <div className="max-w-3xl mx-auto">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-blue-300 text-sm mb-2">
              <Bot className="w-4 h-4" />
              Live AI Interview • Gemma/Ollama when available
            </div>
            <h1 className="text-2xl font-bold">Live AI Chat Interview</h1>
            <p className="text-slate-400 text-sm mt-1">Answer each question in the chat. The AI evaluates and sends the next question.</p>
          </div>
          <Link to={`/interview/${session_id}`} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/10 hover:bg-white/15 text-sm">
            <ArrowLeft className="w-4 h-4" /> Standard
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-4 flex items-start gap-3 text-red-100">
            <AlertCircle className="w-5 h-5 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div className="rounded-2xl border border-white/10 bg-white/5 shadow-2xl overflow-hidden">
          <div className="h-[520px] overflow-y-auto p-5 space-y-4">
            {messages.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 text-center">
                {connected ? <Bot className="w-12 h-12 mb-3 text-blue-300" /> : <Loader className="w-8 h-8 animate-spin mb-3 text-blue-300" />}
                <p>{connected ? 'Waiting for the first question...' : 'Connecting to the AI interviewer...'}</p>
              </div>
            )}

            {messages.map((message) => {
              const isCandidate = message.role === 'candidate';
              const isEvaluation = message.role === 'evaluation';
              const isSystem = message.role === 'system';
              return (
                <div key={message.id} className={`flex ${isCandidate ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                    isCandidate
                      ? 'bg-blue-600 text-white'
                      : isEvaluation
                        ? 'bg-emerald-500/15 border border-emerald-400/30 text-emerald-50'
                        : isSystem
                          ? 'bg-slate-800 text-slate-200'
                          : 'bg-white text-slate-900'
                  }`}>
                    <div className="flex items-center gap-2 text-xs opacity-75 mb-1">
                      {isCandidate ? <User className="w-3.5 h-3.5" /> : isEvaluation || isSystem ? <CheckCircle className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                      {message.meta || (isCandidate ? 'Candidate' : 'AI Interviewer')}
                    </div>
                    <p className="whitespace-pre-wrap leading-relaxed">{message.text}</p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="border-t border-white/10 p-4 bg-slate-900/80">
            <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
              <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-slate-500'}`} />
              {complete ? 'Interview complete' : connected ? 'Connected' : 'Disconnected'}
              {submitting && <span>• AI is evaluating...</span>}
            </div>
            <div className="flex gap-3">
              <textarea
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!currentQuestion || submitting || complete}
                placeholder={complete ? 'Interview complete' : currentQuestion ? 'Type your answer. Press Enter to send, Shift+Enter for new line.' : 'Waiting for AI...'}
                className="flex-1 min-h-24 rounded-xl bg-white text-slate-900 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-60 resize-none"
              />
              <button
                onClick={submitAnswer}
                disabled={!answer.trim() || !currentQuestion || submitting || complete}
                className="self-stretch px-5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:hover:bg-blue-600 flex items-center gap-2 font-medium"
              >
                {submitting ? <Loader className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                Send
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
