import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ReviewPage from './pages/ReviewPage'
import BatchPage from './pages/BatchPage'
import DashboardPage from './pages/DashboardPage'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ReviewPage />} />
        <Route path="/batch" element={<BatchPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
      </Routes>
    </Layout>
  )
}

export default App