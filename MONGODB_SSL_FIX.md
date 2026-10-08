# MongoDB TLS certificate validation

Production connections validate MongoDB TLS certificates. The application does not add `tlsAllowInvalidCertificates=true`, and a connection string that contains that option does not turn validation off.

## Production

Set:

```
APP_ENV=production
```

Do not set `MONGODB_TLS_ALLOW_INVALID_CERTIFICATES`. If that flag is true, or if `MONGODB_URI` includes `tlsAllowInvalidCertificates`, `tlsAllowInvalidHostnames`, or `tlsInsecure`, the process refuses to connect.

## Development only

Local MongoDB without TLS is unchanged. An Atlas connection validates certificates by default.

To skip validation on a development machine, set both:

```
APP_ENV=development
MONGODB_TLS_ALLOW_INVALID_CERTIFICATES=true
```

`APP_ENV=development` is already the default. The second variable is required. It has no effect when `APP_ENV` is anything else, including `production`.
