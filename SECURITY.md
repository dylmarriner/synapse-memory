# Security Policy

## Supported Versions

We release patches for security vulnerabilities in the latest stable release. Older versions do not receive security updates.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < latest| :x:                |

## Reporting a Vulnerability

We take the security of Synapse Memory seriously. If you believe you have found a security vulnerability, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

1. **Email**: Send details to **dylan@marriner.dev**

2. **GPG Encryption** (recommended): Encrypt your report using the GPG key below to ensure secure transmission.

3. **What to include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Affected versions
   - Potential impact
   - Any suggested mitigation (if known)

### GPG Key

```
-----BEGIN PGP PUBLIC KEY BLOCK-----

# Contact maintainer for the latest key fingerprint.
# Key ID: contact dylan@marriner.dev
# Fingerprint: Available on request

-----END PGP PUBLIC KEY BLOCK-----
```

To obtain the current GPG key, email **dylan@marriner.dev** with subject line "GPG key request" and you will receive the public key. You can also check the maintainer's GitHub profile for linked GPG keys.

### What to Expect

- **Acknowledgment**: You will receive an acknowledgment of your report within **48 hours**.
- **Updates**: We will provide updates on the status of the fix at reasonable intervals (typically every 5–7 days).
- **Resolution**: Once the vulnerability is fixed, we will:
  - Release a patch version
  - Credit the reporter (if desired)
  - Publish a security advisory via GitHub

## Disclosure Policy

We follow a coordinated disclosure process:

1. Reporter submits vulnerability details
2. Maintainer confirms and begins work on a fix
3. Fix is developed and tested
4. Patch is released, and advisory is published
5. Reporter is credited (opt-in)

We aim to resolve critical vulnerabilities within **14 days** of confirmation.

## Security-Related Configuration

### Production Deployment

When deploying Synapse Memory in production:

- Use strong, unique secrets for `SECRET_KEY` (generate with `openssl rand -hex 32`)
- Enable HTTPS with a valid TLS certificate
- Restrict database and Redis access to trusted networks only
- Use environment variables or a secret manager — never hardcode secrets
- Run the application as a non-root user inside the container
- Keep all dependencies updated

Thank you for helping keep Synapse Memory and its users safe.
