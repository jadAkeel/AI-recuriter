import { useState, useEffect, useCallback } from 'react';
import api from '../../api/client';
import { Plus, Pencil, Trash2, GitCompare, X, AlertTriangle } from 'lucide-react';
import type { Candidate, Job, MatchResult } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [description, setDescription] = useState('');
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editRequiredSkills, setEditRequiredSkills] = useState('');
  const [editOptionalSkills, setEditOptionalSkills] = useState('');
  const [editSeniority, setEditSeniority] = useState('');

  const [matchingJobId, setMatchingJobId] = useState<string | null>(null);
  const [matchResults, setMatchResults] = useState<MatchResult[]>([]);
  const [matchLoading, setMatchLoading] = useState(false);
  const [candidates, setCandidates] = useState<Record<string, Candidate>>({});

  const loadJobs = useCallback(async () => {
    try {
      const { data } = await api.get<Job[]>('/jobs');
      setJobs(Array.isArray(data) ? data : []);
    } catch {
      setJobs([]);
    }
  }, []);

  useEffect(() => {
    const refresh = async () => {
      await loadJobs();
    };
    void refresh();
  }, [loadJobs]);

  const createJob = async () => {
    try {
      const { data } = await api.post<Job>('/jobs', { description });
      setJobs([...jobs, data]);
      setShowForm(false);
      setDescription('');
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Job creation failed'));
    }
  };

  const startEdit = (job: Job) => {
    setEditingJob(job);
    setEditTitle(job.title || '');
    setEditDescription(job.description || '');
    setEditRequiredSkills((job.required_skills || []).join(', '));
    setEditOptionalSkills((job.optional_skills || []).join(', '));
    setEditSeniority(job.seniority || '');
  };

  const saveEdit = async () => {
    if (!editingJob) return;

    try {
      const required_skills = editRequiredSkills
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const optional_skills = editOptionalSkills
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      await api.patch(`/jobs/${editingJob.job_id}`, {
        title: editTitle,
        description: editDescription,
        required_skills,
        optional_skills,
        seniority: editSeniority || null,
      });

      setEditingJob(null);
      await loadJobs();
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Update failed'));
    }
  };

  const deleteJob = async (jobId: string) => {
    const ok = window.confirm('Delete this job and related matching data?');
    if (!ok) return;
    try {
      await api.delete(`/jobs/${jobId}`);
      await loadJobs();
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Delete failed'));
    }
  };

  const showMatch = async (jobId: string) => {
    setMatchingJobId(jobId);
    setMatchLoading(true);
    setMatchResults([]);
    try {
      const [matchRes, candRes] = await Promise.all([
        api.post<{ results?: MatchResult[] }>(`/jobs/${jobId}/match`),
        api.get<Candidate[]>('/candidates'),
      ]);
      setMatchResults((matchRes.data.results || []).sort((a, b) => b.score - a.score));
      const map: Record<string, Candidate> = {};
      (Array.isArray(candRes.data) ? candRes.data : []).forEach((c: Candidate) => {
        map[c.candidate_id] = c;
      });
      setCandidates(map);
    } catch {
      setMatchResults([]);
    }
    setMatchLoading(false);
  };

  const closeMatch = () => {
    setMatchingJobId(null);
    setMatchResults([]);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Jobs</h1>
        <button onClick={() => setShowForm(true)} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
          <Plus className="w-4 h-4" /> New Job
        </button>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
          <h2 className="font-semibold mb-3">Create Job Posting</h2>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Paste job description here..."
            className="w-full h-32 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none mb-3" />
          <div className="flex gap-2">
            <button onClick={createJob} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Create</button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded-lg hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      {editingJob && (
        <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
          <h2 className="font-semibold mb-3">Edit Job</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              placeholder="Job title"
              className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
            />
            <input
              value={editSeniority}
              onChange={(e) => setEditSeniority(e.target.value)}
              placeholder="Seniority (junior, mid, senior)"
              className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
            />
          </div>
          <textarea
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
            placeholder="Job description"
            className="w-full h-28 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none mb-3"
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <input
              value={editRequiredSkills}
              onChange={(e) => setEditRequiredSkills(e.target.value)}
              placeholder="Required skills (comma separated)"
              className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
            />
            <input
              value={editOptionalSkills}
              onChange={(e) => setEditOptionalSkills(e.target.value)}
              placeholder="Optional skills (comma separated)"
              className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
            />
          </div>
          <div className="flex gap-2">
            <button onClick={saveEdit} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Save</button>
            <button onClick={() => setEditingJob(null)} className="px-4 py-2 border rounded-lg hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      {matchingJobId && (
        <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Matching Results</h2>
            <button onClick={closeMatch} className="p-1 hover:bg-gray-100 rounded">
              <X className="w-5 h-5 text-gray-500" />
            </button>
          </div>
          {matchLoading ? (
            <p className="text-gray-400 text-center py-4">Matching candidates...</p>
          ) : matchResults.length === 0 ? (
            <p className="text-gray-400 text-center py-4">No matching candidates found.</p>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {matchResults.slice(0, 5).map((r) => {
                const cand = candidates[r.candidate_id];
                const reasoning = r.reasoning || {};
                const isOverqualified = reasoning.overqualified;
                const displayName = cand?.full_name || r.candidate_name || r.candidate_id.slice(0, 8);
                const displaySkills = cand?.skills || r.candidate_skills || [];
                return (
                  <div key={r.candidate_id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{displayName}</span>
                        {isOverqualified && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded text-xs">
                            <AlertTriangle className="w-3 h-3" /> Over
                          </span>
                        )}
                      </div>
                      <div className="flex gap-1 flex-wrap mt-1">
                        {displaySkills.slice(0, 5).map((s: string) => (
                          <span key={s} className="px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded text-xs">{s}</span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-sm font-bold ${r.score >= 0.7 ? 'text-green-600' : r.score >= 0.4 ? 'text-yellow-600' : 'text-red-600'}`}>
                        {(r.score * 100).toFixed(1)}%
                      </div>
                      {reasoning.estimated_years !== undefined && (
                        <div className="text-xs text-gray-400">~{reasoning.estimated_years}y exp</div>
                      )}
                    </div>
                  </div>
                );
              })}
              {matchResults.length > 5 && (
                <p className="text-xs text-gray-400 text-center pt-1">+{matchResults.length - 5} more candidates</p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="space-y-3">
        {jobs.map((job) => (
          <div key={job.job_id} className="bg-white rounded-xl shadow-sm border p-5">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-semibold text-gray-900">{job.title || 'Untitled Job'}</h3>
                <p className="text-sm text-gray-500 mt-1">{job.seniority}</p>
                <div className="flex gap-2 mt-2 flex-wrap">
                  {(job.required_skills || []).slice(0, 8).map((s: string) => (
                    <span key={s} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{s}</span>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => showMatch(job.job_id)}
                  className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-blue-50 text-blue-600 text-sm"
                  title="Match candidates"
                >
                  <GitCompare className="w-4 h-4" /> Match
                </button>
                <button
                  onClick={() => startEdit(job)}
                  className="p-2 border rounded-lg hover:bg-gray-50"
                  title="Edit"
                >
                  <Pencil className="w-4 h-4 text-gray-600" />
                </button>
                <button
                  onClick={() => deleteJob(job.job_id)}
                  className="p-2 border rounded-lg hover:bg-red-50"
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4 text-red-600" />
                </button>
              </div>
            </div>
          </div>
        ))}
        {jobs.length === 0 && <p className="text-gray-400 text-center py-8">No jobs yet. Create your first job posting.</p>}
      </div>
    </div>
  );
}
