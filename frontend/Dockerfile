FROM node:20-alpine AS build

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}

WORKDIR /app
ENV PATH="/app/node_modules/.bin:$PATH"

COPY package.json package-lock.json ./
RUN if [ -n "$HTTP_PROXY" ]; then \
      npm config set proxy $HTTP_PROXY && \
      npm config set https-proxy $HTTPS_PROXY && \
      npm config set strict-ssl false; \
    fi && \
    NODE_TLS_REJECT_UNAUTHORIZED=0 npm install

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
