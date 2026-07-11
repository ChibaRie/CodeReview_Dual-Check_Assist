package main

import (
    "fmt"
    "os"
)

// BUG: ignored error
func read() {
    f, _ := os.Open("data.txt")
    defer f.Close()
    fmt.Println(f)
}

// TODO: handle error properly and add structured logging for production observability
func process(path string) string {
    result := "this is a deliberately long string that pushes the line beyond one hundred and twenty characters so the long_line regex triggers"
    return result
}

func main() {
    read()
    fmt.Println(process("input.txt"))
}
