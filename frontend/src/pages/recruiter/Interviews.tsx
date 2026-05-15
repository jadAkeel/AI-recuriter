import { useEffect, useState } from 'react';
import api from '../../api/client';
import { AlertTriangle, Check, Copy, ExternalLink, Loader2, Mail, MessageSquare } from 'lucide-react';
import { getApiErrorMessage } from '../../utils/errors';

interface InviteResponse {
  session_id: string;
  candidate_name?: string | null;
  job_title?: string | null;
  email_sent: boolean;
  email_to?: string | null;
  interview_link?: string;
  status: string;
}

export default function RecruiterInterviews() {
  const [jobId, setJobId] = useState('');
  const [candidateId, setCandidateId] = useState('');
  const [jobs, setJobs] = useState<{ job_id: string; title: string }[]>([]);
  const [candidates, setCandidates] = useState<{ candidate_id: string; full_name: string | null; email?: string | null }[]>([]);
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [sending, setSending] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const [jobsRes, candsRes] = await Promise.all([
          api.get('/jobs'),
          api.get('/candidates'),
        ]);
        setJobs(Array.isArray(jobsRes.data) ? jobsRes.data : []);
        setCandidates(Array.isArray(candsRes.data) ? candsRes.data : []);
      } catch (err: unknown) {
        setError(getApiErrorMessage(err, 'Failed to load interview data'));
      }
    };
    fetchOptions();
  }, []);

  const selectedCandidate = candidates.find((candidate) => candidate.candidate_id === candidateId);
  const inviteLink = invite?.interview_link || (invite ? `${window.location.origin}/interview/${invite.session_id}` : '');

  const sendInvite = async () => {
    if (!jobId || !candidateId) return;
    setSending(true);
    setError('');
    setInvite(null);
    try {
      const { data } = await api.post<InviteResponse>('/interviews/invite', {
        job_id: jobId,
        candidate_id: candidateId,
      });
      setInvite(data);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Failed to create interview invitation'));
    } finally {
      setSending(false);
    }
  };

  const copyLink = async () => {
    if (!inviteLink) return;
    await navigator.clipboard.writeText(inviteLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Interview Studio</h1>
      </div>

      <div className="bg-white rounded-xl shadow-sm border p-6 mb-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
            <MessageSquare className="w-5 h-5" />
          </div>
          <div>
            <h2 className="font-semibold text-gray-900">Candidate Interview Invite</h2>
            <p className="text-sm text-gray-500">{selectedCandidate?.email || selectedCandidate?.full_name || 'Select a candidate'}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          <select
            value={jobId}
            onChange={(event) => setJobId(event.target.value)}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          >
            <option value="">-- Select Job --</option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>{job.title}</option>
            ))}
          </select>
          <select
            value={candidateId}
            onChange={(event) => setCandidateId(event.target.value)}
            className="px-3 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          >
            <option value="">-- Select Candidate --</option>
            {candidates.map((candidate) => (
              <option key={candidate.candidate_id} value={candidate.candidate_id}>
                {candidate.full_name || candidate.email || candidate.candidate_id}
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={sendInvite}
          disabled={sending || !jobId || !candidateId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
          {sending ? 'Sending...' : 'Create & Email Invitation'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 mt-0.5" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {invite && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center gap-3 mb-5">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${invite.email_sent ? 'bg-green-50 text-green-600' : 'bg-yellow-50 text-yellow-600'}`}>
              {invite.email_sent ? <Check className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">{invite.email_sent ? 'Invitation Sent' : 'Invitation Created'}</h2>
              <p className="text-sm text-gray-500">{invite.email_to || 'No candidate email available'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
            <div>
              <p className="text-sm text-gray-500">Candidate</p>
              <p className="font-medium text-gray-900">{invite.candidate_name || 'Candidate'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Job</p>
              <p className="font-medium text-gray-900">{invite.job_title || 'Position'}</p>
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-2">
            <button
              onClick={copyLink}
              className="flex items-center justify-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm text-gray-700"
            >
              {copied ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
              {copied ? 'Copied' : 'Copy Interview Link'}
            </button>
            <a
              href={inviteLink}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm text-gray-700"
            >
              <ExternalLink className="w-4 h-4" />
              Open Link
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
