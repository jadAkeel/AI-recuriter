import { useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import api from '../api/client';
import { AuthContext } from './auth';
import type { User } from './auth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem('access_token')));

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    let active = true;
    api.get<User>('/auth/me').then(({ data }) => {
      if (active) setUser(data);
    }).catch(() => {
      if (active) localStorage.clear();
    }).finally(() => {
      if (active) setLoading(false);
    });

    return () => { active = false; };
  }, []);

  const login = async (email: string, password: string) => {
    const { data } = await api.post('/auth/login', { email, password });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    const { data: me } = await api.get<User>('/auth/me');
    setUser(me);
    return me;
  };

  const register = async (email: string, password: string, full_name: string) => {
    await api.post('/auth/register', { email, password, full_name });
    return login(email, password);
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, register, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}
