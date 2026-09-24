# MongoDB SSL Connection Fix

## Issue
Python 3.13 has stricter SSL/TLS requirements that can cause MongoDB Atlas connections to fail with:
```
SSL handshake failed: [SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error
```

## Solution

### Option 1: Update Connection String (Recommended for Development)
Add `tlsAllowInvalidCertificates=true` to your MongoDB connection string in `.env`:

```
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?tlsAllowInvalidCertificates=true
```

**Note:** This is a workaround for development. In production, fix the SSL certificate issue properly.

### Option 2: Update Python/PyMongo Versions
Try updating to the latest versions:
```bash
pip install --upgrade pymongo motor
```

### Option 3: Use Python 3.11 or 3.12
Python 3.13 may have compatibility issues. Consider using Python 3.11 or 3.12 for better MongoDB Atlas compatibility.

## Current Code Behavior
The code now automatically retries with relaxed SSL settings if the initial connection fails. However, the server may still hang during startup if MongoDB connection fails during startup.

## Quick Fix
1. Stop the server
2. Edit `backend/.env`
3. Add `?tlsAllowInvalidCertificates=true` to the end of your `MONGODB_URI`
4. Restart the server

Example:
```
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/?tlsAllowInvalidCertificates=true
```
