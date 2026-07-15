import { NavLink } from 'react-router-dom'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex">
      <nav className="w-64 bg-slate-900 text-white p-6 flex flex-col gap-4">
        <h1 className="text-xl font-bold">DualCheck</h1>
        <NavLink to="/" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>单文件评审</NavLink>
        <NavLink to="/batch" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>批量评审</NavLink>
        <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'text-blue-400' : ''}>仪表盘</NavLink>
      </nav>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  )
}