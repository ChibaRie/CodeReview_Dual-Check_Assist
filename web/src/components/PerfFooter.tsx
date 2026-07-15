export default function PerfFooter({ perf }: { perf: Record<string, unknown> }) {
  if (!perf) return null
  return (
    <div className="mt-6 p-4 bg-slate-50 rounded text-sm text-slate-600 border border-slate-200">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <span className="block text-xs text-slate-400">耗时</span>
          {typeof perf.elapsed_ms === 'number' ? perf.elapsed_ms.toFixed(0) : '-'} ms
        </div>
        <div>
          <span className="block text-xs text-slate-400">缓存</span>
          {perf.cache_hit ? '命中' : '未命中'}
        </div>
        <div>
          <span className="block text-xs text-slate-400">AI 链路</span>
          {typeof perf.ai_tier === 'string' ? perf.ai_tier : 'none'}
        </div>
        <div>
          <span className="block text-xs text-slate-400">熔断器</span>
          {typeof perf.breaker_state === 'string' ? perf.breaker_state : 'CLOSED'}
        </div>
      </div>
    </div>
  )
}