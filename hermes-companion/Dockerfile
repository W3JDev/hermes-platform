FROM nginx:alpine

# Copy static web assets
COPY web/ /usr/share/nginx/html/

# Copy custom reverse-proxy configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
