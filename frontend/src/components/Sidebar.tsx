import { NavLink } from 'react-router-dom';
import { useAuth } from '../context/auth';
import { LayoutDashboard, FileText, Users, GitCompare, MessageSquare, BarChart3, Upload, UploadCloud } from 'lucide-react';

export function Sidebar() {
  const { user } = useAuth();

  const recruiterLinks = [
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/jobs', label: 'Jobs', icon: FileText },
    { to: '/candidates', label: 'Candidates', icon: Users },
    { to: '/bulk-upload', label: 'Bulk Upload', icon: UploadCloud },
    { to: '/matching', label: 'Matching', icon: GitCompare },
    { to: '/interviews', label: 'Interviews', icon: MessageSquare },
    { to: '/reports', label: 'Reports', icon: BarChart3 },
  ];

  const candidateLinks = [
    { to: '/jobs', label: 'Job Posts', icon: FileText },
    { to: '/upload-cv', label: 'Upload CV', icon: Upload },
    { to: '/my-interviews', label: 'My Interviews', icon: MessageSquare },
    { to: '/my-results', label: 'My Results', icon: BarChart3 },
  ];

  const links = user?.role === 'candidate' ? candidateLinks : recruiterLinks;

  return (
    <aside className="fixed left-0 top-16 bottom-0 w-64 bg-white border-r border-gray-200 p-4 overflow-y-auto hidden md:block">
      <nav className="space-y-1">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-50'
              }`
            }
          >
            <link.icon className="w-4 h-4" />
            {link.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
