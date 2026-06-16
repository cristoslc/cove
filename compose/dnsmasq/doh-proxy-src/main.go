package main

import (
	"flag"
	"io"
	"log"
	"net"
	"net/http"
	"time"
)

func main() {
	upstream := flag.String("upstream", "127.0.0.1:5353", "DNS upstream address")
	listen := flag.String("listen", ":8053", "HTTP listen address")
	flag.Parse()

	http.HandleFunc("/dns-query", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil || len(body) == 0 {
			http.Error(w, "bad request", http.StatusBadRequest)
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
		resp := make([]byte, 512)
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
