import Editor from '@monaco-editor/react'

interface CodeEditorProps {
  value: string
  onChange: (v: string) => void
  language: string
}

export default function CodeEditor({ value, onChange, language }: CodeEditorProps) {
  return (
    <Editor
      height="400px"
      language={language}
      value={value}
      onChange={(v) => onChange(v || '')}
      theme="vs-light"
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
        automaticLayout: true,
      }}
    />
  )
}