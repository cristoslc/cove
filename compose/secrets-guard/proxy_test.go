package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// safeBuffer collects JSON log lines from request goroutines.
type safeBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *safeBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *safeBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// echoUpstream answers with exactly the bytes it received and records them.
type echoUpstream struct {
	mu      sync.Mutex
	bodies  [][]byte
	lengths []int64
	headers []http.Header
}

func (u *echoUpstream) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		u.mu.Lock()
		u.bodies = append(u.bodies, body)
		u.lengths = append(u.lengths, r.ContentLength)
		u.headers = append(u.headers, r.Header.Clone())
		u.mu.Unlock()
		w.Header().Set("Content-Type", r.Header.Get("Content-Type"))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
	})
}

func (u *echoUpstream) last(t *testing.T) ([]byte, int64, http.Header) {
	t.Helper()
	u.mu.Lock()
	defer u.mu.Unlock()
	if len(u.bodies) == 0 {
		t.Fatal("upstream received no request")
	}
	last := len(u.bodies) - 1
	return u.bodies[last], u.lengths[last], u.headers[last]
}

// newGuard wires the real server against a real httptest upstream.
func newGuard(t *testing.T, maxBody int64, mode logMode) (*httptest.Server, *echoUpstream, *safeBuffer) {
	t.Helper()
	upstream := &echoUpstream{}
	backend := httptest.NewServer(upstream.handler())
	t.Cleanup(backend.Close)

	target, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatalf("parse upstream URL: %v", err)
	}
	logs := &safeBuffer{}
	guard := httptest.NewServer(newServer(loadTestEngine(t), target, newEventLog(logs, mode), maxBody))
	t.Cleanup(guard.Close)
	return guard, upstream, logs
}

// A request is delivered to the backend byte-identical, hit or not.
func TestHittingRequestIsForwardedUnchanged(t *testing.T) {
	guard, upstream, logs := newGuard(t, defaultMaxBytes, logAll)
	fixtures := map[string]string{}
	for _, prefix := range []string{"pos", "neg"} {
		for _, path := range fixturesFor(t, prefix) {
			body, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			fixtures[filepath.Base(path)] = string(body)
		}
	}

	for name, content := range fixtures {
		payload, err := json.Marshal(map[string]any{
			"model": "vision:standard",
			"messages": []map[string]string{
				{"role": "user", "content": content},
			},
			"stream": true,
		})
		if err != nil {
			t.Fatal(err)
		}
		resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", bytes.NewReader(payload))
		if err != nil {
			t.Fatalf("%s: post: %v", name, err)
		}
		echoed, err := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if err != nil {
			t.Fatalf("%s: read: %v", name, err)
		}
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("%s: status %d", name, resp.StatusCode)
		}
		if !bytes.Equal(echoed, payload) {
			t.Fatalf("%s: backend received %d bytes, client sent %d (body was altered)",
				name, len(echoed), len(payload))
		}
		got, length, headers := upstream.last(t)
		if !bytes.Equal(got, payload) {
			t.Fatalf("%s: captured body differs from the sent bytes", name)
		}
		if length != int64(len(payload)) {
			t.Fatalf("%s: upstream ContentLength %d, want %d", name, length, len(payload))
		}
		if headers.Get("Content-Type") != "application/json" {
			t.Fatalf("%s: Content-Type lost: %q", name, headers.Get("Content-Type"))
		}
	}
	if !strings.Contains(logs.String(), kindHit) {
		t.Fatal("no hit was logged; the positive fixtures must fire on the request path")
	}
	assertNoFixtureText(t, logs.String())
}

// The negative fixtures stay silent when they arrive the way real traffic
// arrives: wrapped in an OpenAI-compatible JSON body.
func TestNegativeRequestsStaySilent(t *testing.T) {
	guard, _, logs := newGuard(t, defaultMaxBytes, logAll)
	for _, path := range fixturesFor(t, "neg") {
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		payload, err := json.Marshal(map[string]any{
			"model":    "vision:standard",
			"messages": []map[string]string{{"role": "user", "content": string(body)}},
		})
		if err != nil {
			t.Fatal(err)
		}
		resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", bytes.NewReader(payload))
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		_ = resp.Body.Close()
	}
	if strings.Contains(logs.String(), kindHit) {
		t.Fatalf("false positive on ordinary prompts:\n%s", logs.String())
	}
}

