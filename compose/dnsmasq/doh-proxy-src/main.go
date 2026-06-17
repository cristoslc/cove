// Package main implements a minimal DNS-over-HTTPS (DoH) proxy that
// accepts RFC 8484 POST and GET requests on /dns-query and forwards
// the raw DNS wire-format body to a local dnsmasq instance over UDP.
//
// This proxy enables iOS and Android clients to resolve *.cove.<host>
// names via encrypted DNS when they cannot use plain UDP port 5353.
//
// Usage:
//
//	doh-proxy -upstream 127.0.0.1:5353 -listen :8053
package main

import (
	"encoding/base64"
	"flag"
	"io"
	"log"
	"net"
	"net/http"
	"time"
)

// dnsMaxUDPSize is the maximum DNS message size over UDP.
// RFC 1035 section 4.2.1 specifies 512 bytes; RFC 6891 (EDNS0)
// extends this to 4096. We use the EDNS0 maximum to avoid
// truncating legitimate responses with DNSSEC or large records.
const dnsMaxUDPSize = 4096

// maxBodySize limits the POST body. DNS wire messages are at most
// dnsMaxUDPSize bytes; 64KB is a generous ceiling that rejects
// memory-exhaustion attempts while accepting any valid query.
const maxBodySize = 65536

func main() {
	upstream := flag.String("upstream", "127.0.0.1:5353", "DNS upstream address")
	listen := flag.String("listen", ":8053", "HTTP listen address")
	flag.Parse()

	http.HandleFunc("/dns-query", func(w http.ResponseWriter, r *http.Request) {
		var body []byte
		var err error

		switch r.Method {
		case http.MethodPost:
			body, err = io.ReadAll(io.LimitReader(r.Body, maxBodySize))
			if err != nil || len(body) == 0 {
				http.Error(w, "bad request", http.StatusBadRequest)
				return
			}
		case http.MethodGet:
			// RFC 8484 section 4.1: GET requests carry the DNS wire
			// message as a base64url-encoded ?dns= query parameter.
			dnsParam := r.URL.Query().Get("dns")
			if dnsParam == "" {
				http.Error(w, "missing dns parameter", http.StatusBadRequest)
				return
			}
			body, err = base64.RawURLEncoding.DecodeString(dnsParam)
			if err != nil || len(body) == 0 {
				http.Error(w, "bad request", http.StatusBadRequest)
				return
			}
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		conn, err := net.DialTimeout("udp", *upstream, 5*time.Second)
		if err != nil {
			http.Error(w, "upstream unreachable", http.StatusBadGateway)
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(5 * time.Second))
		if _, err := conn.Write(body); err != nil {
			http.Error(w, "upstream write failed", http.StatusBadGateway)
			return
		}
		resp := make([]byte, dnsMaxUDPSize)
		n, err := conn.Read(resp)
		if err != nil {
			http.Error(w, "upstream read failed", http.StatusBadGateway)
			return
		}
		w.Header().Set("Content-Type", "application/dns-message")
		w.Write(resp[:n])
	})

	log.Printf("DoH proxy listening on %s, upstream %s", *listen, *upstream)
	log.Fatal(http.ListenAndServe(*listen, nil))
}