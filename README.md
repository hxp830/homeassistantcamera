# Gesture YOLO HA

Multi-source gesture recognition system for Home Assistant, with YOLO + MediaPipe, MQTT Discovery, and multilingual web UI.

## Docs

- Chinese: [README.zh-CN.md](README.zh-CN.md)
- English: [README.en.md](README.en.md)
- Russian: [README.ru.md](README.ru.md)

## Release

- Current tag: `v1.0.0`
- GitHub Releases are generated automatically when pushing tags like `v*` (see `.github/workflows/release.yml`).

## CI/CD Deployment

On every push to `main`, GitHub Actions can auto-sync to your server and restart the system service.

- Workflow: `.github/workflows/deploy.yml`
- Required repository secrets:
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT` (optional, default `22`)
  - `DEPLOY_PATH` (for example: `/home/linaro/gesture-yolo-ha`)
  - `DEPLOY_SERVICE` (for example: `gesture-yolo-ha.service`)
