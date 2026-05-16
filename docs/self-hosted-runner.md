# Setting Up a Self-Hosted GitHub Actions Runner for LXC Deployment

This guide explains how to set up a self-hosted GitHub Actions runner on your LXC container for automated Docker deployment.

---

## 1. Setting up GitHub Secrets

In your GitHub repository:
1. Go to **Settings → Secrets and variables → Actions**
2. Add the following secrets:
   - `DOCKERHUB_USERNAME`: Your Docker Hub username
   - `DOCKERHUB_TOKEN`: Your Docker Hub access token (not your password)
   - `APP_DIRECTORY`: The absolute path to your app directory on the LXC (e.g., `/opt/photoprism-sync`)

---

## 2. Setting up Self-Hosted Runner in LXC

**A. Prepare your LXC container:**
```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y curl git docker.io
```

**B. Create a dedicated runner user:**
```bash
sudo useradd -m github-runner
sudo usermod -aG docker github-runner
```

**C. Switch to the runner user and set up the runner:**
```bash
sudo su - github-runner
mkdir ~/actions-runner && cd ~/actions-runner

# Download the latest runner (check for latest version at https://github.com/actions/runner/releases)
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Get the registration URL and token from your repo: Settings → Actions → Runners → New self-hosted runner
./config.sh --url https://github.com/YOUR_USERNAME/YOUR_REPO --token YOUR_TOKEN
```

**D. Install and start the runner as a service:**
```bash
# Still as github-runner user, in ~/actions-runner
touch .env  # (optional, for environment variables)
exit        # Return to root
cd /home/github-runner/actions-runner
sudo ./svc.sh install github-runner
sudo ./svc.sh start
```

**E. Give the runner user access to your app directory:**
```bash
sudo chown -R github-runner:github-runner /opt/photoprism-sync
```

---

## 3. Verify Setup

- Go to your repository → **Settings → Actions → Runners**
  - Your runner should show as "Idle"
- Test Docker access as the runner user:
  ```bash
  sudo su - github-runner
  docker ps
  ```
- Make sure the runner can access your app directory:
  ```bash
  ls /opt/photoprism-sync
  ```

---

## 4. Security Considerations

- **Runner Isolation:** Use a dedicated user and directory for the runner.
- **Permissions:** Only give the runner user access to what it needs (app directory, Docker group).
- **Network:** The runner only makes outbound connections to GitHub (no open ports required).
- **Secrets:** All sensitive data (tokens, paths) should be stored in GitHub Secrets.
- **Updates:** Regularly update the runner and system packages.

---

## 5. Maintenance

- **Check runner status:**
  ```bash
  sudo ./svc.sh status
  ```
- **View runner logs:**
  ```bash
  sudo tail -f /home/github-runner/actions-runner/_diag/*.log
  ```
- **Restart runner:**
  ```bash
  sudo ./svc.sh stop
  sudo ./svc.sh start
  ```
- **Update runner:**
  - Download the latest version from GitHub and repeat the setup steps.
- **Clean up Docker resources regularly:**
  ```bash
  docker system prune -f
  ```

---

## Deploy Step in Workflow

Add this job to your `.github/workflows/docker-build.yml`:

```yaml
deploy:
  name: Deploy to LXC
  needs: build
  runs-on: self-hosted
  steps:
    - name: Deploy new version
      run: |
        cd ${{ secrets.APP_DIRECTORY }}
        docker-compose down -v
        docker system prune -f -a --volumes -y
        docker-compose pull
        docker-compose up -d
```

> **Note:** Ensure `settings.json` and `downloader/data/` exist on the host before the first deployment so Docker volume mounts them correctly (see [deployment.md](deployment.md) step 3).

---

**Now, after every successful build on `main`, your LXC container will automatically pull the latest image and redeploy your app!** 