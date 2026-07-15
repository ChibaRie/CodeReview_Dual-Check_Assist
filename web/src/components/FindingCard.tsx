import SeverityBadge from './SeverityBadge'
import type { Finding } from '../api'

export default function FindingCard({ finding }: { finding: Finding }) {
  return (
    <div className="border border-slate-200 rounded p-4 mb-3 bg-white shadow-sm">
      <div className="flex items-center gap-3 mb-2">
        <span className="text-sm font-mono text-slate-500">行 {finding.line}</span>
        <span className="text-xs font-medium px-2 py-1 rounded bg-slate-100 text-slate-700">
          {finding.layer}:{finding.kind}
        </span>
        <SeverityBadge severity={finding.severity} />
      </div>
      <p className="text-slate-800">{finding.message}</p>
    </div>
  )
}