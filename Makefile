SHELL := /bin/bash
ROOT := $(CURDIR)
GO := go
GOCACHE := $(ROOT)/go/.gocache
GOPATH := $(ROOT)/go/.gopath
GOENV := GOCACHE=$(GOCACHE) GOPATH=$(GOPATH) GOTOOLCHAIN=local GOPROXY=off CGO_ENABLED=0
LDFLAGS := -s -w
VERSION := 0.2.0

.PHONY: build static test oracle install install-user dist clean

build:
	cd go && $(GOENV) $(GO) build -trimpath -ldflags="$(LDFLAGS)" -o ../bin/pyforai ./cmd/pyforai

static:
	cd go && $(GOENV) GOOS=linux GOARCH=amd64 $(GO) build -trimpath -ldflags="$(LDFLAGS)" -o ../bin/pyforai-linux-amd64 ./cmd/pyforai
	cd go && $(GOENV) GOOS=linux GOARCH=arm64 $(GO) build -trimpath -ldflags="$(LDFLAGS)" -o ../bin/pyforai-linux-arm64 ./cmd/pyforai

test:
	cd go && $(GOENV) $(GO) test ./...

oracle: build
	python3 go/oracle_check.py

install: static
	./install.sh

install-user: static
	PYFORAI_INSTALL_DIR=$(HOME)/.local/bin ./install.sh

dist: static
	mkdir -p dist
	tar -czf dist/pyforai-$(VERSION)-linux.tar.gz install.sh bin/pyforai-linux-amd64 bin/pyforai-linux-arm64

clean:
	rm -rf bin go/.gocache go/.gopath
