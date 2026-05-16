# Google Photos API Authentication Guide

## Current Problem

The current OAuth2 implementation requires browser interaction for initial authentication and manual token renewal, which is problematic for remote deployments.

## Solution

### Enhanced OAuth2 with Refresh Tokens

**How it works:**
- Initial authentication is done once with browser interaction
- Refresh tokens allow automatic token renewal without user interaction
- Suitable for remote deployment once properly configured

**Implementation:**
- Enhanced `auth.py` with better error handling and logging
- Token manager utility for monitoring and maintenance
- Automatic refresh token handling

**Steps for Remote Deployment:**

1. **Initial Setup (Local Machine):**
   ```bash
   # Generate initial token with browser interaction
   python -m uploader.token_manager generate
   ```

2. **Validate Token:**
   ```bash
   # Check if token is suitable for remote deployment
   python -m uploader.token_manager validate
   ```

3. **Deploy to Remote Host:**
   - Copy `token.json` to remote host
   - Ensure `credentials.json` is also present
   - The application will automatically refresh tokens as needed

4. **Monitor Token Status:**
   ```bash
   # Check token status on remote host
   python -m uploader.token_manager status
   ```

**Refresh Token Lifespan:**
- Refresh tokens can last indefinitely if used regularly
- They become invalid if:
  - Not used for 6 months
  - User revokes access
  - User changes password (with Gmail scopes)
  - Maximum number of refresh tokens exceeded (50 per user)

## Best Practices for Remote Deployment

### 1. Token Management
- Store tokens securely (encrypted files, environment variables)
- Monitor token expiration
- Implement automatic refresh logic
- Log authentication events

### 2. Error Handling
- Graceful handling of expired tokens
- Automatic retry with refresh
- Alerting when manual intervention is required

### 3. Security
- Never commit tokens to version control
- Use secure file permissions (600)
- Consider using secret management services

### 4. Monitoring
- Regular token status checks
- Log authentication failures
- Set up alerts for token expiration

## Troubleshooting

### Common Issues:

1. **"Refresh token invalid"**
   - Solution: Generate new token with `python -m uploader.token_manager generate`

2. **"No refresh token available"**
   - Solution: Ensure OAuth flow includes offline access scope

3. **"Token expired and refresh failed"**
   - Solution: Check network connectivity and user permissions

### Debug Commands:

```bash
# Check token status
python -m uploader.token_manager status

# Test token refresh
python -m uploader.token_manager refresh

# Validate for remote deployment
python -m uploader.token_manager validate
```
