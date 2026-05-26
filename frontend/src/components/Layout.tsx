import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Sidebar } from './Sidebar';

export function Layout() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <Sidebar />
      <main className="p-4 pt-20 pb-24 md:ml-64 md:p-6 md:pt-20">
        <Outlet />
      </main>
    </div>
  );
}
