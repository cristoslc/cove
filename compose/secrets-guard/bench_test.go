package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Benchmarks for the placement argument. Run:
//
//	go test -bench . -benchtime 500x ./...
//
// The numbers that matter are the warm scan cost (well under a millisecond for
// a prompt-sized body) against a fresh `gitleaks` process per scan (median
// 246 ms, measured in docs/musings/2026-11-19-edge-secrets-check-spike.md).

func BenchmarkScanPromptSized(b *testing.B) {
	engine := loadBenchEngine(b)
	body, err := os.ReadFile(filepath.Join(corpusDir, "pos-forgejo-40hex.txt"))
	if err != nil {
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		engine.Scan(body)
	}
}

func BenchmarkScan100KB(b *testing.B) {
	engine := loadBenchEngine(b)
	var builder strings.Builder
	for builder.Len() < 100_000 {
		builder.WriteString("a long prompt body with no credential shape in it. ")
	}
	body := []byte(builder.String())
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		engine.Scan(body)
	}
}

func loadBenchEngine(b *testing.B) *Engine {
	b.Helper()
	engine, err := LoadEngine(rulesPath)
	if err != nil {
		b.Fatalf("LoadEngine: %v", err)
	}
	return engine
}
