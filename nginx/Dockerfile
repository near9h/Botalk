FROM nginx:1.27-alpine

# Drop default site, use ours.
RUN rm /etc/nginx/conf.d/default.conf

# Self-signed certificate baked at image build time. Browsers will
# complain until the user installs the cert as trusted, but the wire
# is encrypted end-to-end and the download links can no longer be
# scraped by a passive eavesdropper. Regenerate by re-running
# `openssl req -x509 -newkey rsa:2048 -nodes` (see README).
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/ssl \
    && openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout /etc/nginx/ssl/selfsigned.key \
        -out /etc/nginx/ssl/selfsigned.crt \
        -subj "/CN=botgroup.local" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -days 3650

COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 3500 5050

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -q --spider --no-check-certificate https://localhost:5050/ || exit 1

CMD ["nginx", "-g", "daemon off;"]