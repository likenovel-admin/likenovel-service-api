-- Keycloak 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS keycloak CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ln-admin 사용자에게 keycloak 데이터베이스 권한 부여
GRANT ALL PRIVILEGES ON keycloak.* TO 'ln-admin'@'%';
FLUSH PRIVILEGES;
