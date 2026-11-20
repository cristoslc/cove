package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/rs/zerolog"
	"github.com/zricethezav/gitleaks/v8/logging"
)

// The fixtures are the spike's own corpus: twelve files in real secret shapes
// with fake values, six positive and six negative. Reusing them is the point —
// the edge check and the spike must agree about what fires.
const corpusDir = "../../scripts/spikes/edge-secrets/corpus"

// rulesPath is the SAME file the commit-hook gate reads.
const rulesPath = "../../.gitleaks.toml"

func TestMain(m *testing.M) {
	// Keep gitleaks' library logger out of the test output; it can carry the
	// matched text at trace level.
	logging.Logger = zerolog.Nop()
	os.Exit(m.Run())
}

func loadTestEngine(t *testing.T) *Engine {
	t.Helper()
	engine, err := LoadEngine(rulesPath)
	if err != nil {
		t.Fatalf("LoadEngine(%s): %v", rulesPath, err)
	}
	return engine
}

// corpusValue pulls a value out of an allowlisted fixture so the tests never
// carry a secret-shaped literal of their own: the repository's gitleaks gate
// would flag such a literal, and one fixture source is enough.
func corpusValue(t *testing.T, name, pattern string) string {
	t.Helper()
	body, err := os.ReadFile(filepath.Join(corpusDir, name))
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	match := regexp.MustCompile(pattern).FindString(string(body))
	if match == "" {
		t.Fatalf("%s does not contain %s", name, pattern)
	}
	return match
}

func fixtures(t *testing.T, prefix string) []string {
	t.Helper()
	matches, err := filepath.Glob(filepath.Join(corpusDir, prefix+"-*.txt"))
	if err != nil {
		t.Fatalf("glob corpus: %v", err)
	}
	if len(matches) != 6 {
		t.Fatalf("expected 6 %s fixtures, found %d: %v", prefix, len(matches), matches)
	}
	return matches
}

func TestEveryPositiveFixtureFires(t *testing.T) {
	engine := loadTestEngine(t)
	for _, path := range fixtures(t, "pos") {
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		hits := engine.Scan(body)
		if len(hits) == 0 {
			t.Errorf("%s: no hit; the shape must fire", filepath.Base(path))
			continue
		}
		for _, hit := range hits {
			if hit.RuleID == "" {
				t.Errorf("%s: hit with no rule id", filepath.Base(path))
			}
			if hit.Offset < 0 || hit.Offset > len(body) {
				t.Errorf("%s: offset %d outside a %d-byte body", filepath.Base(path), hit.Offset, len(body))
			}
			if hit.Fingerprint == "" {
				t.Errorf("%s: hit with no fingerprint", filepath.Base(path))
			}
		}
	}
}

func TestEveryNegativeFixtureIsSilent(t *testing.T) {
	engine := loadTestEngine(t)
	for _, path := range fixtures(t, "neg") {
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		if hits := engine.Scan(body); len(hits) != 0 {
			t.Errorf("%s: %d hit(s) on an ordinary prompt: %+v", filepath.Base(path), len(hits), hits)
		}
	}
}

// The two rules the spike found missing must come from the shipped ruleset, not
// from a second config file. This pins the ids the commit hook and the edge
// check share.
func TestShippedRulesetCarriesTheTwoPromotedRules(t *testing.T) {
	engine := loadTestEngine(t)
	have := map[string]bool{}
	for _, id := range engine.RuleIDs() {
		have[id] = true
	}
	for _, want := range []string{"forgejo-token-context", "openai-project-key"} {
		if !have[want] {
			t.Errorf("compiled rule set is missing %q", want)
		}
	}
}

// A 40-hex commit SHA in prose must stay silent while the same shape near a
// credential keyword fires: that is the whole reason the token rule is
// context-aware.
func TestTokenRuleIsContextAware(t *testing.T) {
	engine := loadTestEngine(t)
	// The 40-hex value comes from the allowlisted fixture corpus, so no
	// secret-shaped literal is duplicated into this file.
	sha := corpusValue(t, "pos-forgejo-40hex.txt", `\b[0-9a-f]{40}\b`)
	silent := []byte("The commit " + sha + " fixed the probe; see the diff.\n")
	if hits := engine.Scan(silent); len(hits) != 0 {
		t.Fatalf("commit SHA fired: %+v", hits)
	}
	loud := []byte("the bearer token " + sha + " was pasted\n")
	if hits := engine.Scan(loud); len(hits) == 0 {
		t.Fatal("credential-shaped token did not fire")
	}
}

