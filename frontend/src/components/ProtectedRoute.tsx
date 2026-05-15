import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/auth';

type ProtectedRouteProps = {
  children: React.ReactNode;
  role?: string;
  roles?: string[];
};

export function ProtectedRoute({ children, role, roles }: ProtectedRouteProps) {
  const { user, loading } = useAuth();
  const allowedRoles = roles ?? (role ? [role] : undefined);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-200 border-b-blue-600" />
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  if (allowedRoles && !allowedRoles.includes(user.role)) return <Navigate to="/" replace />;

  return <>{children}</>;
}
