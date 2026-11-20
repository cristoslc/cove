package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

// maxBodyEnv is the scan cap. A body over the cap is forwarded unscanned and
// the skip is logged with a reason, so a gap is visible rather than silent.
const maxBodyEnv = "SECRETS_GUARD_MAX_BODY_BYTES"

// server is the observe-only proxy: it scans the request body, logs hits, and
// forwards the request untouched.
type server struct {
	engine   *Engine
	proxy    *httputil.ReverseProxy
	events   *eventLog
	maxBody  int64
	upstream *url.URL
}

func newServer(engine *Engine, upstream *url.URL, events *eventLog, maxBody int64) *server {
	s := &server{
		engine:   engine,
		events:   events,
		maxBody:  maxBody,
		upstream: upstream,
	}
	s.proxy = &httputil.ReverseProxy{
		// Rewrite rather than Director: SetURL keeps the inbound path and
		// query, and only names the backend.
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(upstream)
			pr.SetXForwarded()
		},
		// FlushInterval -1 flushes every write immediately. The ladder serves
		// 3600-second token streams; buffering any of it would break them.
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			s.events.upstreamError(baseEvent(r), err)
			w.WriteHeader(http.StatusBadGateway)
		},
	}
	return s
}

func baseEvent(r *http.Request) event {
	return event{Method: r.Method, Path: r.URL.Path}
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/healthz" {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"status":"ok"}`+"\n")
		return
	}

	started := time.Now()
	base := baseEvent(r)
	hits, scanned, skipped, err := s.inspect(r)
	if err != nil {
		// The body could not be read, so it cannot be forwarded intact either.
		// That is a transport failure, not a policy decision: no request is
		// blocked or altered for containing a secret.
		s.events.emit(event{
			Kind:   kindBodyReadError,
			Method: r.Method,
			Path:   r.URL.Path,
			Error:  err.Error(),
		})
		http.Error(w, "request body could not be read", http.StatusBadRequest)
		return
	}

	for _, hit := range hits {
		s.events.hit(base, hit)
	}
	if skipped != "" {
		declared := r.ContentLength
		if declared < 0 {
			declared = 0 // chunked: the length is not known up front
		}
		s.events.skipped(base, skipped, declared)
	} else {
		s.events.request(base, int64(scanned), len(hits), float64(time.Since(started).Microseconds())/1000)
	}

	s.proxy.ServeHTTP(w, r)
}

// inspect scans the body and hands the proxy back the exact bytes it received.
//
// Returns the hits, the scanned byte count (0 when skipped), a skip reason, and
// a read error. It never mutates the body's content: the request is rebuilt
// from the bytes that were read, so a hitting request reaches the backend
// byte-identical.
func (s *server) inspect(r *http.Request) ([]Hit, int, string, error) {
	if r.Body == nil || r.Body == http.NoBody {
		return nil, 0, "", nil
	}
	if r.ContentLength > s.maxBody {
		return nil, 0, "body_too_large", nil
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, s.maxBody+1))
	if err != nil {
		return nil, 0, "", err
	}
	if int64(len(body)) > s.maxBody {
		// Over the cap after reading: put the prefix back in front of the rest
		// of the stream so the upstream still receives every byte, and record
		// that this one was not scanned.
		r.Body = io.NopCloser(io.MultiReader(bytes.NewReader(body), r.Body))
		return nil, 0, "body_too_large", nil
	}

	r.Body = io.NopCloser(bytes.NewReader(body))
	r.ContentLength = int64(len(body))
	return s.engine.Scan(body), len(body), "", nil
}
