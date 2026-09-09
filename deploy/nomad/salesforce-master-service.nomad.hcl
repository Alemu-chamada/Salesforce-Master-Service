job "salesforce-master-service" {
  datacenters = ["dc1"]
  type = "service"

  group "api" {
    count = 1
    network {
      port "http" { to = 8000 }
    }

    task "app" {
      driver = "docker"
      config {
        image = "salesforce-master-service:latest"
        ports = ["http"]
      }

      vault { policies = ["salesforce-master-service"] }
      template {
        destination = "secrets/config.env"
        env = true
        data = <<EOF
{{ with secret "secrets/data/salesforce/salesforce-master-service-${NOMAD_META_environment}" }}
DATABASE_URL={{ .Data.data.DATABASE_URL }}
SF_CLIENT_ID={{ .Data.data.SF_CLIENT_ID }}
SF_CLIENT_SECRET={{ .Data.data.SF_CLIENT_SECRET }}
SF_JWT_PRIVATE_KEY_PATH={{ .Data.data.SF_JWT_PRIVATE_KEY_PATH }}
MINIO_ACCESS_KEY={{ .Data.data.MINIO_ACCESS_KEY }}
MINIO_SECRET_KEY={{ .Data.data.MINIO_SECRET_KEY }}
HMAC_SECRET_KEY_CORE={{ .Data.data.HMAC_SECRET_KEY_CORE }}
HMAC_SECRET_KEY_ENGINEER={{ .Data.data.HMAC_SECRET_KEY_ENGINEER }}
{{ end }}
EOF
      }

      service {
        name = "salesforce-master-service"
        port = "http"
        check {
          type = "http"
          path = "/api/health"
          interval = "30s"
          timeout = "5s"
        }
      }
      resources { cpu = 500 memory = 512 }
    }
  }
}
