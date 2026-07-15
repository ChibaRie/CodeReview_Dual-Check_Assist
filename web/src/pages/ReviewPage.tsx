import { useState, useEffect } from 'react'
import ApiKeyInput, { getStoredApiKey } from '../components/ApiKeyInput'
import CodeEditor from '../components/CodeEditor'
import RiskBanner from '../components/RiskBanner'
import FindingCard from '../components/FindingCard'
import PerfFooter from '../components/PerfFooter'
import { review, type ReviewResponse } from '../api'

const SAMPLE_CODE = `def divide(a, b):
    return a / b
`

export default function ReviewPage() {
  const [apiKey, setApiKey] = useState(getStoredApiKey)
  const [lang, setLang] = useState('python')
  const [framework, setFramework] = useState('')
  const [code, setCode] = useState(SAMPLE_CODE)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReviewResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setApiKey(getStoredApiKey)
  }, [])

  const handleReview = async (useCache: boolean) => {
    setLoading(true)
    setError('')
    try {
      const res = await review({
        code,
        lang,
        framework,
        api_key: apiKey,
        use_cache: useCache,
      })
      setResult(res)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '评审失败'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <ApiKeyInput value={apiKey} onChange={setApiKey} />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">语言</label>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="w-full border border-slate-300 rounded px-3 py-2"
            >
              <option value="python">Python</option>
              <option value="java">Java</option>
              <option value="go">Go</option>
              <option value="javascript">JavaScript</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">框架</label>
            <input
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              placeholder="例如 Django, Spring"
              className="w-full border border-slate-300 rounded px-3 py-2"
            />
          </div>
        </div>
        <CodeEditor value={code} onChange={setCode} language={lang} />
        <div className="flex gap-3">
          <button
            onClick={() => handleReview(true)}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
          >
            {loading ? '评审中...' : '评审'}
          </button>
          <button
            onClick={() => handleReview(false)}
            disabled={loading}
            className="bg-slate-200 hover:bg-slate-300 text-slate-800 px-4 py-2 rounded disabled:opacity-50"
          >
            强制刷新
          </button>
        </div>
      </div>

      <div>
        {error && <div className="bg-red-50 text-red-700 p-4 rounded mb-4">{error}</div>}
        {result && (
          <>
            <RiskBanner risk={result.risk} />
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">摘要</h3>
              <p className="text-slate-700">{result.summary}</p>
            </div>
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">静态层</h3>
              <p className="text-slate-700">{result.static_summary}</p>
            </div>
            <div className="mb-4">
              <h3 className="font-bold text-slate-800">AI 层</h3>
              <p className="text-slate-700">{result.ai_summary}</p>
            </div>
            <div>
              <h3 className="font-bold text-slate-800 mb-2">
                明细（{result.findings.length} 条）
              </h3>
              {result.findings.map((f, idx) => (
                <FindingCard key={idx} finding={f} />
              ))}
            </div>
            <PerfFooter perf={result._perf} />
          </>
        )}
      </div>
    </div>
  )
}