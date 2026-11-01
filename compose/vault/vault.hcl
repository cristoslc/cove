storage "raft" {
  path    = "/openbao/data"
  node_id = "cove-1"
}

# OpenBao binds all interfaces inside the container so Docker's port mapping
# (127.0.0.1:8200 → container:8200) can reach it. Docker restricts external
# access to localhost; inter-container exposure on the same Docker network
# is acceptable for this single-node personal setup since every container
# on it is controlled by the same operator.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
ui           = true

# `disable_mlock` was removed: OpenBao 2.0 dropped mlock entirely, so the
# directive is obsolete and the IPC_LOCK capability is gone from the service.
