import { useState } from 'react'
import ApiKeyInput, { getStoredApiKey } from '../components/ApiKeyInput'
import { batchReview, type BatchResponse } from '../api'

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return '批量评审失败'
}

export default function BatchPage() {
  const [apiKey, setApiKey] = useState(getStoredApiKey)
  const [directory, setDirectory] = useState('')
  const [lineThreshold, setLineThreshold] = useState(500)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BatchResponse | null>(null)
  const [error, setError] = useState('')

  const handleBatch = async () => {
    if (!directory) {
      setError('请输入目录路径')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await batchReview({
        directory,
        api_key: apiKey,
        line_threshold: lineThreshold,
      })
      setResult(res)
    } catch (err: unknown) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <ApiKeyInput value={apiKey} onChange={setApiKey} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <input
          value={directory}
          onChange={(e) => setDirectory(e.target.value)}
          placeholder="目录绝对路径，例如 D:\\project\\src"
          className="border border-slate-300 rounded px-3 py-2 md:col-span-2"
        />
        <input
          type="number"
          value={lineThreshold}
          onChange={(e) => setLineThreshold(Number(e.target.value))}
          placeholder="舱壁阈值"
          className="border border-slate-300 rounded px-3 py-2"
        />
      </div>
      <button
        onClick={handleBatch}
        disabled={loading}
        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {loading ? '批量评审中...' : '开始批量评审'}
      </button>

      {error && <div className="bg-red-50 text-red-700 p-4 rounded">{error}</div>}

      {result && (
        <div>
          <div className="mb-4 p-4 bg-slate-50 rounded border border-slate-200">
            <p>总文件数：{result.batch_summary.total_files}</p>
            <p>小文件：{result.batch_summary.small_files}</p>
            <p>大文件：{result.batch_summary.large_files}</p>
          </div>
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-300">
                <th className="py-2">文件</th>
                <th className="py-2">行数</th>
                <th className="py-2">Pool</th>
                <th className="py-2">耗时</th>
                <th className="py-2">风险等级</th>
              </tr>
            </thead>
            <tbody>
              {result.files.map((f, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="py-2 font-mono text-sm">{f.file}</td>
                  <td className="py-2">{f.lines}</td>
                  <td className="py-2">{f.pool}</td>
                  <td className="py-2">{f.elapsed_ms.toFixed(0)} ms</td>
                  <td className="py-2">{f.risk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}