// Go 静态规则测试 — 错误检查 + defer 泄漏 + 全局变量
// 基于常见 Go 代码审查问题

package main

import (
    "fmt"
    "os"
)

// BUG: 包级可变变量
var globalCounter int = 0

// BUG: 未检查错误返回值
func readFile(path string) string {
    data, err := os.ReadFile(path)
    return string(data)
}

// BUG: defer 在循环中 — 资源泄漏
func processFiles(paths []string) {
    for _, p := range paths {
        f, err := os.Open(p)
        if err != nil {
            continue
        }
        defer f.Close()  // BUG: defer 在循环中不释放
        fmt.Println(f.Name())
    }
}

// OK: 正确检查错误
func safeReadFile(path string) (string, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return "", fmt.Errorf("read failed: %w", err)
    }
    return string(data), nil
}

func main() {
    fmt.Println("Go static check test")
}
