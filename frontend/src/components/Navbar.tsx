import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/auth';
import { LogOut, User, Briefcase, LayoutDashboard } from 'lucide-react';

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };
  const primaryHref = user?.role === 'candidate' ? '/jobs' : '/dashboard';
  const primaryLabel = user?.role === 'candidate' ? 'Job Posts' : 'Dashboard';

  return (
    <nav className="bg-white border-b border-gray-200 fixed top-0 left-0 right-0 z-50 h-16">
      <div className="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-xl font-bold text-blue-600">
          <Briefcase className="w-6 h-6" />
          AI Recruiter
        </Link>

        <div className="flex items-center gap-4">
          {user && (
            <>
              <Link to={primaryHref} className="flex items-center gap-1 text-gray-600 hover:text-blue-600 text-sm">
                <LayoutDashboard className="w-4 h-4" />
                {primaryLabel}
              </Link>
              <div className="flex items-center gap-2 text-sm text-gray-600">
                <User className="w-4 h-4" />
                {user.full_name}
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                  {user.role}
                </span>
              </div>
              <button onClick={handleLogout} className="flex items-center gap-1 text-red-500 hover:text-red-700 text-sm">
                <LogOut className="w-4 h-4" />
                Logout
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
