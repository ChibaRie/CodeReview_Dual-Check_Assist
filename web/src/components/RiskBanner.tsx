const styles: Record<string, string> = {
  '阻止合并': 'bg-red-600 text-white',
  '修复后合并': 'bg-yellow-500 text-white',
  '可合并': 'bg-green-600 text-white',
}

export default function RiskBanner({ risk }: { risk: string }) {
  return (
    <div className={`rounded p-4 text-lg font-bold mb-4 ${styles[risk] || 'bg-slate-500 text-white'}`}>
      风险等级：{risk}
    </div>
  )
}