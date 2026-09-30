FROM node:22-bookworm-slim
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev --ignore-scripts
COPY src ./src
COPY sql ./sql
COPY web ./web
USER node
EXPOSE 8080
CMD ["node","src/server.mjs"]
