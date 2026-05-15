import { useState, useEffect, useRef } from 'react';
import api from '../../api/client';
import { Upload, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import type { CandidateUploadResult } from '../../types/api';
import { getApiErrorMessage } from '../../utils/errors';
import { buildApiWebSocketUrl } from '../../utils/network';

export default function UploadCV() {
  const [result, setResult] = useState<CandidateUploadResult | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<'idle' | 'uploading' | 'queued' | 'processing' | 'done' | 'error'>('idle');
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const startPolling = (taskId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    setStatus('processing');
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get(`/candidates/async/${taskId}`);
        if (data.status === 'completed' || data.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          if (data.status === 'completed') {
            setResult(data);
            setStatus('done');
          } else {
            setError(data.error || 'Processing failed');
            setStatus('error');
          }
        }
      } catch {
        // Poll again on transient errors.
      }
    }, 2000);
  };

  const waitForResult = (taskId: string) => {
    startPolling(taskId);
    let finished = false;
    const ws = new WebSocket(buildApiWebSocketUrl('/ws/cv-notifications'));
    wsRef.current = ws;

    ws.onopen = () => setStatus('queued');

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'ping') return;
      if (data.type === 'error') {
        startPolling(taskId);
        return;
      }
      if (data.task_id === taskId && (data.status === 'completed' || data.status === 'failed')) {
        finished = true;
        ws.close();
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        if (data.status === 'completed') {
          setResult(data);
          setStatus('done');
        } else {
          setError(data.error || 'Processing failed');
          setStatus('error');
        }
      }
    };

    ws.onerror = () => {
      startPolling(taskId);
    };

    ws.onclose = () => {
      if (!finished) startPolling(taskId);
    };
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError('');
    setStatus('uploading');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const { data } = await api.post('/candidates/async', formData);
      setStatus('queued');
      waitForResult(data.task_id);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Upload failed'));
      setStatus('error');
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Upload Your CV</h1>

      {status === 'idle' && (
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <Upload className="w-16 h-16 mx-auto mb-4 text-blue-500" />
          <p className="text-gray-600 mb-4">Upload your CV in PDF, DOCX, or TXT format</p>
          <label className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer">
            Choose File
            <input type="file" accept=".pdf,.docx,.doc,.txt" onChange={handleUpload} className="hidden" />
          </label>
        </div>
      )}

      {status === 'uploading' && (
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <Upload className="w-16 h-16 mx-auto mb-4 text-blue-500 animate-pulse" />
          <p className="text-gray-600">Uploading...</p>
        </div>
      )}

      {status === 'queued' && (
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <Clock className="w-16 h-16 mx-auto mb-4 text-yellow-500 animate-spin" />
          <p className="text-gray-600">CV queued for processing...</p>
        </div>
      )}

      {status === 'processing' && (
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <Clock className="w-16 h-16 mx-auto mb-4 text-yellow-500 animate-spin" />
          <p className="text-gray-600">Processing CV...</p>
        </div>
      )}

      {(status === 'done') && result && (
        <div className="bg-white rounded-xl shadow-sm border p-6">
          <div className="flex items-center gap-3 text-green-600 mb-6">
            <CheckCircle className="w-6 h-6" />
            <span className="font-semibold">CV Processed Successfully</span>
          </div>
          <div className="space-y-4">
            <div>
              <p className="text-sm text-gray-500">Name</p>
              <p className="font-medium">{result.full_name}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Email</p>
              <p className="font-medium">{result.email}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Skills</p>
              <div className="flex gap-2 flex-wrap mt-1">
                {result.skills?.map((s: string) => <span key={s} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{s}</span>)}
              </div>
            </div>
          </div>
          <button onClick={() => { setResult(null); setStatus('idle'); }} className="mt-6 text-sm text-blue-600 hover:underline">
            Upload another CV
          </button>
        </div>
      )}

      {status === 'error' && (
        <div className="bg-white rounded-xl shadow-sm border p-8 text-center">
          <AlertCircle className="w-16 h-16 mx-auto mb-4 text-red-500" />
          <p className="text-red-600 mb-4">{error || 'Upload failed'}</p>
          <button onClick={() => { setError(''); setStatus('idle'); }} className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}
