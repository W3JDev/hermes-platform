FROM minio/minio:latest

# Official image has no default server command — without this the
# container prints help and exits immediately (Coolify: exited:unhealthy).
EXPOSE 9000 9001

VOLUME ["/data"]

CMD ["server", "/data", "--console-address", ":9001"]
