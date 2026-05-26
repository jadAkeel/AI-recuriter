import { useCallback, useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/client';
import { useAuth } from '../../context/auth';
import { AlertTriangle, ArrowUpRight, BarChart3, Bot, Briefcase, Eye, FileText, GitCompare, Loader2, Trash2, Users, X } from 'lucide-react';
import type { DashboardInterviewResult, InterviewSessionStatus } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

const analysisLabel = (status: string) => {
  if (status === 'ready') return 'Report ready';
  if (status === 'saved') return 'Saved match';
  if (status === 'queued') return 'Analysis queued';
  if (status === 'analyzing') return 'Analyzing interview';
  if (status === 'in_progress') return 'In progress';
  return status || 'Unknown';
};

const questionId = (question?: { id?: string; question_id?: string }) => question?.id || question?.question_id || '';
const questionText = (question?: { question?: string; question_text?: string }) => question?.question || question?.question_text || 'Question text is not available.';

export default function RecruiterDashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState({ jobs: 0, candidates: 0, matches: 0, reports: 0 });
  const [interviewResults, setInterviewResults] = useState<DashboardInterviewResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selectedResult, setSelectedResult] = useState<DashboardInterviewResult | null>(null);
  const [details, setDetails] = useState<InterviewSessionStatus | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [jobs, candidates, results] = await Promise.all([
        api.get('/jobs'),
        api.get('/candidates'),
        api.get<DashboardInterviewResult[]>('/interviews/dashboard-results'),
      ]);
      const rows = Array.isArray(results.data) ? results.data : [];
      const reportIds = new Set(rows.map((row) => row.report_id).filter((id): id is string => Boolean(id)));
      setInterviewResults(rows);
      setStats({
        jobs: jobs.data.length || 0,
        candidates: candidates.data.length || 0,
        matches: rows.filter((row) => row.match_score !== null && row.match_score !== undefined).length,
        reports: reportIds.size,
      });
    } catch {
      setLoadError('Could not load the dashboard. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void loadDashboard());
  }, [loadDashboard]);

  const openDetails = async (row: DashboardInterviewResult) => {
    if (!row.session_id) return;
    setSelectedResult(row);
    setDetails(null);
    setDetailsError('');
    setDetailsLoading(true);
    try {
      const { data } = await api.get<InterviewSessionStatus>(`/interviews/${row.session_id}`);
      setDetails(data);
    } catch {
      setDetailsError('Could not load interview details. Please try again.');
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleDelete = async (row: DashboardInterviewResult) => {
    const rowKey = row.session_id || row.report_id || `${row.job_id}-${row.candidate_id}`;
    const message = row.session_id
      ? 'Delete this interview result and linked report data?'
      : row.report_id
        ? 'Delete this report and linked match result?'
        : 'Delete this saved match result?';
    if (!window.confirm(message)) return;
    setDeleteError('');
    setDeletingKey(rowKey);
    try {
      if (row.session_id) {
        await api.delete(`/interviews/${row.session_id}`);
      } else {
        await api.delete('/reports/candidate', {
          params: { job_id: row.job_id, candidate_id: row.candidate_id },
        });
      }
      if (selectedResult?.session_id === row.session_id) {
        setSelectedResult(null);
      }
      await loadDashboard();
    } catch (err: unknown) {
      setDeleteError(getApiErrorMessage(err, 'Delete failed. Please try again.'));
    } finally {
      setDeletingKey(null);
    }
  };

  const cards = [
    { title: 'Jobs', value: stats.jobs, icon: Briefcase, color: 'bg-blue-500', href: '/jobs' },
    { title: 'Candidates', value: stats.candidates, icon: Users, color: 'bg-emerald-500', href: '/candidates' },
    { title: 'Matches', value: stats.matches, icon: GitCompare, color: 'bg-violet-500', href: '/match-results' },
    { title: 'Reports', value: stats.reports, icon: BarChart3, color: 'bg-orange-500', href: '/reports' },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Welcome, {user?.full_name}</h1>
      <p className="text-gray-500 mb-8">Recruiter Dashboard — overview of your hiring pipeline</p>
      {loadError && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 flex items-start gap-3" role="alert">
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium">Dashboard data did not load.</p>
            <p>{loadError}</p>
          </div>
        </div>
      )}
      {deleteError && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 flex items-start gap-3" role="alert">
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium">Delete did not complete.</p>
            <p>{deleteError}</p>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map((card) => (
          <Link
            key={card.title}
            to={card.href}
            className="group bg-white rounded-xl shadow-sm border p-6 hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md transition-all"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">{card.title}</p>
                <p className="text-3xl font-bold text-gray-900 mt-1">{loading ? '...' : card.value}</p>
              </div>
              <div className={`${card.color} p-3 rounded-lg relative`}>
                <card.icon className="w-6 h-6 text-white" />
                <ArrowUpRight className="w-3.5 h-3.5 text-white absolute -right-1 -top-1 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div className="mt-8 bg-white rounded-xl shadow-sm border p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Match Results & Reports</h2>
            <p className="text-sm text-gray-500">Saved matches, generated reports, and interview analysis appear here.</p>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/match-results" className="text-sm text-blue-600 hover:text-blue-700">All matches</Link>
            <Link to="/reports" className="text-sm text-blue-600 hover:text-blue-700">All reports</Link>
            <Bot className="w-5 h-5 text-blue-600" />
          </div>
        </div>

        {interviewResults.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">
            {loading ? 'Loading results...' : 'No match results or reports yet.'}
          </p>
        ) : (
          <div className="space-y-3">
            {interviewResults.map((row) => {
              const isReady = row.analysis_status === 'ready';
              const isWorking = row.analysis_status === 'queued' || row.analysis_status === 'analyzing';
              const score = row.match_score ?? row.report_score ?? row.interview_score;
              const scoreLabel = row.match_score == null
                ? row.report_score == null ? 'Interview score' : 'Report score'
                : 'Final match';
              const rowKey = row.session_id || row.report_id || `${row.job_id}-${row.candidate_id}`;
              const scoreValue = score ?? 0;
              return (
                <div key={rowKey} className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 p-4 bg-gray-50 rounded-lg border border-transparent hover:border-blue-100 transition-colors">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-medium text-gray-900">{row.candidate_name || 'Candidate'}</p>
                      <span className="text-xs text-gray-400">for</span>
                      <p className="text-sm text-gray-600">{row.job_title || 'Job'}</p>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {row.session_id
                        ? `${row.answered_questions}/${row.total_questions} answers submitted`
                        : row.report_id
                          ? 'Report generated from candidate profile'
                          : 'Saved from matching'}
                    </p>
                  </div>

                  <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    <div className="text-right">
                      <p className="text-xl font-bold text-blue-600">{(scoreValue * 100).toFixed(1)}%</p>
                      <p className="text-xs text-gray-500">{scoreLabel}</p>
                    </div>
                    <span className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
                      isReady
                        ? 'bg-green-50 text-green-700'
                        : isWorking
                          ? 'bg-yellow-50 text-yellow-700'
                          : 'bg-gray-100 text-gray-600'
                    }`}>
                      {isWorking && <Loader2 className="w-3 h-3 animate-spin" />}
                      {analysisLabel(row.analysis_status)}
                    </span>
                    <div className="flex items-center gap-2 flex-wrap">
                      {row.session_id && (
                        <button
                          onClick={() => openDetails(row)}
                          className="inline-flex items-center justify-center gap-1 px-3 py-2 border border-blue-200 text-blue-700 bg-white rounded-lg hover:bg-blue-50 text-sm"
                        >
                          <Eye className="w-4 h-4" />
                          View details
                        </button>
                      )}
                      <Link
                        to={`/reports?job_id=${row.job_id}&candidate_id=${row.candidate_id}&auto=1`}
                        className="inline-flex items-center justify-center gap-1 px-3 py-2 border rounded-lg hover:bg-white text-sm text-gray-700"
                      >
                        <FileText className="w-4 h-4" />
                        {row.report_id ? 'Open report' : 'Create report'}
                      </Link>
                    </div>
                    <button
                      onClick={() => handleDelete(row)}
                      disabled={deletingKey === rowKey}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors self-start sm:self-auto disabled:opacity-50"
                      aria-label={row.session_id ? 'Delete interview result' : row.report_id ? 'Delete report' : 'Delete saved match'}
                    >
                      {deletingKey === rowKey ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {selectedResult && (
        <div
          className="fixed inset-0 z-50 bg-black/40 p-4 flex items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-label="Interview details"
          onClick={() => setSelectedResult(null)}
        >
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[88vh] flex flex-col" onClick={(event) => event.stopPropagation()}>
            <div className="p-5 border-b flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-gray-900">Interview Details</h2>
                <p className="text-sm text-gray-500">
                  {selectedResult.candidate_name || 'Candidate'} for {selectedResult.job_title || 'Job'}
                </p>
              </div>
              <button
                onClick={() => setSelectedResult(null)}
                className="p-2 rounded-lg hover:bg-gray-100"
                aria-label="Close interview details"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="bg-blue-50 rounded-lg p-3">
                  <p className="text-xs text-blue-600">Final score</p>
                  <p className="text-xl font-bold text-blue-700">{((selectedResult.match_score ?? selectedResult.report_score ?? selectedResult.interview_score) * 100).toFixed(1)}%</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Answers</p>
                  <p className="text-xl font-bold text-gray-900">{selectedResult.answered_questions}/{selectedResult.total_questions}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Status</p>
                  <p className="text-sm font-semibold text-gray-900">{analysisLabel(selectedResult.analysis_status)}</p>
                </div>
              </div>

              {detailsLoading && (
                <div className="flex items-center gap-2 text-sm text-blue-600 bg-blue-50 rounded-lg p-4" role="status">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Loading interview answers...
                </div>
              )}

              {detailsError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700" role="alert">
                  {detailsError}
                </div>
              )}

              {details && details.answers.length > 0 && (
                <div className="space-y-3">
                  {details.answers.map((answer, index) => {
                    const question = details.questions.find((item) => questionId(item) === answer.question_id);
                    return (
                      <div key={`${answer.question_id}-${index}`} className="border rounded-lg p-4">
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div>
                            <p className="text-xs text-gray-500">Question {index + 1} · {answer.skill || question?.skill || 'General'}</p>
                            <p className="font-medium text-gray-900 mt-1">{questionText(question)}</p>
                          </div>
                          <span className="px-2 py-1 rounded bg-blue-50 text-blue-700 text-xs font-semibold">
                            {(answer.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap mb-2">
                          {answer.answer}
                        </div>
                        <p className="text-sm text-gray-600"><span className="font-medium">Feedback:</span> {answer.feedback}</p>
                      </div>
                    );
                  })}
                </div>
              )}

              {details && details.answers.length === 0 && (
                <div className="text-sm text-gray-400 text-center py-6">No answers have been submitted yet.</div>
              )}

              <div className="flex flex-col sm:flex-row gap-2 pt-2">
                <Link
                  to={`/reports?job_id=${selectedResult.job_id}&candidate_id=${selectedResult.candidate_id}&auto=1`}
                  className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
                >
                  <FileText className="w-4 h-4" />
                  Open full report
                </Link>
                <button
                  onClick={() => setSelectedResult(null)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
