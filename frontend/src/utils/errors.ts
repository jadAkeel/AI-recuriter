import { isAxiosError } from 'axios';

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function getApiStatus(error: unknown): number | undefined {
  return isAxiosError(error) ? error.response?.status : undefined;
}
