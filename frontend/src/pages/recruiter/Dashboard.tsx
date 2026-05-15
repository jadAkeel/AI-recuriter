import { useState, useEffect } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/auth';
import { Briefcase, Users, GitCompare, BarChart3 } from 'lucide-react';

export default function RecruiterDashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState({ jobs: 0, candidates: 0, matches: 0, reports: 0 });

  useEffect(() => {
    Promise.all([
      api.get('/jobs').catch(() => ({ data: [] })),
      api.get('/candidates').catch(() => ({ data: [] })),
    ]).then(([jobs, candidates]) => {
      setStats({
        jobs: jobs.data.length || 0,
        candidates: candidates.data.length || 0,
        matches: 0,
        reports: 0,
      });
    });
  }, []);

  const cards = [
    { title: 'Jobs', value: stats.jobs, icon: Briefcase, color: 'bg-blue-500' },
    { title: 'Candidates', value: stats.candidates, icon: Users, color: 'bg-green-500' },
    { title: 'Matches', value: stats.matches, icon: GitCompare, color: 'bg-purple-500' },
    { title: 'Reports', value: stats.reports, icon: BarChart3, color: 'bg-orange-500' },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Welcome, {user?.full_name}</h1>
      <p className="text-gray-500 mb-8">Recruiter Dashboard — overview of your hiring pipeline</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map((card) => (
          <div key={card.title} className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">{card.title}</p>
                <p className="text-3xl font-bold text-gray-900 mt-1">{card.value}</p>
              </div>
              <div className={`${card.color} p-3 rounded-lg`}>
                <card.icon className="w-6 h-6 text-white" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
