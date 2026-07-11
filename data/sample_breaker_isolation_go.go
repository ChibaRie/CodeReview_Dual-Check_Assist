"""熔断器隔离测试 — Go 样本。

与 Python 样本同时存在，验证 Go 熔断器独立于 Python 熔断器。
Python 熔断器 OPEN 不影响 Go 的 AI 评审路径。
*/

package main

import "fmt"

// TODO: add proper error handling
func processData(input []int) []int {
	result := make([]int, 0)
	for _, v := range input {
		if v > 0 {
			result = append(result, v*2)
		}
	}
	return result
}

// FIXME: this function is too long and needs refactoring — this is a very long comment line to trigger the long line detector in the static checker
func main() {
	fmt.Println("breaker isolation test")
}
