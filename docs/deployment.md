# Docker Deployment Guide

## Local Development & Docker Hub Setup

1. **Login to Docker Hub**
   ```bash
   docker login
   ```
   Use your Docker Hub username and password/token

2. **Build and Push Multi-Architecture Image**
   ```bash
   # Enable BuildKit
   export DOCKER_BUILDKIT=1
   
   # Set up Docker buildx
   docker buildx create --use
   
   # Build and push for linux/amd64 (e.g. LXC server)
   docker buildx build --platform linux/amd64 \
     -t yourusername/photoprism-google-sync:latest \
     --push .
   ```

## Proxmox LXC Container Setup

1. **Install Docker and Docker compose**
    ```bash
    apt update && apt upgrade -y
    apt install -y curl
    curl -fsSL https://get.docker.com | sh
    apt install -y docker-compose

2. **Create Directory Structure**
   ```bash
   mkdir -p /opt/photoprism-sync/uploader
   cd /opt/photoprism-sync
   ```

3. **Add Google Photos credentials (one-time setup)**

   The Docker image does **not** contain credentials (they are excluded for security). You must place them on the LXC host and mount them into the container.

   - Copy `credentials.json` (from [Google Cloud Console](https://console.cloud.google.com)) to `/opt/photoprism-sync/uploader/credentials.json`.
   - Generate a token once (e.g. on your laptop): `python -m uploader.token_manager generate`, then copy `uploader/token.json` to `/opt/photoprism-sync/uploader/token.json`.
   - See [docs/authentication.md](authentication.md) for full setup.

   After this one-time setup, deployments only update the image; the mounted files stay in place.

   **Important:** Create the `settings.json` file and `downloader/data/` directory before the first run so Docker mounts them as files/directories rather than creating them as directories:
   ```bash
   touch /opt/photoprism-sync/settings.json
   mkdir -p /opt/photoprism-sync/downloader/data
   # copy your album_whitelist.csv into downloader/data/ if you have one
   ```

4. **Create docker-compose.yml**
   ```bash
   nano docker-compose.yml
   ```
   
   Add this content (the volume mounts provide credentials and persistent config at runtime):

   ```yaml
   services:
     photoprism-google-sync:
       image: yourusername/photoprism-google-sync:latest
       restart: unless-stopped
       ports:
         - "8080:8080"           # Web UI
       volumes:
         # Required: Google Photos API credentials (must exist on host)
         - ./uploader/credentials.json:/app/uploader/credentials.json:ro
         - ./uploader/token.json:/app/uploader/token.json
         # Persist web UI config and album whitelist across restarts
         - ./downloader/data:/app/downloader/data
         - ./settings.json:/app/settings.json
       environment:
         - PHOTOPRISM_SERVER_URL=your_url
         - PHOTOPRISM_USERNAME=your_username
         - PHOTOPRISM_PASSWORD=your_password
         - GOOGLE_PHOTOS_ALBUM_NAME=your_album
         - NUM_RANDOM_ALBUMS=5
         - NUM_RANDOM_PHOTOS=10
         - SCHEDULER_INTERVAL_SECONDS=86400
         - WEBAPP_PASSWORD=          # optional; set to password-protect the UI
         - WEBAPP_PORT=8080
   ```

   Once the container is running, the web UI is available at **http://&lt;host-ip&gt;:8080**. Use it to change photo selection settings, manage the album whitelist, and trigger an immediate sync run.

5. **Login to Docker Hub in LXC**
   ```bash
   docker login -u <docker_username>
   ```

6. **Pull and Run the Container**
   ```bash
   # Pull latest version
   docker-compose pull
   
   # Start container in detached mode
   docker-compose up -d
   ```

## Container Management Commands

1. **Check Running Containers**
   ```bash
   docker ps
   ```

2. **View Container Logs**
   ```bash
   # View logs
   docker-compose logs
   
   # Follow logs in real-time
   docker-compose logs -f
   ```

3. **Stop Container**
   ```bash
   docker-compose down
   ```

4. **Restart Container**
   ```bash
   docker-compose restart
   ```

5. **Update Container (Safe Method)**
   ```bash
   # Stop and remove existing containers and networks
   docker-compose down -v
   
   # Remove old images to prevent conflicts
   docker images | grep photoprism-google-sync  # List images
   docker rmi $(docker images | grep photoprism-google-sync | awk '{print $3}')  # Remove all versions
   
   # Clean up any dangling images and cached layers
   docker system prune -f
   
   # Pull new version
   docker-compose pull
   
   # Start with new version
   docker-compose up -d
   ```

## Environment Variables

Update the environment variables in `docker-compose.yml`:
```yaml
environment:
  - PHOTOPRISM_SERVER_URL=your_url          # Your PhotoPrism server URL
  - PHOTOPRISM_USERNAME=your_username       # PhotoPrism username
  - PHOTOPRISM_PASSWORD=your_password       # PhotoPrism password
  - GOOGLE_PHOTOS_ALBUM_NAME=your_album     # Target Google Photos album
  - NUM_RANDOM_ALBUMS=5                     # Initial default (overridden by web UI)
  - NUM_RANDOM_PHOTOS=10                    # Initial default (overridden by web UI)
  - SCHEDULER_INTERVAL_SECONDS=86400        # Initial default (overridden by web UI)
  - WEBAPP_PASSWORD=                        # Optional: password for the web UI
  - WEBAPP_PORT=8080                        # Port for the web UI (default 8080)
```

> Once you save settings via the web UI, they are written to `settings.json` and the corresponding env vars are no longer consulted for those keys.

## Troubleshooting

1. **Container not starting:**
   ```bash
   # Check logs for errors
   docker-compose logs
   ```

2. **Architecture issues:**
   - Image is built for linux/amd64 (e.g. LXC). Rebuild with buildx if needed.

3. **Permission issues:**
   - Ensure you're logged in to Docker Hub
   - Check file permissions
   - Verify environment variables

4. **Container stops unexpectedly:**
   - Check logs for errors
   - Verify all environment variables are set correctly
   - Ensure PhotoPrism and Google Photos credentials are valid
   - Confirm `uploader/credentials.json` and `uploader/token.json` exist on the host and are mounted (see step 3)

5. **ContainerConfig errors:**
   - This usually happens when there are conflicts with old images or containers
   - Always use the complete update procedure above to prevent these issues
   - Make sure to remove old images before pulling new ones
   - If issues persist, use the complete reset command provided above

6. **Web UI not accessible / settings don't persist:**
   - Confirm port 8080 is open on the host firewall
   - Ensure `settings.json` exists as a *file* on the host before `docker compose up` (`touch settings.json`)
   - Ensure `downloader/data/` exists as a *directory* on the host before `docker compose up`
   - Check the container logs for Flask startup errors: `docker-compose logs -f`