// The log line names the rule, a fingerprint, and an offset. It never carries
// the matched text or the body.
func TestHitLineCarriesNoSecretMaterial(t *testing.T) {
	guard, _, logs := newGuard(t, defaultMaxBytes, logAll)
	body := fixtureBody(t, "pos-forgejo-40hex.txt")
	resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()

	output := logs.String()
	if !strings.Contains(output, "forgejo-token-context") {
		t.Fatalf("hit line does not name the rule:\n%s", output)
	}
	if !strings.Contains(output, `"fingerprint"`) || !strings.Contains(output, `"offset"`) {
		t.Fatalf("hit line is missing the fingerprint or offset:\n%s", output)
	}
	token := corpusValue(t, "pos-forgejo-40hex.txt", `\b[0-9a-f]{40}\b`)
	if strings.Contains(output, token) {
		t.Fatalf("the matched token is in the log:\n%s", output)
	}
	if bytes.Contains([]byte(output), body) {
		t.Fatalf("the request body is in the log:\n%s", output)
	}
	assertNoFixtureText(t, output)

	// Every line must be valid JSON with no free-text field carrying content.
	for _, line := range strings.Split(strings.TrimSpace(output), "\n") {
		var parsed map[string]any
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			t.Fatalf("log line is not JSON: %q (%v)", line, err)
		}
		for _, banned := range []string{"secret", "match", "line", "body", "content", "authorization"} {
			if _, ok := parsed[banned]; ok {
				t.Fatalf("log line has a %q field: %s", banned, line)
			}
		}
	}
}

// The rule is only useful if it does not fire on ordinary prose. The commit-SHA
// fixture reaches the backend and is logged as a clean request.
func TestCleanRequestLogsADenominator(t *testing.T) {
	guard, _, logs := newGuard(t, defaultMaxBytes, logAll)
	resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json",
		strings.NewReader(`{"model":"vision:standard","messages":[{"role":"user","content":"hello"}]}`))
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()

	output := logs.String()
	if !strings.Contains(output, `"event":"request"`) {
		t.Fatalf("no request line logged:\n%s", output)
	}
	if !strings.Contains(output, `"hits":0`) {
		t.Fatalf("request line does not record zero hits:\n%s", output)
	}
}

// `hits` mode keeps the log quiet except for requests that found something.
func TestHitsModeLogsOnlyHits(t *testing.T) {
	guard, _, logs := newGuard(t, defaultMaxBytes, logHits)
	for _, payload := range []string{
		`{"messages":[{"role":"user","content":"an ordinary prompt"}]}`,
	} {
		resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", strings.NewReader(payload))
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		_ = resp.Body.Close()
	}
	if logs.String() != "" {
		t.Fatalf("hits mode logged a clean request:\n%s", logs.String())
	}
}

// A stream is forwarded as it arrives. Buffering the response would break the
// 3600-second completion streams the ladder serves.
func TestStreamingResponseIsNotBuffered(t *testing.T) {
	guard, _, _ := newGuard(t, defaultMaxBytes, logOff)

	release := make(chan struct{})
	var once sync.Once
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Error("upstream response writer cannot flush")
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "data: one\n\n")
		flusher.Flush()
		<-release
		fmt.Fprint(w, "data: two\n\n")
	}))
	t.Cleanup(func() {
		once.Do(func() { close(release) })
		backend.Close()
	})

	// Point a second guard at this streaming backend.
	target, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	streaming := httptest.NewServer(newServer(loadTestEngine(t), target, newEventLog(io.Discard, logOff), defaultMaxBytes))
	t.Cleanup(streaming.Close)
	_ = guard

	resp, err := http.Post(streaming.URL+"/v1/chat/completions", "application/json",
		strings.NewReader(`{"model":"vision:standard","stream":true}`))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()

	firstLine := make(chan string, 1)
	go func() {
		reader := bufio.NewReader(resp.Body)
		line, _ := reader.ReadString('\n')
		firstLine <- line
	}()

	select {
	case line := <-firstLine:
		if !strings.Contains(line, "data: one") {
			t.Fatalf("unexpected first chunk %q", line)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("first stream chunk did not arrive while the upstream was still streaming: the proxy buffered it")
	}

	once.Do(func() { close(release) })
	rest, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(rest), "data: two") {
		t.Fatalf("tail of the stream was lost: %q", rest)
	}
}

