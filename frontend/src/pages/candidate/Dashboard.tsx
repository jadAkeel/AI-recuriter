import { useAuth } from '../../context/auth';
import { Upload, MessageSquare, BarChart3, User } from 'lucide-react';

export default function CandidateDashboard() {
  const { user } = useAuth();

  const quickActions = [
    { title: 'Upload CV', desc: 'Upload your CV for AI analysis', icon: Upload, href: '/upload-cv' },
    { title: 'Take Interview', desc: 'Complete AI-generated technical interview', icon: MessageSquare, href: '/my-interviews' },
    { title: 'View Results', desc: 'See your evaluation and skill gap analysis', icon: BarChart3, href: '/my-results' },
  ];

  return (
    <div>
      <div className="flex items-center gap-4 mb-8">
        <div className="w-14 h-14 bg-blue-100 rounded-full flex items-center justify-center">
          <User className="w-7 h-7 text-blue-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Welcome, {user?.full_name}</h1>
          <p className="text-gray-500">Candidate Portal — manage your applications</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {quickActions.map((action) => (
          <a key={action.title} href={action.href}
            className="bg-white rounded-xl shadow-sm border p-6 hover:border-blue-300 transition-colors">
            <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center mb-4">
              <action.icon className="w-6 h-6 text-blue-600" />
            </div>
            <h3 className="font-semibold text-gray-900 mb-1">{action.title}</h3>
            <p className="text-sm text-gray-500">{action.desc}</p>
          </a>
        ))}
      </div>
    </div>
  );
}
