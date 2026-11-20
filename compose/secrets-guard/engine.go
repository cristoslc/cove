package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sync"
	"sync/atomic"

	"github.com/spf13/viper"
	"github.com/zricethezav/gitleaks/v8/config"
	"github.com/zricethezav/gitleaks/v8/detect"
	"github.com/zricethezav/gitleaks/v8/report"
)

// Hit is one rule match, reduced to what may leave the process.
//
// It deliberately carries no matched text: the rule id, a short fingerprint of
// the secret, and the byte offset of the rule's match inside the body. The
// fingerprint is stable (same secret, same value) so repeats can be counted
// without the value ever being stored or logged.
type Hit struct {
	RuleID      string `json:"rule"`
	Fingerprint string `json:"fingerprint,omitempty"`
	Offset      int    `json:"offset"`
}

// Engine is a rule set loaded once and reused for every scan.
//
// Loading means: parse the TOML, merge the extended default rules, compile
// every rule regex. Measured at ~0.37 ms on an M3 Pro, and 246 ms when each
// scan paid for a fresh `gitleaks` process instead — which is exactly the
// placement argument in docs/musings/2026-11-19-edge-secrets-check-spike.md.
type Engine struct {
	cfg   config.Config
	path  string
	loads atomic.Int64
	scans atomic.Int64
}

// loaded is the process-wide engine. gitleaks' Translate() keeps an
// unexported, never-reset extend-depth counter in package state, so a second
// load in the same process silently skips `[extend] useDefault` and comes back
// with the repo's two rules but none of the default ones. One load per process
// is therefore a hard constraint, enforced here rather than discovered later as
// a detection gap.
var (
	loadedMu     sync.Mutex
	loadedEngine *Engine
)

// LoadEngine reads a gitleaks config file — the same `.gitleaks.toml` the
// commit-hook gate uses — and holds the compiled rule set.
//
// Calling it again with the already-loaded path returns that engine. Calling it
// with a different path fails loudly: the library cannot extend its defaults
// twice in one process, and returning a partially-loaded rule set would look
// like a clean scan.
func LoadEngine(path string) (*Engine, error) {
	loadedMu.Lock()
	defer loadedMu.Unlock()
	if loadedEngine != nil {
		if loadedEngine.path == path {
			return loadedEngine, nil
		}
		return nil, fmt.Errorf(
			"cannot load %q: %q is already loaded and gitleaks' config loader cannot extend its defaults twice in one process",
			path, loadedEngine.path,
		)
	}

	// A private viper keeps the config-file read isolated; gitleaks'
	// Translate() reaches into the package-global viper for extends.
	v := viper.New()
	v.SetConfigType("toml")
	v.SetConfigFile(path)
	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("read gitleaks rules %s: %w", path, err)
	}
	var vc config.ViperConfig
	if err := v.Unmarshal(&vc); err != nil {
		return nil, fmt.Errorf("parse gitleaks rules %s: %w", path, err)
	}
	cfg, err := vc.Translate()
	if err != nil {
		return nil, fmt.Errorf("compile gitleaks rules %s: %w", path, err)
	}
	engine := &Engine{cfg: cfg, path: path}
	engine.loads.Add(1)
	loadedEngine = engine
	return engine, nil
}

// RuleCount is the number of compiled rules, default set plus the repo's own.
func (e *Engine) RuleCount() int { return len(e.cfg.Rules) }

// RuleIDs is the compiled rule ids, for the startup line. Never secret.
func (e *Engine) RuleIDs() []string {
	ids := make([]string, 0, len(e.cfg.Rules))
	for _, rule := range e.cfg.GetOrderedRules() {
		ids = append(ids, rule.RuleID)
	}
	return ids
}

// Loads is how many times the rule set was read from disk. It must stay 1 for
// the life of the process; a test pins that.
func (e *Engine) Loads() int64 { return e.loads.Load() }

// Scans is how many bodies this engine has scanned.
func (e *Engine) Scans() int64 { return e.scans.Load() }

// Scan reports the hits in body, observing only: it mutates nothing and keeps
// no finding after it returns.
//
// Each call builds a fresh Detector over the shared, already-compiled config.
// That is deliberate: gitleaks' Detector appends every finding it ever produced
// to an internal slice, and a Finding holds the matched text, so reusing one
// Detector in a long-lived process would retain real credentials in memory for
// the process lifetime. The config (parser + compiled regexes) stays loaded;
// the per-scan Detector only builds the keyword prefilter trie (~27 µs).
func (e *Engine) Scan(body []byte) []Hit {
	e.scans.Add(1)
	detector := detect.NewDetector(e.cfg)
	findings := detector.DetectBytes(body)
	hits := make([]Hit, 0, len(findings))
	for _, finding := range findings {
		hits = append(hits, Hit{
			RuleID:      finding.RuleID,
			Fingerprint: fingerprint(finding.Secret),
			Offset:      matchOffset(body, finding),
		})
	}
	return hits
}

// fingerprint is the first 12 hex characters of SHA-256 over the matched
// secret. It identifies a value across requests without carrying it.
func fingerprint(secret string) string {
	if secret == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(sum[:])[:12]
}

// matchOffset converts a finding's line/column into a byte offset in body.
//
// gitleaks reports the *match* start, which for a secretGroup rule is the
// keyword, not the captured secret. Its column is measured from the previous
// newline with a +1 base, so the byte arithmetic differs by one on the first
// line (where the previous newline is the virtual index 0). Verified against
// multi-line bodies in engine_test.go.
func matchOffset(body []byte, finding report.Finding) int {
	if finding.StartLine < 0 || finding.StartColumn < 1 {
		return -1
	}
	lineStart := 0
	for line := 0; line < finding.StartLine; line++ {
		next := bytes.IndexByte(body[lineStart:], '\n')
		if next < 0 {
			return -1
		}
		lineStart += next + 1
	}
	var offset int
	if finding.StartLine == 0 {
		offset = finding.StartColumn - 1
	} else {
		offset = lineStart + finding.StartColumn - 2
	}
	if offset < 0 || offset > len(body) {
		return -1
	}
	return offset
}
