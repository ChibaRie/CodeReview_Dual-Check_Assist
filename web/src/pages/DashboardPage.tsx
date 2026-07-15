import { useEffect, useState } from 'react'
import { health, breakerStatus, resetBreaker, vectorStats, trendReport } from '../api'

export default function DashboardPage() {
  const [healthData, setHealthData] = useState<Record<string, any> | null>(null)
  const [breakerData, setBreakerData] = useState<Record<string, any> | null>(null)
  const [vectorData, setVectorData] = useState<Record<string, any> | null>(null)
  const [trendData, setTrendData] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setError('')
      const [h, b, v, t] = await Promise.all([
        health(),
        breakerStatus(),
        vectorStats(),
        trendReport(),
      ])
      setHealthData(h)
      setBreakerData(b)
      setVectorData(v)
      setTrendData(t)
    } catch (err: any) {
      setError(err.message || '加载仪表盘失败')
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleReset = async (lang: string) => {
    await resetBreaker(lang)
    await load()
  }

  return (
    <div className="space-y-6">
      {error && <div className="bg-red-50 text-red-700 p-4 rounded">{error}</div>}

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">健康度</h2>
        {healthData && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-400">整体</span>
              <p className="font-medium">{healthData.health?.overall}</p>
            </div>
            <div>
              <span className="text-slate-400">缓存</span>
              <p className="font-medium">{healthData.health?.cache}</p>
            </div>
            <div>
              <span className="text-slate-400">规则</span>
              <p className="font-medium">{healthData.health?.rules}</p>
            </div>
            <div>
              <span className="text-slate-400">熔断器</span>
              <p className="font-medium">{healthData.health?.breaker}</p>
            </div>
          </div>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">熔断器状态</h2>
        {breakerData && Object.keys(breakerData).length > 0 ? (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-300">
                <th className="py-2">语言</th>
                <th className="py-2">状态</th>
                <th className="py-2">失败次数</th>
                <th className="py-2">阈值</th>
                <th className="py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(breakerData).map(([lang, s]: [string, any]) => (
                <tr key={lang} className="border-b border-slate-100">
                  <td className="py-2">{lang}</td>
                  <td className="py-2">{s.state}</td>
                  <td className="py-2">{s.failures}</td>
                  <td className="py-2">{s.threshold}</td>
                  <td className="py-2">
                    <button
                      onClick={() => handleReset(lang)}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      重置
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-slate-500">暂无熔断器记录</p>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">向量记忆</h2>
        {vectorData && (
          <div className="text-sm">
            <p>总模式数：{vectorData.total_patterns}</p>
            {vectorData.top_kinds && (
              <div className="mt-2">
                <span className="text-slate-500">Top Bug 类型：</span>
                <ul className="list-disc list-inside">
                  {vectorData.top_kinds.map((k: any) => (
                    <li key={k.kind}>{k.kind}: {k.count}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="p-4 border border-slate-200 rounded">
        <h2 className="font-bold text-lg mb-3">趋势报告</h2>
        {trendData && (
          <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">
            {JSON.stringify(trendData, null, 2)}
          </pre>
        )}
      </section>
    </div>
  )
}