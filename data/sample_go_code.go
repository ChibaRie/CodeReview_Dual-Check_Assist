package main

import "fmt"

// BUG: ignored error
func read() {
    f, _ := os.Open("data.txt")
    defer f.Close()
    fmt.Println(f)
}

func main() {
    read()
}
