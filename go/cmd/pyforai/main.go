package main

import (
	"os"

	"pyforai"
)

func main() {
	os.Exit(pyforai.Run(os.Args[1:]))
}
