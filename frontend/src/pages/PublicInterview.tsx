import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Send, CheckCircle, AlertCircle, Loader, Keyboard, Mic } from 'lucide-react';
import type { InterviewEvaluation, InterviewSessionResponse } from '../types/api';
import VoiceRecorder from '../components/VoiceRecorder';

const API = '/api/v1';

export default function PublicInterview() {
  const { session_id } = useParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [interview, setInterview] = useState<InterviewSessionResponse | null>(null);
  const [currentQIndex, setCurrentQIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [mode, setMode] = useState<'text' | 'voice'>('text');
  const [done, setDone] = useState(false);
  const [result, setResult] = useState<InterviewEvaluation | null>(null);

  useEffect(() => {
    if (!session_id) return;
    fetch(`${API}/interviews/public/${session_id}`)
      .then((r) => r.json())
      .then((data: InterviewSessionResponse | InterviewEvaluation & { is_completed?: boolean }) => {
        if (data.is_completed) {
          setDone(true);
          setResult(data as InterviewEvaluation);
        } else if ('questions' in data && data.questions?.length > 0) {
          setInterview(data);
        } else {
          setError('No questions available');
        }
      })
      .catch(() => setError('Could not load interview'))
      .finally(() => setLoading(false));
  }, [session_id]);

  const finishOrAdvance = async () => {
    if (!interview) return;
    if (currentQIndex < interview.questions.length - 1) {
      setCurrentQIndex(currentQIndex + 1);
      setAnswer('');
    } else {
      const evalRes = await fetch(`${API}/interviews/public/${session_id}/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!evalRes.ok) throw new Error('Interview evaluation failed');
      const evalData = await evalRes.json();
      setResult(evalData);
      setDone(true);
    }
  };

  const submitAnswer = async () => {
    if (!interview || !answer.trim()) return;
    setSubmitting(true);
    const q = interview.questions[currentQIndex];
    const realQId = q.id || q.question_id;
    if (!realQId) {
      setError('Invalid question');
      setSubmitting(false);
      return;
    }

    try {
      const res = await fetch(`${API}/interviews/public/${session_id}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_id: realQId, answer }),
      });
      if (!res.ok) throw new Error('Answer submission failed');
      await res.json();
      await finishOrAdvance();
    } catch {
      setError('Failed to submit answer');
    }
    setSubmitting(false);
  };

  const submitVoiceAnswer = async (blob: Blob) => {
    if (!interview) return;
    const q = interview.questions[currentQIndex];
    const realQId = q.id || q.question_id;
    if (!realQId) {
      setError('Invalid question');
      return;
    }

    setTranscribing(true);
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('question_id', realQId);
      formData.append('file', blob, 'answer.webm');
      const res = await fetch(`${API}/interviews/public/${session_id}/voice-answer`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error('Voice answer submission failed');
      const data = await res.json();
      setAnswer(data.answer || '');
      await finishOrAdvance();
    } catch {
      setError('Failed to submit voice answer');
    } finally {
      setTranscribing(false);
      setSubmitting(false);
    }
  };

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Loader className="w-8 h-8 text-blue-500 animate-spin" />
    </div>
  );

  if (error) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="bg-white rounded-xl shadow-sm border p-8 text-center max-w-md">
        <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
        <p className="text-gray-700">{error}</p>
      </div>
    </div>
  );

  if (done && result) return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Interview Complete!</h1>
          <div className="my-8">
            <p className="text-5xl font-bold text-blue-600 mb-2">{(result.overall_score * 100).toFixed(1)}%</p>
            <p className="text-gray-500">Overall Score</p>
          </div>
          <p className="text-gray-700 mb-6">{result.feedback}</p>
          {result.strengths?.length > 0 && (
            <div className="mb-4 text-left">
              <p className="font-medium text-green-700 mb-2">Strengths</p>
              <div className="flex gap-2 flex-wrap">{result.strengths.map((s: string) => <span key={s} className="px-3 py-1 bg-green-50 text-green-700 rounded text-sm">{s}</span>)}</div>
            </div>
          )}
          {result.weaknesses?.length > 0 && (
            <div className="mb-4 text-left">
              <p className="font-medium text-red-700 mb-2">Areas to Improve</p>
              <div className="flex gap-2 flex-wrap">{result.weaknesses.map((w: string) => <span key={w} className="px-3 py-1 bg-red-50 text-red-700 rounded text-sm">{w}</span>)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  if (!interview) return null;

  const currentQ = interview.questions[currentQIndex];

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Technical Interview</h1>
          <p className="text-gray-500">{interview.job_title}</p>
          <p className="text-sm text-gray-400 mt-1">Candidate: {interview.candidate_name}</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-500">
              Question {(interview.answered_count ?? 0) + currentQIndex + 1} of {interview.total_questions ?? interview.questions.length}
            </span>
            <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded">{currentQ?.skill || currentQ?.category || 'General'}</span>
          </div>

          <p className="text-lg font-medium text-gray-900 mb-4">{currentQ?.question || currentQ?.question_text}</p>

          <div className="flex bg-gray-100 rounded-lg p-0.5 mb-4 w-fit">
            <button
              onClick={() => setMode('text')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md ${mode === 'text' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500'}`}
            >
              <Keyboard className="w-4 h-4" /> Written
            </button>
            <button
              onClick={() => setMode('voice')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md ${mode === 'voice' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500'}`}
            >
              <Mic className="w-4 h-4" /> Voice
            </button>
          </div>

          {mode === 'text' ? (
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer here..."
              className="w-full h-40 px-4 py-3 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 mb-4 resize-none"
            />
          ) : (
            <div className="border rounded-lg p-4 mb-4">
              <VoiceRecorder
                onRecordingComplete={submitVoiceAnswer}
                disabled={submitting || transcribing}
                maxDuration={120}
              />
              {transcribing && (
                <div className="flex items-center gap-2 text-sm text-blue-600 mt-3">
                  <Loader className="w-4 h-4 animate-spin" />
                  Processing voice answer...
                </div>
              )}
            </div>
          )}

          {mode === 'text' && (
            <button
              onClick={submitAnswer}
              disabled={!answer.trim() || submitting}
              className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              <Send className="w-4 h-4" />
              {submitting ? 'Saving...' : currentQIndex < interview.questions.length - 1 ? 'Next Question' : 'Finish Interview'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
