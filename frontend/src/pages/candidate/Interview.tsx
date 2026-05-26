import { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../../api/client';
import { AlertTriangle, Send, MessageSquare, Briefcase } from 'lucide-react';
import type { InterviewEvaluation, InterviewSessionResponse, Job } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

export default function CandidateInterview() {
  const [searchParams] = useSearchParams();
  const requestedJobId = searchParams.get('job_id');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [session, setSession] = useState<InterviewSessionResponse | null>(null);
  const [currentAnswer, setCurrentAnswer] = useState('');
  const [currentQIndex, setCurrentQIndex] = useState(0);
  const [evaluation, setEvaluation] = useState<InterviewEvaluation | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [useLlm, setUseLlm] = useState(true);

  useEffect(() => {
    api.get<Job[]>('/jobs').then(({ data }) => {
      const list = Array.isArray(data) ? data : [];
      setJobs(list);
      if (requestedJobId && list.some((job) => job.job_id === requestedJobId)) {
        setSelectedJobId(requestedJobId);
      }
    }).catch((err: unknown) => {
      setError(getApiErrorMessage(err, 'Could not load jobs'));
    });
  }, [requestedJobId]);

  const startInterview = async () => {
    if (!selectedJobId) return;
    setError('');
    try {
      const me = (await api.get<{ candidate_id: string }>('/candidates/me')).data;
      const { data } = await api.post('/interviews/start', { job_id: selectedJobId, candidate_id: me.candidate_id });
      setSession(data);
      setCurrentQIndex(0);
      setEvaluation(null);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Could not start interview. Upload your CV first, then try again.'));
    }
  };

  const submitAnswer = async () => {
    if (!session || !currentAnswer.trim()) return;
    setSubmitting(true);
    const q = session.questions[currentQIndex];
    const questionId = q.id || q.question_id;
    if (!questionId) {
      setSubmitting(false);
      return;
    }
    try {
      await api.post('/interviews/answer', {
        session_id: session.session_id, question_id: questionId, answer: currentAnswer,
      }, { params: { use_llm: useLlm } });
      setCurrentAnswer('');

      if (currentQIndex < session.questions.length - 1) {
        setCurrentQIndex(currentQIndex + 1);
      } else {
        const { data } = await api.post('/interviews/evaluate', { session_id: session.session_id });
        setEvaluation(data);
      }
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Could not save answer. Please try again.'));
    }
    setSubmitting(false);
  };

  const selectedJob = jobs.find((j) => j.job_id === selectedJobId);

  if (evaluation) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Interview Results</h1>
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="text-center mb-6">
            <p className="text-5xl font-bold text-blue-600 mb-2">{(evaluation.overall_score * 100).toFixed(1)}%</p>
            <p className="text-gray-500">Overall Score</p>
          </div>
          <p className="text-gray-700 mb-4">{evaluation.feedback}</p>
          {evaluation.strengths?.length > 0 && (
            <div className="mb-3"><p className="font-medium text-green-700 mb-1">Strengths</p>
              <div className="flex gap-2 flex-wrap">{evaluation.strengths.map((s: string) => <span key={s} className="px-2 py-0.5 bg-green-50 text-green-700 rounded text-xs">{s}</span>)}</div>
            </div>
          )}
          {evaluation.weaknesses?.length > 0 && (
            <div><p className="font-medium text-red-700 mb-1">Areas to Improve</p>
              <div className="flex gap-2 flex-wrap">{evaluation.weaknesses.map((s: string) => <span key={s} className="px-2 py-0.5 bg-red-50 text-red-700 rounded text-xs">{s}</span>)}</div>
            </div>
          )}
          <button onClick={() => { setSession(null); setEvaluation(null); }}
            className="mt-4 px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm">New Interview</button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">AI Interview</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 mt-0.5" />
          <div className="text-sm text-red-700">
            <p>{error}</p>
            {error.toLowerCase().includes('candidate profile') && (
              <Link to="/upload-cv" className="inline-block mt-2 font-medium text-red-800 underline">
                Upload CV
              </Link>
            )}
          </div>
        </div>
      )}

      {!session && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center gap-3 mb-4">
            <MessageSquare className="w-8 h-8 text-blue-500" />
            <div>
              <p className="font-medium text-gray-900">Start a Technical Interview</p>
              <p className="text-sm text-gray-500">Choose a job to begin the AI-powered interview</p>
            </div>
          </div>
          <div className="flex gap-3">
            <select value={selectedJobId} onChange={(e) => setSelectedJobId(e.target.value)}
              className="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white">
              <option value="">-- Select a Job --</option>
              {jobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.title || 'Untitled'} ({job.seniority || 'any'})
                </option>
              ))}
            </select>
            <button onClick={startInterview} disabled={!selectedJobId}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">Start</button>
          </div>
          {selectedJob && (
            <div className="mt-3 text-sm text-gray-500 bg-gray-50 rounded-lg p-3">
              <span className="font-medium">{selectedJob.title}</span>
              {selectedJob.seniority && <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">{selectedJob.seniority}</span>}
              <div className="flex gap-2 mt-2 flex-wrap">
                {(selectedJob.required_skills || []).slice(0, 5).map((s: string) => (
                  <span key={s} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{s}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {session && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">Question {currentQIndex + 1} of {session.questions.length}</span>
                <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded">{session.questions[currentQIndex]?.skill}</span>
              </div>
              <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(event) => setUseLlm(event.target.checked)}
                  className="rounded accent-blue-600"
                />
                Use LLM evaluation
              </label>
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <Briefcase className="w-3 h-3" />
                {session.job_title || 'Job'}
              </div>
            </div>
            <p className="text-lg font-medium text-gray-900 mb-4">{session.questions[currentQIndex]?.question}</p>
            <textarea value={currentAnswer} onChange={(e) => setCurrentAnswer(e.target.value)}
              placeholder="Type your answer here..."
              className="w-full h-32 px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 mb-3" />
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">Press Enter to submit</span>
              <button onClick={submitAnswer} disabled={!currentAnswer.trim() || submitting}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                <Send className="w-4 h-4" />
                {submitting ? 'Saving...' : currentQIndex < session.questions.length - 1 ? 'Next Question' : 'Finish Interview'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
