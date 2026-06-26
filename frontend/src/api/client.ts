import axios from 'axios';
import type { InternalAxiosRequestConfig } from 'axios';

type RetriableRequestConfig = InternalAxiosRequestConfig & { _retry?: boolean };

const getApiBaseUrl = () => {
  let url = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  if (url.startsWith('http') && !url.endsWith('/api/v1')) {
    url = url.replace(/\/$/, '') + '/api/v1';
  }
  return url;
};
const API_BASE_URL = getApiBaseUrl();
let refreshPromise: Promise<string> | null = null;

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60_000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const originalRequest = error.config as RetriableRequestConfig | undefined;
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        try {
          if (!refreshPromise) {
            refreshPromise = axios
              .post(`${API_BASE_URL}/auth/refresh`, { refresh_token: refreshToken })
              .then(({ data }) => {
                localStorage.setItem('access_token', data.access_token);
                localStorage.setItem('refresh_token', data.refresh_token);
                return data.access_token as string;
              })
              .finally(() => {
                refreshPromise = null;
              });
          }
          const accessToken = await refreshPromise;
          originalRequest.headers.Authorization = `Bearer ${accessToken}`;
          return api(originalRequest);
        } catch {
          localStorage.clear();
          window.location.href = '/login';
        }
      } else {
        localStorage.clear();
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export async function voiceStart(sessionId: string): Promise<{ session_id: string; status: string }> {
  const { data } = await api.post(`/voice/start/${sessionId}`);
  return data;
}

export async function voiceProcess(params: {
  audio: string;
  session_id?: string;
  question_id?: string;
  question_text?: string;
  skill?: string;
  difficulty?: string;
}): Promise<{
  transcript: string;
  score: number;
  feedback: string;
  strengths: string[];
  weaknesses: string[];
  language_detected: string;
  audio?: string;
}> {
  const { data } = await api.post('/voice/process', params);
  return data;
}

export async function voiceProcessUpload(
  file: Blob,
  formFields: Record<string, string> = {},
): Promise<{
  transcript: string;
  score: number;
  feedback: string;
  strengths: string[];
  weaknesses: string[];
  language_detected: string;
  audio?: string;
}> {
  const formData = new FormData();
  formData.append('file', file, 'recording.webm');
  Object.entries(formFields).forEach(([k, v]) => formData.append(k, v));
  const { data } = await api.post('/voice/process/upload', formData);
  return data;
}

export async function voiceStatus(sessionId: string): Promise<{
  session_id: string;
  status: string;
  answers_count: number;
  started_at: number | null;
}> {
  const { data } = await api.get(`/voice/status/${sessionId}`);
  return data;
}

export default api;
