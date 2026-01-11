import jwt
import time

# AuthKey_C9HZUNW6B4.p8
"""
-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQgi38CZLAvp6HQKbWc
F2ntisvLcHwp5zPDsClf93f4vumgCgYIKoZIzj0DAQehRANCAAR1LW1HdWMzEja3
UKa6jm82VeSB/+ns8imk3OtPm32o1Gle+emW+T+LaIDuZAmY9dqFnghb0DoI7pDE
wDzTAFEJ
-----END PRIVATE KEY-----
"""

with open('AuthKey_C9HZUNW6B4.p8', 'r') as kf:
    pri_key = kf.read()

now = int(time.time())
jwt_headers = {
    "kid": "C9HZUNW6B4", # key id
    "alg": "ES256"
}
jwt_payload = {
    "iss": "64GM3LZMY8", # team id
    "iat": now,
    "exp": now + 86400*180, # max
    "aud": "https://appleid.apple.com",
    "sub": "prod.likenovel" # client id - 서비스 id 부분
}

client_secret = jwt.encode(jwt_payload, pri_key, algorithm="ES256", headers=jwt_headers)

# 새로 생성된 애플 시크릿 키 값
print(client_secret)