// The rule set is read once and reused: a hundred scans do not re-read the
// config, and the engine keeps its compiled rule count. A second load with the
// same path returns the same engine; a second load with a different path fails
// loudly instead of returning a partially-extended rule set.
func TestRuleSetIsLoadedOnceAndReused(t *testing.T) {
	engine := loadTestEngine(t)
	if got := engine.Loads(); got != 1 {
		t.Fatalf("expected one load after LoadEngine, got %d", got)
	}
	again, err := LoadEngine(rulesPath)
	if err != nil {
		t.Fatalf("loading the same path twice: %v", err)
	}
	if again != engine {
		t.Fatal("a second load of the same path built a new engine")
	}
	if _, err := LoadEngine(filepath.Join(corpusDir, "..", "spike.toml")); err == nil {
		t.Fatal("a second, different rules path did not fail loudly")
	}

	before := engine.RuleCount()
	scansBefore := engine.Scans()
	for i := 0; i < 100; i++ {
		engine.Scan([]byte("an ordinary prompt about the weather\n"))
	}
	if got := engine.Loads(); got != 1 {
		t.Errorf("rule set was loaded %d times across 100 scans", got)
	}
	if got := engine.Scans() - scansBefore; got != 100 {
		t.Errorf("expected 100 scans, got %d", got)
	}
	if got := engine.RuleCount(); got != before {
		t.Errorf("rule count moved from %d to %d", before, got)
	}
}

// A finding reports the byte offset of the rule's match, not a line number.
// Multi-line bodies exercise the off-by-one gitleaks' column base introduces
// after the first line.
func TestMatchOffsetPointsAtTheMatch(t *testing.T) {
	engine := loadTestEngine(t)
	secret := corpusValue(t, "pos-forgejo-40hex.txt", `\b[0-9a-f]{40}\b`)
	body := []byte("first line is ordinary\nsecond line mentions a token " + secret + "\n")
	hits := engine.Scan(body)
	if len(hits) != 1 {
		t.Fatalf("expected one hit, got %+v", hits)
	}
	if hits[0].RuleID != "forgejo-token-context" {
		t.Fatalf("unexpected rule %q", hits[0].RuleID)
	}
	at := hits[0].Offset
	if at < 0 || at >= len(body) {
		t.Fatalf("offset %d outside body of %d bytes", at, len(body))
	}
	if !strings.HasPrefix(strings.ToLower(string(body[at:])), "token") {
		t.Fatalf("offset %d does not start the rule match: %q", at, body[at:min(at+16, len(body))])
	}
}

// The fingerprint identifies a value without carrying it: stable per secret,
// distinct between secrets, and not the secret itself.
func TestFingerprintIsStableAndOpaque(t *testing.T) {
	secret := corpusValue(t, "pos-github-pat.txt", `ghp_[A-Za-z0-9]+`)
	first := fingerprint(secret)
	if first != fingerprint(secret) {
		t.Fatal("fingerprint is not stable for the same secret")
	}
	if first == fingerprint("another-secret") {
		t.Fatal("fingerprint collided for different secrets")
	}
	if len(first) != 12 {
		t.Fatalf("expected a 12-character fingerprint, got %q", first)
	}
	if strings.Contains(secret, first) || strings.Contains(first, secret) {
		t.Fatalf("fingerprint %q carries material from the secret", first)
	}
}

// Same secret in two requests: two hits, one fingerprint. This is how repeats
// get counted without storing values.
func TestRepeatedSecretKeepsOneFingerprint(t *testing.T) {
	engine := loadTestEngine(t)
	body, err := os.ReadFile(filepath.Join(corpusDir, "pos-github-pat.txt"))
	if err != nil {
		t.Fatal(err)
	}
	first := engine.Scan(body)
	second := engine.Scan(body)
	if len(first) == 0 || len(second) == 0 {
		t.Fatal("expected hits on both scans")
	}
	if first[0].Fingerprint != second[0].Fingerprint {
		t.Fatalf("fingerprints differ across identical bodies: %q vs %q",
			first[0].Fingerprint, second[0].Fingerprint)
	}
}
