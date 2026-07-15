const STORAGE_KEY = 'dualcheck_api_key'

export function getStoredApiKey(): string {
  return localStorage.getItem(STORAGE_KEY) || ''
}

export function setStoredApiKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key)
}

export default function ApiKeyInput({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-slate-700 mb-1">DeepSeek API Key</label>
      <input
        type="password"
        value={value}
        onChange={(e) => {
          const v = e.target.value
          onChange(v)
          setStoredApiKey(v)
        }}
        placeholder="sk-..."
        className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
      />
      <p className="text-xs text-slate-500 mt-1">仅在本地内存和浏览器 localStorage 保存，不会上传到服务器。</p>
    </div>
  )
}