# quicTransport_mouse_point_share

## prepare

- DownloadGoogle Chrome(M85~)
- Get origin trial key
  - Register QuicTransport Trials. [All Trials](https://developers.chrome.com/origintrials/#/trials/active)
  - Copy token.
  - Use Trials Token in `index.html`.
    - ```
        <meta
            http-equiv="origin-trial"
            content="<YOUR_TRIAL_TOKEN>"
        />
      ```
- Generate a certificate and a private key
  - ```
      openssl req -newkey rsa:2048 -nodes -keyout certificate.key \
      -x509 -out certificate.pem -subj '/CN=Test Certificate' \
      -addext "subjectAltName = DNS:localhost"
    ```
  - Compute the fingerprint of the certificate
    - ```
      openssl x509 -pubkey -noout -in certificate.pem |
      openssl rsa -pubin -outform der |
      openssl dgst -sha256 -binary | base64
      ```
    - Copy fingerprint.
- Open Google Chrome
  - ```
      open -a "Google Chrome" --args --origin-to-force-quic-on=localhost:4433 --ignore-certificate-errors-spki-list="<YOUR_CRTIFICATE_FINGERPRINT>"
    ```

### install

`pipenv install`

## run

`pipenv shell`
`python quic_transport_server.py certificate.pem certificate.key`
`python -m http.server 8000`
