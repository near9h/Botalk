FROM nginx:1.27-alpine

# Drop default site, use ours.
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 3500

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -q --spider http://localhost:3500/ || exit 1

CMD ["nginx", "-g", "daemon off;"]