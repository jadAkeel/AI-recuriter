import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/auth';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import RecruiterDashboard from './pages/recruiter/Dashboard';
import Jobs from './pages/recruiter/Jobs';
import BulkUpload from './pages/recruiter/BulkUpload';
import Candidates from './pages/recruiter/Candidates';
import Matching from './pages/recruiter/Matching';
import MatchResults from './pages/recruiter/MatchResults';
import RecruiterInterviews from './pages/recruiter/Interviews';
import Reports from './pages/recruiter/Reports';
import UploadCV from './pages/candidate/UploadCV';
import CandidateInterview from './pages/candidate/Interview';
import CandidateResults from './pages/candidate/Results';
import PublicInterview from './pages/PublicInterview';
import LiveInterview from './pages/LiveInterview';
import VideoInterview from './pages/VideoInterview';

const staffRoles = ['owner', 'admin', 'recruiter'];

function HomeRedirect() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === 'candidate') return <Navigate to="/jobs" replace />;
  return <Navigate to="/dashboard" replace />;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<HomeRedirect />} />

          <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route path="/dashboard" element={
              <ProtectedRoute roles={staffRoles}><RecruiterDashboard /></ProtectedRoute>
            } />
            <Route path="/jobs" element={<ProtectedRoute><Jobs /></ProtectedRoute>} />
            <Route path="/candidates" element={
              <ProtectedRoute roles={staffRoles}><Candidates /></ProtectedRoute>
            } />
            <Route path="/bulk-upload" element={
              <ProtectedRoute roles={staffRoles}><BulkUpload /></ProtectedRoute>
            } />
            <Route path="/matching" element={
              <ProtectedRoute roles={staffRoles}><Matching /></ProtectedRoute>
            } />
            <Route path="/match-results" element={
              <ProtectedRoute roles={staffRoles}><MatchResults /></ProtectedRoute>
            } />
            <Route path="/interviews" element={
              <ProtectedRoute roles={staffRoles}><RecruiterInterviews /></ProtectedRoute>
            } />
            <Route path="/reports" element={
              <ProtectedRoute roles={staffRoles}><Reports /></ProtectedRoute>
            } />
            <Route path="/upload-cv" element={<ProtectedRoute><UploadCV /></ProtectedRoute>} />
            <Route path="/my-interviews" element={<ProtectedRoute><CandidateInterview /></ProtectedRoute>} />
            <Route path="/my-results" element={<ProtectedRoute><CandidateResults /></ProtectedRoute>} />
          </Route>
          <Route path="/interview/:session_id" element={<PublicInterview />} />
          <Route path="/interview/live/:session_id" element={<LiveInterview />} />
          <Route path="/interview/video/:session_id" element={<VideoInterview />} />
          <Route path="*" element={<HomeRedirect />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