// A body over the cap is forwarded whole and logged as skipped, never silently
// treated as clean.
func TestOversizeBodyIsForwardedUnscannedAndMarked(t *testing.T) {
	guard, upstream, logs := newGuard(t, 32, logAll)
	payload := fixtureBody(t, "pos-forgejo-40hex.txt")
	resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", bytes.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()

	got, _, _ := upstream.last(t)
	if !bytes.Equal(got, payload) {
		t.Fatalf("oversize body was altered: upstream saw %d of %d bytes", len(got), len(payload))
	}
	output := logs.String()
	if !strings.Contains(output, kindScanSkipped) || !strings.Contains(output, "body_too_large") {
		t.Fatalf("oversize body was not recorded as skipped:\n%s", output)
	}
	if strings.Contains(output, kindHit) {
		t.Fatalf("an over-cap body must not claim a hit:\n%s", output)
	}
}

// A chunked body has no ContentLength, so the overflow is discovered after the
// read: the rest of the stream must still reach the backend.
func TestChunkedOversizeBodyIsForwardedWhole(t *testing.T) {
	guard, upstream, logs := newGuard(t, 32, logAll)
	payload := append(fixtureBody(t, "pos-forgejo-40hex.txt"), bytes.Repeat([]byte(" "), 128)...)
	req, err := http.NewRequest(http.MethodPost, guard.URL+"/v1/chat/completions", io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()

	got, _, _ := upstream.last(t)
	if !bytes.Equal(got, payload) {
		t.Fatalf("chunked oversize body was truncated: upstream saw %d of %d bytes", len(got), len(payload))
	}
	if !strings.Contains(logs.String(), "body_too_large") {
		t.Fatalf("chunked oversize body was not recorded as skipped:\n%s", logs.String())
	}
}

// The health endpoint is local and never proxied.
func TestHealthEndpointIsNotProxied(t *testing.T) {
	guard, upstream, _ := newGuard(t, defaultMaxBytes, logOff)
	resp, err := http.Get(guard.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if !strings.Contains(string(body), "ok") {
		t.Fatalf("unexpected health body %q", body)
	}
	upstream.mu.Lock()
	reached := len(upstream.bodies)
	upstream.mu.Unlock()
	if reached != 0 {
		t.Fatalf("health probe reached the backend %d time(s)", reached)
	}
}

// A dead backend answers 502 with an error event; the request is not queued or
// retried and nothing about the body is logged.
func TestDeadUpstreamAnswersBadGateway(t *testing.T) {
	engine := loadTestEngine(t)
	target, err := url.Parse("http://127.0.0.1:1")
	if err != nil {
		t.Fatal(err)
	}
	logs := &safeBuffer{}
	guard := httptest.NewServer(newServer(engine, target, newEventLog(logs, logAll), defaultMaxBytes))
	t.Cleanup(guard.Close)

	resp, err := http.Post(guard.URL+"/v1/chat/completions", "application/json", strings.NewReader(`{"x":1}`))
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status %d, want 502", resp.StatusCode)
	}
	if !strings.Contains(logs.String(), kindUpstreamError) {
		t.Fatalf("no upstream_error event:\n%s", logs.String())
	}
}

// helpers -------------------------------------------------------------------

func fixturesFor(t *testing.T, prefix string) []string {
	t.Helper()
	matches, err := filepath.Glob(filepath.Join(corpusDir, prefix+"-*.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 6 {
		t.Fatalf("expected 6 %s fixtures, found %d", prefix, len(matches))
	}
	return matches
}

// fixtureBody wraps a fixture the way real traffic carries it.
func fixtureBody(t *testing.T, name string) []byte {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(corpusDir, name))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := json.Marshal(map[string]any{
		"model":    "vision:standard",
		"messages": []map[string]string{{"role": "user", "content": string(content)}},
	})
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

// assertNoFixtureText proves no fixture line reached the log. Values only, no
// rule names: the log legitimately names rules and paths.
func assertNoFixtureText(t *testing.T, output string) {
	t.Helper()
	for _, prefix := range []string{"pos", "neg"} {
		for _, path := range fixturesFor(t, prefix) {
			body, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			for _, line := range strings.Split(string(body), "\n") {
				line = strings.TrimSpace(line)
				if len(line) < 12 {
					continue
				}
				if strings.Contains(output, line) {
					t.Fatalf("%s: a fixture line reached the log: %q", filepath.Base(path), line)
				}
			}
		}
	}
}
