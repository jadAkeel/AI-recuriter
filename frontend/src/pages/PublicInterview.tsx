import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertCircle, Bot, CheckCircle, ChevronLeft, ChevronRight, Keyboard, Loader, Mic, Send } from 'lucide-react';
import type { InterviewEvaluation, InterviewQuestion, InterviewSessionResponse, PublicInterviewAnswerResponse } from '../types/api';
import VoiceRecorder from '../components/VoiceRecorder';

const API = '/api/v1';

const getResponseError = async (res: Response, fallback: string) => {
  try {
    const data = await res.json();
    return typeof data.detail === 'string' ? data.detail : fallback;
  } catch {
    return fallback;
  }
};

const questionId = (question?: InterviewQuestion | null) => question?.id || question?.question_id || '';
const questionText = (question?: InterviewQuestion | null) => question?.question || question?.question_text || '';

const answeredIdsFromSession = (session: InterviewSessionResponse) => {
  if (session.answered_question_ids?.length) return new Set(session.answered_question_ids);
  const answeredCount = session.answered_count ?? 0;
  return new Set(session.questions.slice(0, answeredCount).map(questionId).filter(Boolean));
};

export default function PublicInterview() {
  const { session_id } = useParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [interview, setInterview] = useState<InterviewSessionResponse | null>(null);
  const [currentQIndex, setCurrentQIndex] = useState(0);
  const [answersByQuestionId, setAnswersByQuestionId] = useState<Record<string, string>>({});
  const [answeredQuestionIds, setAnsweredQuestionIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [mode, setMode] = useState<'text' | 'voice'>('text');
  const [done, setDone] = useState(false);
  const [result, setResult] = useState<InterviewEvaluation | null>(null);
  const [submitError, setSubmitError] = useState('');
  const [lastFeedback, setLastFeedback] = useState<PublicInterviewAnswerResponse | null>(null);

  useEffect(() => {
    if (!session_id) return;

    let active = true;
    queueMicrotask(() => {
      setLoading(true);
      setError('');

      fetch(`${API}/interviews/public/${session_id}`)
        .then(async (res) => {
          if (!res.ok) throw new Error(await getResponseError(res, 'Could not load interview'));
          return res.json();
        })
        .then((data: InterviewSessionResponse | (InterviewEvaluation & { is_completed?: boolean })) => {
          if (!active) return;
          if (data.is_completed) {
            setDone(true);
            setResult(data as InterviewEvaluation);
            return;
          }

          if ('questions' in data && data.questions?.length > 0) {
            setInterview(data);
            setAnsweredQuestionIds(answeredIdsFromSession(data));
            const currentQuestionIndex = data.current_question_id
              ? data.questions.findIndex((question) => questionId(question) === data.current_question_id)
              : Math.min(data.answered_count ?? 0, data.questions.length - 1);
            setCurrentQIndex(currentQuestionIndex >= 0 ? currentQuestionIndex : 0);
            return;
          }

          setError('No questions available');
        })
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : 'Could not load interview');
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });

    return () => {
      active = false;
    };
  }, [session_id]);

  const evaluateInterview = async () => {
    if (!session_id) return;
    setEvaluating(true);
    setSubmitError('');
    try {
      const evalRes = await fetch(`${API}/interviews/public/${session_id}/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!evalRes.ok) throw new Error(await getResponseError(evalRes, 'Interview evaluation failed'));
      const evalData = await evalRes.json();
      setResult(evalData);
      setDone(true);
    } finally {
      setEvaluating(false);
    }
  };

  const markAnswerSaved = (savedQuestionId: string, data: PublicInterviewAnswerResponse) => {
    if (!interview) return;

    const totalQuestions = interview.total_questions ?? interview.questions.length;
    const nextAnsweredCount = Math.min(
      totalQuestions,
      Math.max(interview.answered_count ?? 0, answeredQuestionIds.size) + 1,
    );
    const nextQuestionId = questionId(data.next_question);
    const existingNextIndex = nextQuestionId
      ? interview.questions.findIndex((question) => questionId(question) === nextQuestionId)
      : -1;

    setAnsweredQuestionIds((previous) => {
      const next = new Set(previous);
      next.add(savedQuestionId);
      return next;
    });
    setInterview((previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        answered_count: nextAnsweredCount,
        current_question_id: nextQuestionId || null,
        questions: data.next_question && existingNextIndex < 0
          ? [...previous.questions, data.next_question]
          : previous.questions,
      };
    });
    setLastFeedback(data);
    setSubmitError('');

    if (nextQuestionId) {
      setCurrentQIndex(existingNextIndex >= 0 ? existingNextIndex : interview.questions.length);
    }
  };

  const submitAnswer = async () => {
    if (!interview) return;
    const currentQuestion = interview.questions[currentQIndex];
    const currentQuestionId = questionId(currentQuestion);
    const answer = answersByQuestionId[currentQuestionId]?.trim() || '';
    if (!currentQuestionId || !answer) return;

    setSubmitting(true);
    setSubmitError('');
    try {
      const res = await fetch(`${API}/interviews/public/${session_id}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_id: currentQuestionId, answer }),
      });
      if (!res.ok) throw new Error(await getResponseError(res, 'Answer submission failed'));
      const data = await res.json() as PublicInterviewAnswerResponse;
      markAnswerSaved(currentQuestionId, data);

      if (!data.next_question) {
        try {
          await evaluateInterview();
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Interview evaluation failed';
          setSubmitError(`Your answer was saved, but final evaluation could not load. ${message}`);
        }
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setSubmitting(false);
    }
  };

  const submitVoiceAnswer = async (blob: Blob) => {
    if (!interview) return;
    const currentQuestion = interview.questions[currentQIndex];
    const currentQuestionId = questionId(currentQuestion);
    if (!currentQuestionId) {
      setError('Invalid question');
      return;
    }

    setSubmitError('');
    setTranscribing(true);
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('question_id', currentQuestionId);
      formData.append('file', blob, 'answer.webm');
      const res = await fetch(`${API}/interviews/public/${session_id}/voice-answer`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error(await getResponseError(res, 'Voice answer submission failed'));
      const data = await res.json() as PublicInterviewAnswerResponse;
      setAnswersByQuestionId((previous) => ({ ...previous, [currentQuestionId]: data.answer }));
      markAnswerSaved(currentQuestionId, data);

      if (!data.next_question) {
        try {
          await evaluateInterview();
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Interview evaluation failed';
          setSubmitError(`Your voice answer was saved, but final evaluation could not load. ${message}`);
        }
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to submit voice answer');
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
            <p className="text-5xl font-bold text-blue-600 mb-2">{(Number(result.overall_score || 0) * 100).toFixed(1)}%</p>
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

  const questions = interview.questions;
  const currentQ = questions[currentQIndex];
  const currentQuestionId = questionId(currentQ);
  const answeredCount = Math.max(interview.answered_count ?? 0, answeredQuestionIds.size);
  const totalQuestions = interview.total_questions ?? questions.length;
  const requiredQuestionId = interview.current_question_id || questionId(questions[answeredCount]);
  const isAnswered = currentQuestionId ? answeredQuestionIds.has(currentQuestionId) : false;
  const canSubmitCurrent = Boolean(currentQuestionId && currentQuestionId === requiredQuestionId && !isAnswered);
  const allAnswered = answeredCount >= totalQuestions;
  const currentAnswer = currentQuestionId ? answersByQuestionId[currentQuestionId] || '' : '';

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Technical Interview</h1>
          <p className="text-gray-500">{interview.job_title}</p>
          <p className="text-sm text-gray-400 mt-1">Candidate: {interview.candidate_name}</p>
        </div>

        <Link
          to={`/interview/live/${session_id}`}
          className="mb-4 flex items-center justify-between gap-3 bg-slate-900 text-white rounded-xl p-4 hover:bg-slate-800 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-500/20 text-blue-300 flex items-center justify-center">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <p className="font-medium">Prefer live AI chat?</p>
              <p className="text-sm text-slate-300">Open a real-time interview chat powered by the local Ollama model when available.</p>
            </div>
          </div>
          <span className="text-sm text-blue-200">Open</span>
        </Link>
        

        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
          <aside className="bg-white rounded-xl shadow-sm border p-4 h-fit">
            <div className="flex items-center justify-between text-sm mb-3">
              <span className="font-medium text-gray-900">Progress</span>
              <span className="text-gray-500">{answeredCount}/{totalQuestions}</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-4">
              <div className="h-full bg-blue-600" style={{ width: `${totalQuestions ? (answeredCount / totalQuestions) * 100 : 0}%` }} />
            </div>
            <div className="grid grid-cols-4 lg:grid-cols-3 gap-2">
              {questions.map((question, index) => {
                const id = questionId(question);
                const answered = answeredQuestionIds.has(id);
                const active = index === currentQIndex;
                return (
                  <button
                    key={id || index}
                    onClick={() => setCurrentQIndex(index)}
                    className={`h-10 rounded-lg text-sm font-medium border transition-colors ${
                      active
                        ? 'border-blue-600 bg-blue-600 text-white'
                        : answered
                          ? 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100'
                          : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                    }`}
                    aria-label={`Go to question ${index + 1}`}
                  >
                    {index + 1}
                  </button>
                );
              })}
            </div>
          </aside>

          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm text-gray-500">
                Question {currentQIndex + 1} of {totalQuestions}
              </span>
              <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded">{currentQ?.skill || currentQ?.category || 'General'}</span>
            </div>

            <p className="text-lg font-medium text-gray-900 mb-4">{questionText(currentQ)}</p>

            {isAnswered && (
              <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4 text-sm text-green-700">
                This question has been answered. You can review it, but answers cannot be changed after submission.
              </div>
            )}

            {!isAnswered && !canSubmitCurrent && !allAnswered && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4 text-sm text-yellow-800">
                You can preview this question now. Submit the earlier unanswered question before answering this one.
              </div>
            )}

            {lastFeedback?.question_id === currentQuestionId && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-800">
                Answer saved. {lastFeedback.using_llm ? 'AI evaluation completed.' : 'Quick evaluation completed.'}
              </div>
            )}

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
                value={currentAnswer}
                onChange={(event) => {
                  if (!currentQuestionId) return;
                  setAnswersByQuestionId((previous) => ({ ...previous, [currentQuestionId]: event.target.value }));
                }}
                disabled={!canSubmitCurrent || submitting || evaluating}
                placeholder={isAnswered ? 'Answer already submitted.' : canSubmitCurrent ? 'Type your answer here...' : 'Preview only until earlier questions are answered.'}
                className="w-full h-40 px-4 py-3 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 mb-4 resize-none disabled:bg-gray-50 disabled:text-gray-500"
              />
            ) : (
              <div className="border rounded-lg p-4 mb-4">
                <VoiceRecorder
                  onRecordingComplete={submitVoiceAnswer}
                  disabled={!canSubmitCurrent || submitting || transcribing || evaluating}
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

            {submitError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 text-sm text-red-700">
                {submitError}
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
              <div className="flex gap-2">
                <button
                  onClick={() => setCurrentQIndex((index) => Math.max(0, index - 1))}
                  disabled={currentQIndex === 0}
                  className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 text-sm"
                >
                  <ChevronLeft className="w-4 h-4" /> Previous
                </button>
                <button
                  onClick={() => setCurrentQIndex((index) => Math.min(questions.length - 1, index + 1))}
                  disabled={currentQIndex >= questions.length - 1}
                  className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 text-sm"
                >
                  Next <ChevronRight className="w-4 h-4" />
                </button>
              </div>

              {allAnswered ? (
                <button
                  onClick={() => {
                    evaluateInterview().catch((err) => {
                      setSubmitError(err instanceof Error ? err.message : 'Interview evaluation failed');
                    });
                  }}
                  disabled={evaluating}
                  className="flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
                >
                  {evaluating ? <Loader className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                  {evaluating ? 'Loading result...' : 'Show Final Result'}
                </button>
              ) : true && (
                <button
                  onClick={submitAnswer}
                  disabled={!canSubmitCurrent || !currentAnswer.trim() || submitting || evaluating}
                  className="flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
                >
                  {submitting ? <Loader className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  {submitting ? 'Saving...' : answeredCount + 1 >= totalQuestions ? 'Finish Interview' : 'Save & Continue'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
