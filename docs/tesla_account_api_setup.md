# Tesla Developer & Fleet API Setup (100% Free Hosting Edition)

This guide walks you through registering a Tesla developer account, setting up OAuth 2.0 credentials, and hosting the signature keys for **free** using GitHub Pages or Vercel to support the **FreeCharge** service on your Synology NAS.

---

## 1. Prerequisites
1. **MFA Activation:** Enable **Multi-Factor Authentication (MFA)** on your personal Tesla account. Tesla *requires* MFA to grant access to the Developer Portal.
2. **Email Verification:** Confirm your Tesla account email is fully verified.

---

## 2. Choosing a Free Validation Host
> [!NOTE]
> Tesla's validator blocks shared Dynamic DNS hostnames (like `*.synology.me`, `*.duckdns.org`). Rather than purchasing a custom domain, you can use one of the two free developer hosting options below:

### Option A: GitHub Pages (Recommended)
Since you already have a GitHub account, you can host your keys directly on a free GitHub Pages site.

1. **Create the Repository:** 
   * Go to GitHub and create a new public repository.
   * **Crucial:** Name the repository exactly `<your-github-username>.github.io` (e.g., `mrpeel.github.io`). This configures it as a user-level root page.
2. **Create the Key Folders & `.nojekyll` File:**
   * Inside your local checkout of that repository, create a directory path: `.well-known/appspecific/`.
   * **Crucial:** Create an empty file named `.nojekyll` in the root directory. (By default, GitHub Pages uses Jekyll, which ignores directories starting with a dot. The `.nojekyll` file overrides this behavior).
3. **Commit the Public Key:**
   * Generate your key pair (see Section 4).
   * Copy the public key `tesla_public_key.pem` to `.well-known/appspecific/com.tesla.3p.public-key.pem`.
   * Commit and push `.nojekyll` and your `.well-known` directory to GitHub.
4. **Enable Pages in GitHub Settings:** 
   * Go to your repository on `github.com`.
   * Click **Settings** (tab at the top) > **Pages** (left sidebar).
   * Under **Build and deployment**, select **Deploy from a branch**.
   * Under **Branch**, choose `main` (or `master`) and `/ (root)`, then click **Save**.
   * Wait 1–2 minutes. A banner will appear at the top of the Pages settings page showing: *"Your site is live at https://<your-username>.github.io/"*.
5. Your public key will now be hosted at:  
   `https://<your-username>.github.io/.well-known/appspecific/com.tesla.3p.public-key.pem`

---

### Option B: Vercel (Alternative Setup)
Vercel provides free deployments with secure HTTPS domains (e.g., `myfreecharge.vercel.app`).

1. Sign up for a free hobbyist account at [Vercel](https://vercel.com) using your GitHub login.
2. On your local machine, create a new empty directory and set up the static files:
   ```bash
   mkdir -p vercel-tesla-host/public/.well-known/appspecific
   # Copy your public key there
   cp tesla_public_key.pem vercel-tesla-host/public/.well-known/appspecific/com.tesla.3p.public-key.pem
   ```
3. Install the Vercel CLI locally and deploy (or link the folder to a new GitHub repo and import it into Vercel):
   ```bash
   npm install -g vercel
   cd vercel-tesla-host
   vercel --prod
   ```
4. This will output a free URL (e.g., `https://<your-project>.vercel.app`). Your public key is now hosted at:  
   `https://<your-project>.vercel.app/.well-known/appspecific/com.tesla.3p.public-key.pem`

---

## 3. Registering for a Tesla Developer Account & Saving Secrets
1. Log in to the [Tesla Developer Portal](https://developer.tesla.com) using your Tesla account.
2. Select **Submit a New Request** to register your application:
   * **Allowed Origin URL:** Enter your free root domain (e.g., `https://<your-username>.github.io` or `https://<your-project>.vercel.app`).
   * **Allowed Redirect URI:** Enter `https://<your-username>.github.io/oauth/callback` (or your Vercel equivalent).
   * **Scopes Selection:** On the application scopes form, check the following boxes:
     * `[x] Vehicle Information` (maps to `vehicle_device_data` API scope)
     * `[x] Vehicle Location` (maps to `vehicle_location` API scope)
     * `[x] Vehicle Charging Management` (maps to `vehicle_charging_cmds` API scope)
     * `[x] Vehicle Commands` (maps to `vehicle_cmds` API scope)
3. Once approved, copy the credentials from your dashboard and add them to your Synology `.env` file:
   ```ini
   TESLA_CLIENT_ID=your_client_id_from_portal
   TESLA_CLIENT_SECRET=your_client_secret_from_portal
   ```

---

## 4. Key Generation & Registration (Synology NAS)
1. SSH into your Synology NAS and navigate to the project directory:
   ```bash
   ssh admin@192.168.1.x
   cd /volume1/homes/admin/tesla_tracker
   ```
2. Generate your keys:
   ```bash
   openssl ecparam -name prime256v1 -genkey -noout -out tesla_private_key.pem
   openssl ec -in tesla_private_key.pem -pubout -out tesla_public_key.pem
   ```
3. Upload `tesla_public_key.pem` to your choice of Option A or Option B above (named `com.tesla.3p.public-key.pem`).
4. **Obtain a Partner Token (Client Credentials):**
   Before registering your domain, you must request a developer authentication token (called the **Partner Token**). Run the following command (substituting your Client ID and Secret):
   ```bash
   curl -X POST https://auth.tesla.com/oauth2/v3/token \
     -H "Content-Type: application/json" \
     -d '{
       "grant_type": "client_credentials",
       "client_id": "<YOUR_CLIENT_ID>",
       "client_secret": "<YOUR_CLIENT_SECRET>",
       "scope": "openid"
     }'
   ```
   Copy the returned `access_token` string (this is your Partner Token).
5. **Register the Domain with Tesla:**
   Execute a POST request to register your public key URL using the Partner Token:
   ```bash
   curl -X POST https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/partner_accounts \
     -H "Authorization: Bearer <YOUR_PARTNER_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"domain": "<your-username>.github.io"}'
   ```

---

## 5. Exchanging Authorization Codes for User Tokens
Because you are configuring a personal automation task, you do not need a web server listening on the redirect callback port.

1. Navigate to this URL in your web browser:
   ```text
   https://auth.tesla.com/oauth2/v3/authorize?client_id=<YOUR_CLIENT_ID>&redirect_uri=https://<your-domain>/oauth/callback&response_type=code&scope=openid offline_access vehicle_device_data vehicle_location vehicle_charging_cmds vehicle_cmds&state=random_state
   ```
2. Log in and authorize your app.
3. The page will redirect to your domain and display an error page (since no server is running at `/oauth/callback`). **This is expected behavior.**
4. Extract the code from the URL bar of your browser (copy the text after `code=`).
5. Run the POST request locally to retrieve your keys:
   ```bash
   curl -X POST https://auth.tesla.com/oauth2/v3/token \
     -H "Content-Type: application/json" \
     -d '{
       "grant_type": "authorization_code",
       "client_id": "<YOUR_CLIENT_ID>",
       "client_secret": "<YOUR_CLIENT_SECRET>",
       "code": "<COPIED_AUTH_CODE>",
       "redirect_uri": "https://<your-domain>/oauth/callback"
     }'
   ```
6. Paste the returned `access_token` into your Synology `.env` file under `TESLA_API_TOKEN`.
