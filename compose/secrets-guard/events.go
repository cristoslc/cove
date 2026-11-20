package main

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"time"
)

// logMode decides which request lines are written. Hits are always written
// unless the mode is off; a hit line never carries request content.
type logMode string

const (
	// logAll writes one line per request plus one line per hit. The request
	// lines are the denominator for a false-positive rate: hits over requests.
	logAll logMode = "all"
	// logHits writes the hit lines and a request line only when the request
	// hit a rule.
	logHits logMode = "hits"
	// logOff writes only scan skips and upstream errors, so a silent log is
	// never mistaken for a clean one.
	logOff logMode = "off"
)

func parseLogMode(value string) (logMode, error) {
	switch mode := logMode(value); mode {
	case logAll, logHits, logOff:
		return mode, nil
	default:
		return "", fmt.Errorf("SECRETS_GUARD_LOG must be all, hits or off (got %q)", value)
	}
}

// event is one JSON log line. Every field is a value this process generated:
// rule id, fingerprint, offset, byte count, duration. There is no field for
// the matched text, the request body, or a header, so no code path can put a
// credential in the log by accident.
type event struct {
	Time        string  `json:"ts"`
	Kind        string  `json:"event"`
	Method      string  `json:"method,omitempty"`
	Path        string  `json:"path,omitempty"`
	Rule        string  `json:"rule,omitempty"`
	Fingerprint string  `json:"fingerprint,omitempty"`
	Offset      *int    `json:"offset,omitempty"`
	Bytes       int64   `json:"bytes,omitempty"`
	MaxBytes    int64   `json:"max_bytes,omitempty"`
	Hits        *int    `json:"hits,omitempty"`
	ScanMS      float64 `json:"scan_ms,omitempty"`
	Reason      string  `json:"reason,omitempty"`
	Error       string  `json:"error,omitempty"`
	Rules       string  `json:"rules,omitempty"`
	RuleCount   int     `json:"rules_count,omitempty"`
	Upstream    string  `json:"upstream,omitempty"`
	Mode        string  `json:"mode,omitempty"`
}

const (
	kindStartup       = "startup"
	kindHit           = "secret_hit"
	kindRequest       = "request"
	kindScanSkipped   = "scan_skipped"
	kindUpstreamError = "upstream_error"
	kindBodyReadError = "body_read_error"
)

// eventLog serialises JSON lines onto one writer. A single mutex keeps
// concurrent requests from interleaving halves of a line.
type eventLog struct {
	mu   sync.Mutex
	out  io.Writer
	mode logMode
	now  func() time.Time
}

func newEventLog(out io.Writer, mode logMode) *eventLog {
	return &eventLog{out: out, mode: mode, now: time.Now}
}

func (l *eventLog) emit(e event) {
	e.Time = l.now().UTC().Format(time.RFC3339Nano)
	line, err := json.Marshal(e)
	if err != nil {
		// A struct of strings and numbers cannot fail to marshal; if it ever
		// does, the safe move is still not to print the struct.
		line = []byte(`{"event":"log_error"}`)
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	_, _ = l.out.Write(append(line, '\n'))
}

func (l *eventLog) hit(base event, hit Hit) {
	offset := hit.Offset
	base.Kind = kindHit
	base.Rule = hit.RuleID
	base.Fingerprint = hit.Fingerprint
	base.Offset = &offset
	l.emit(base)
}

func (l *eventLog) request(base event, bytes int64, hits int, scanMS float64) {
	if l.mode == logOff || (l.mode == logHits && hits == 0) {
		return
	}
	base.Kind = kindRequest
	base.Bytes = bytes
	base.Hits = &hits
	base.ScanMS = scanMS
	l.emit(base)
}

func (l *eventLog) skipped(base event, reason string, bytes int64) {
	base.Kind = kindScanSkipped
	base.Reason = reason
	base.Bytes = bytes
	l.emit(base)
}

func (l *eventLog) upstreamError(base event, err error) {
	base.Kind = kindUpstreamError
	base.Error = err.Error()
	l.emit(base)
}
