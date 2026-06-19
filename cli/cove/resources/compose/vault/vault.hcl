storage "raft" {
  path    = "/vault/data"
  node_id = "cove-1"
}

# Vault binds all interfaces inside the container so Docker's port mapping
# (127.0.0.1:8200 → container:8200) can reach it. Docker restricts external
# access to localhost; inter-container exposure on the same Docker network
# is acceptable for this single-node personal setup since both containers
# (Forgejo + Vault) are controlled by the same operator.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
ui           = true

# macOS does not support mlock; on Linux this is also fine for a personal
# single-node Vault since the host is trusted and there is no swap concern
# beyond the usual.
disable_mlock = true
