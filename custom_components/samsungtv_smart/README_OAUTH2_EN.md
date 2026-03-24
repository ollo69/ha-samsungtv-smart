# Samsung TV Smart - OAuth2 Integration

## Overview

This update adds **standalone OAuth2 support** for the Samsung TV Smart integration.
The integration can now work in 3 ways:

| Method | Description |
|--------|-------------|
| **OAuth2** ⭐ | Authentication via Samsung Developer Portal - Auto token refresh |
| **PAT** | Personal Access Token (legacy) |
| **ST Integration** | Reuses the token from the native SmartThings integration |

## Modified Files

```
samsungtv_smart/
├── manifest.json          # ✅ Added "application_credentials" dependency
├── const.py               # ✅ New OAuth constants
├── config_flow.py         # ✅ Full OAuth2 support
├── oauth_helper.py        # ✅ NEW - OAuth token management
├── strings.json           # ✅ OAuth messages
└── application_credentials.py  # (already present)
```

## Installation

### 1. Replace the Files

Copy these files into `custom_components/samsungtv_smart/`:
- `manifest.json`
- `const.py`
- `config_flow.py`
- `oauth_helper.py`
- `strings.json`

### 2. Restart Home Assistant

### 3. Create a SmartThings App (one-time only)

1. Go to https://developer.smartthings.com/
2. Sign in with your Samsung account
3. **New Project** → "Automation for the Home"
4. Give it a name (e.g. "Home Assistant TV")
5. In the sidebar: **Register App** → "OAuth2 / Credentials"
6. Fill in:
   - **App Name**: Home Assistant Samsung TV
   - **Redirect URI**: `https://my.home-assistant.io/redirect/oauth`
   - **Scopes**: ✅ `r:devices:*` and ✅ `x:devices:*`
7. **Save** → copy your **Client ID** and **Client Secret**

### 4. Add Credentials in Home Assistant

1. **Settings** → **Devices & Services**
2. Menu ⋮ → **Application Credentials**
3. **+ Add Application Credentials**
4. Select "Samsung TV Smart"
5. Paste your Client ID and Client Secret
6. **Add**

### 5. Configure the Integration

1. **Settings** → **Devices & Services** → **+ Add Integration**
2. Search for "Samsung TV Smart"
3. Select **🔐 OAuth2 (Recommended)**
4. You will be redirected to the Samsung login page
5. Grant the requested permissions
6. Select your TV and enter its IP address

## How OAuth Works

```
┌───────────────────────────────────────────────────────┐
│                    OAuth2 Token Lifecycle              │
├───────────────────────────────────────────────────────┤
│                                                        │
│  Initial authentication:                              │
│  User login → Access Token (24h) + Refresh Token      │
│                                                        │
│  Normal operation:                                    │
│  Token valid → Use access_token for API calls         │
│                                                        │
│  Token expired:                                        │
│  Token expires → Auto-refresh via refresh_token       │
│                → New access_token saved               │
│                                                        │
│  Refresh fails:                                        │
│  Refresh fail → Triggers re-authentication flow       │
│                                                        │
└───────────────────────────────────────────────────────┘
```

## Migrating from PAT

If you have already configured the integration with a PAT:

1. Go to the integration's **options**
2. Click **Reconfigure**
3. Check **🔄 Switch to OAuth2 authentication**
4. Follow the OAuth flow

## Troubleshooting

### "OAuth not configured"
→ First add the Application Credentials (step 4)

### "No Samsung TVs found"
→ Check that your TV is registered in the SmartThings app
→ Check that you have granted the correct scopes (`r:devices:*`, `x:devices:*`)

### "Token refresh failed"
→ Check your internet connection
→ Re-authenticate via the reauth flow
→ Check that your OAuth app is still active on developer.smartthings.com

## Technical Notes

- SmartThings OAuth tokens expire after **24 hours**
- Automatic refresh happens **5 minutes** before expiration
- Tokens are stored securely in the config entry
- Fully backward compatible with existing PAT and ST Integration setups
