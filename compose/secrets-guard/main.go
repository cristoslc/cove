// Command secrets-guard is the observe-only secrets check that sits in front of
// the Bifrost gateway.
//
// It is a transparent reverse proxy: every request body is scanned against the
// repository's own `.gitleaks.toml`, hits are written as JSON lines without the
// matched text, and every request is forwarded to the backend unchanged. It
// never blocks and never alters a request. Blocking is a later decision with
// its own evidence; see docs/services/secrets-guard.md.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/zricethezav/gitleaks/v8/logging"
)

const (
	envListen   = "SECRETS_GUARD_LISTEN"
	envUpstream = "SECRETS_GUARD_UPSTREAM"
	envRules    = "SECRETS_GUARD_RULES"
	envLogMode  = "SECRETS_GUARD_LOG"

	defaultListen = ":8080"
	defaultRules  = "/etc/secrets-guard/gitleaks.toml"
	// 4 MiB is above any real prompt this ladder serves (a 250k-token context is
	// about 1 MiB of text) with headroom for an inline image, and bounds the
	// synchronous scan's worst case. Measured cost is in README.md.
	defaultMaxBytes = 4 << 20
)

func main() {
	// gitleaks' own logger writes finding text at trace/debug level. This
	// process must never print a match, so the library logger is disabled
	// outright rather than relying on a level.
	logging.Logger = zerolog.Nop()

	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "secrets-guard: %v\n", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return serve()
	}
	switch args[0] {
	case "healthcheck":
		return healthcheck()
	case "scan":
		return scanCommand(args[1:])
	default:
		return fmt.Errorf("unknown subcommand %q (use none to serve, or \"healthcheck\", \"scan\")", args[0])
	}
}

func serve() error {
	listen := envOr(envListen, defaultListen)
	rawUpstream := strings.TrimSpace(os.Getenv(envUpstream))
	if rawUpstream == "" {
		return fmt.Errorf("%s must name the backend to forward to (for example http://bifrost:8080)", envUpstream)
	}
	upstream, err := url.Parse(rawUpstream)
	if err != nil {
		return fmt.Errorf("%s is not a URL: %w", envUpstream, err)
	}
	if upstream.Scheme != "http" && upstream.Scheme != "https" {
		return fmt.Errorf("%s must be http or https (got %q)", envUpstream, upstream.Scheme)
	}
	if upstream.Host == "" {
		return fmt.Errorf("%s must carry a host (got %q)", envUpstream, rawUpstream)
	}

	rules := envOr(envRules, defaultRules)
	mode, err := parseLogMode(envOr(envLogMode, string(logAll)))
	if err != nil {
		return err
	}
	maxBody, err := parseByteSize(envOr(maxBodyEnv, strconv.Itoa(defaultMaxBytes)))
	if err != nil {
		return err
	}

	engine, err := LoadEngine(rules)
	if err != nil {
		return err
	}

	events := newEventLog(os.Stdout, mode)
	events.emit(event{
		Kind:      kindStartup,
		Rules:     rules,
		Upstream:  upstream.String(),
		Mode:      string(mode),
		MaxBytes:  maxBody,
		RuleCount: engine.RuleCount(),
	})

	srv := &http.Server{
		Addr:              listen,
		Handler:           newServer(engine, upstream, events, maxBody),
		ReadHeaderTimeout: 10 * time.Second,
		// Deliberately no ReadTimeout/WriteTimeout: a completion stream can
		// run for an hour (the ladder's 3600s read/send timeouts), and a
		// server-side write deadline would break exactly the traffic this
		// proxy is here to observe.
		IdleTimeout: 120 * time.Second,
	}

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	errs := make(chan error, 1)
	go func() {
		err := srv.ListenAndServe()
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		errs <- err
	}()

	select {
	case err := <-errs:
		return err
	case <-stop:
		return srv.Close()
	}
}

func healthcheck() error {
	port, err := listenPort(envOr(envListen, defaultListen))
	if err != nil {
		return err
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%s/healthz", port))
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("health endpoint answered %d", resp.StatusCode)
	}
	return nil
}

// scanCommand scans stdin once and prints hits. It exists for the image build
// check ("the shipped ruleset loads and detects") and for an operator proving
// the rule source on demand. It is not used on the request path.
func scanCommand(args []string) error {
	fs := flag.NewFlagSet("scan", flag.ContinueOnError)
	configPath := fs.String("config", envOr(envRules, defaultRules), "gitleaks rules file to load")
	if err := fs.Parse(args); err != nil {
		return err
	}
	engine, err := LoadEngine(*configPath)
	if err != nil {
		return err
	}
	body, err := io.ReadAll(os.Stdin)
	if err != nil {
		return err
	}
	out := json.NewEncoder(os.Stdout)
	for _, hit := range engine.Scan(body) {
		if err := out.Encode(hit); err != nil {
			return err
		}
	}
	return nil
}

// listenPort pulls the port out of a listen address such as ":8080" or
// "0.0.0.0:8080" for the in-container healthcheck.
func listenPort(listen string) (string, error) {
	_, port, err := net.SplitHostPort(listen)
	if err != nil || port == "" {
		return "", fmt.Errorf("cannot read a port from %s=%q: %w", envListen, listen, err)
	}
	return port, nil
}

func parseByteSize(value string) (int64, error) {
	size, err := strconv.ParseInt(value, 10, 64)
	if err != nil || size <= 0 {
		return 0, fmt.Errorf("%s must be a positive byte count (got %q)", maxBodyEnv, value)
	}
	return size, nil
}

func envOr(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}
