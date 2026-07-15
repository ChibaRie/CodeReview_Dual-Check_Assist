const colors: Record<string, string> = {
  high: 'bg-red-100 text-red-800 border-red-200',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  low: 'bg-blue-100 text-blue-800 border-blue-200',
}

export default function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-xs font-medium px-2 py-1 rounded border ${colors[severity] || colors.low}`}>
      {severity}
    </span>
  )
}