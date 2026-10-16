FROM node:24-alpine
WORKDIR /app-f

COPY package.json ./
COPY yarn.lock ./

RUN yarn install --frozen-lockfile --non-interactive

COPY . .

RUN apk add --no-cache coreutils

EXPOSE 5173

CMD ["yarn", "dev", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
